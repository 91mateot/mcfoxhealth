"""
Backfill Strava activities for a given date range.

Usage:
  python3 backend/scripts/strava_backfill.py --days 90

Pulls activities via /athlete/activities?after=<ts>, fetches HR streams per activity,
computes TRIMP + strain with shared/scoring.py, writes to fitness-workouts table.

Rate limits: Strava allows 100 req/15min, 1000/day. A 90-day backfill is
roughly 2 calls per activity × ~30-60 activities = well within limits.
Throttles to 1 req/sec defensively.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Make shared/ importable: backend/shared/ contains a `shared` package
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))

import boto3
from shared.db import get_table, put_item
from shared.scoring import compute_trimp, compute_strain, classify_hr_zone


STRAVA_API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"


def aws_get_secret(profile, region, name):
    result = subprocess.run(
        ["aws", "--profile", profile, "--region", region,
         "secretsmanager", "get-secret-value", "--secret-id", name,
         "--query", "SecretString", "--output", "text"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def aws_put_secret(profile, region, name, payload):
    subprocess.run(
        ["aws", "--profile", profile, "--region", region,
         "secretsmanager", "put-secret-value", "--secret-id", name,
         "--secret-string", json.dumps(payload)],
        capture_output=True, text=True, check=True,
    )


def refresh_strava(profile, region, secret):
    data = urllib.parse.urlencode({
        "client_id": secret["client_id"],
        "client_secret": secret["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": secret["refresh_token"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())
    secret["access_token"] = body["access_token"]
    secret["refresh_token"] = body.get("refresh_token", secret["refresh_token"])
    secret["expires_at"] = int(body.get("expires_at", int(time.time()) + int(body.get("expires_in", 21600))))
    aws_put_secret(profile, region, "strava-oauth", secret)
    return secret


def strava_get(path, token, _rate_limit_backoff=True):
    url = path if path.startswith("http") else f"{STRAVA_API}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        if e.code == 429 and _rate_limit_backoff:
            # 15-min window rate limit — sleep until the next quarter-hour boundary + buffer
            now = int(time.time())
            next_quarter = ((now // 900) + 1) * 900
            wait = next_quarter - now + 5
            print(f"   ⏸ rate-limited, sleeping {wait}s until next 15-min window…")
            time.sleep(wait)
            return strava_get(path, token, _rate_limit_backoff=False)
        try:
            body = json.loads(e.read())
        except Exception:
            body = None
        return body, e.code


def list_activities(token, after_ts, per_page=100):
    """Paginate through /athlete/activities?after=<ts>."""
    activities = []
    page = 1
    while True:
        body, status = strava_get(
            f"/athlete/activities?after={after_ts}&per_page={per_page}&page={page}",
            token,
        )
        if status != 200 or not isinstance(body, list):
            print(f"  list_activities page {page} failed: status {status}")
            break
        if not body:
            break
        activities.extend(body)
        if len(body) < per_page:
            break
        page += 1
        time.sleep(1)
    return activities


def fetch_activity_with_hr(token, activity_id):
    """Fetch full activity + HR stream. Returns (activity_dict, hr_data_list)."""
    activity, status = strava_get(f"/activities/{activity_id}", token)
    if status != 200 or not isinstance(activity, dict):
        return None, []
    time.sleep(1)
    streams, _ = strava_get(f"/activities/{activity_id}/streams?keys=heartrate&key_type=time", token)
    hr_stream = []
    if isinstance(streams, list):
        for s in streams:
            if s.get("type") == "heartrate":
                hr_stream = s.get("data", [])
                break
    return activity, hr_stream


def activity_to_workout_item(activity, hr_stream):
    start = activity.get("start_date_local", "")[:10]
    if not start:
        start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    item = {
        "date": start,
        "strava_id": str(activity["id"]),
        "title": activity.get("name", ""),
        "type": activity.get("sport_type", activity.get("type", "")),
        "dur": round(activity.get("elapsed_time", 0) / 60),
        "avgHR": round(activity.get("average_heartrate", 0), 1),
        "maxHR": round(activity.get("max_heartrate", 0)),
        "cal": round(activity.get("calories", 0)),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    if hr_stream:
        trimp_data = compute_trimp(hr_stream, sample_interval_sec=1.0)
        item["trimp"] = trimp_data["trimp"]
        item["strain"] = compute_strain(trimp_data["trimp"])
        item["zones"] = trimp_data["zone_minutes"]
    elif item["avgHR"] > 0:
        avg_zone = classify_hr_zone(item["avgHR"])
        est_trimp = item["dur"] * {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}[avg_zone]
        item["trimp"] = round(est_trimp, 1)
        item["strain"] = compute_strain(est_trimp)
        item["zones_estimated"] = True
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()

    # AWS creds/region for boto3
    os.environ["AWS_PROFILE"] = args.profile
    os.environ["AWS_DEFAULT_REGION"] = args.region
    os.environ.setdefault("WORKOUTS_TABLE", "fitness-workouts")
    boto3.setup_default_session(profile_name=args.profile, region_name=args.region)

    secret = aws_get_secret(args.profile, args.region, "strava-oauth")
    if not secret.get("access_token"):
        sys.exit("strava-oauth secret has no access_token — run strava_auth.py first")

    # Proactive refresh
    if secret.get("expires_at", 0) - time.time() < 300:
        print("Refreshing Strava token…")
        secret = refresh_strava(args.profile, args.region, secret)

    after_ts = int(time.time()) - args.days * 86400
    print(f"Listing activities since {datetime.fromtimestamp(after_ts, tz=timezone.utc).isoformat()}")
    activities = list_activities(secret["access_token"], after_ts)
    print(f"Found {len(activities)} activities")

    table = get_table("WORKOUTS_TABLE")

    # Build set of already-saved strava_ids to make this idempotent
    existing = set()
    try:
        paginator = boto3.client("dynamodb", region_name=args.region).get_paginator("scan")
        for page in paginator.paginate(TableName="fitness-workouts", ProjectionExpression="strava_id"):
            for item in page.get("Items", []):
                existing.add(item["strava_id"]["S"])
        print(f"Skipping {len(existing)} already-written activities")
    except Exception as e:
        print(f"Could not check existing: {e}")

    written = 0
    skipped = 0
    for i, summary in enumerate(activities, 1):
        aid = summary["id"]
        if str(aid) in existing:
            skipped += 1
            continue
        print(f"[{i}/{len(activities)}] {summary.get('name', '')} (id={aid})")
        activity, hr = fetch_activity_with_hr(secret["access_token"], aid)
        if activity is None:
            print(f"   skip — fetch failed")
            time.sleep(2)
            continue
        item = activity_to_workout_item(activity, hr)
        put_item(table, item)
        written += 1
        print(f"   → {item['date']} · {item['type']} · {item['dur']}min · strain {item.get('strain', '?')}")
        time.sleep(1)  # defensive throttle

    print(f"\n✓ Backfill complete: {written} workouts written, {skipped} skipped (already present).")


if __name__ == "__main__":
    main()
