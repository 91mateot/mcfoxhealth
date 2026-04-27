"""
Backfill Withings body measurements for a date range.

Usage:
  python3 backend/scripts/withings_backfill.py --days 90

Pulls weight, fat%, fat mass, muscle mass, hydration via a single getmeas call,
writes rows to fitness-health-metrics.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Make shared/ importable: backend/shared/ contains a `shared` package
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))

import boto3
from shared.db import get_table, put_item


WITHINGS_API = "https://wbsapi.withings.net/measure"
WITHINGS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"


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


def refresh_withings(profile, region, secret):
    data = urllib.parse.urlencode({
        "action": "requesttoken",
        "grant_type": "refresh_token",
        "client_id": secret["client_id"],
        "client_secret": secret["client_secret"],
        "refresh_token": secret["refresh_token"],
    }).encode()
    req = urllib.request.Request(
        WITHINGS_TOKEN_URL, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())
    if body.get("status") != 0:
        sys.exit(f"Withings refresh failed: status {body.get('status')}")
    new = body["body"]
    secret["access_token"] = new["access_token"]
    secret["refresh_token"] = new.get("refresh_token", secret["refresh_token"])
    secret["userid"] = str(new.get("userid", secret.get("userid", "")))
    secret["expires_at"] = int(time.time()) + int(new.get("expires_in", 10800))
    aws_put_secret(profile, region, "withings-oauth", secret)
    return secret


def getmeas(token, startdate, enddate):
    params = urllib.parse.urlencode({
        "action": "getmeas",
        "meastype": "1,6,8,76,77",
        "category": 1,
        "startdate": startdate,
        "enddate": enddate,
    })
    req = urllib.request.Request(
        f"{WITHINGS_API}?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


MEASURE_TYPES = {1: "weight", 6: "fat_ratio", 8: "fat_mass", 76: "muscle_mass", 77: "hydration"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()

    os.environ["AWS_PROFILE"] = args.profile
    os.environ["AWS_DEFAULT_REGION"] = args.region
    os.environ.setdefault("HEALTH_METRICS_TABLE", "fitness-health-metrics")
    boto3.setup_default_session(profile_name=args.profile, region_name=args.region)

    secret = aws_get_secret(args.profile, args.region, "withings-oauth")

    if not secret.get("access_token") or secret.get("expires_at", 0) - time.time() < 300:
        print("Refreshing Withings token…")
        secret = refresh_withings(args.profile, args.region, secret)

    end = int(time.time())
    start = end - args.days * 86400
    print(f"Querying measurements from {datetime.fromtimestamp(start, tz=timezone.utc).isoformat()} "
          f"to {datetime.fromtimestamp(end, tz=timezone.utc).isoformat()}")

    data = getmeas(secret["access_token"], start, end)
    if data.get("status") in (401, 601):
        print("Auth expired mid-call, refreshing and retrying…")
        secret = refresh_withings(args.profile, args.region, secret)
        data = getmeas(secret["access_token"], start, end)
    if data.get("status") != 0:
        sys.exit(f"Withings getmeas failed: status {data.get('status')}")

    groups = data.get("body", {}).get("measuregrps", [])
    print(f"Got {len(groups)} measurement groups")

    table = get_table("HEALTH_METRICS_TABLE")
    written = 0
    for grp in groups:
        grp_date = datetime.fromtimestamp(grp["date"], tz=timezone.utc).strftime("%Y-%m-%d")
        for m in grp.get("measures", []):
            mtype = MEASURE_TYPES.get(m["type"])
            if not mtype:
                continue
            value = m["value"] * (10 ** m["unit"])
            if mtype in ("weight", "fat_mass", "muscle_mass", "hydration"):
                value = round(value * 2.20462, 1)  # kg → lbs
                unit = "lbs"
            else:  # fat_ratio
                value = round(value, 1)
                unit = "%"
            put_item(table, {
                "date": grp_date,
                "metric_source": f"{mtype}#withings",
                "value": value,
                "unit": unit,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })
            written += 1

    print(f"\n✓ Backfill complete: {written} rows written.")


if __name__ == "__main__":
    main()
