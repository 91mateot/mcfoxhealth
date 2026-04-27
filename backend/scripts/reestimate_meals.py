"""
Re-estimate macros for meals logged with the old hardcoded-dummy signature.

Any meal stored with the telltale (cal=300, p=25, c=30, f=8) values was logged
by the pre-estimator frontend. This script finds them for a given date range
and replaces the macros in-place by calling the new /api/meal/estimate
endpoint with each meal's stored `name`.

Usage:
    python backend/scripts/reestimate_meals.py --date 2026-04-26
    python backend/scripts/reestimate_meals.py --start 2026-04-01 --end 2026-04-26
    python backend/scripts/reestimate_meals.py --date 2026-04-26 --dry-run
"""
import argparse
import json
import time
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urljoin

import boto3
import urllib.request


def _dec(v) -> Decimal:
    """DynamoDB Number type — floats must become Decimals."""
    return Decimal(str(v))

DUMMY_SIGNATURE = {"cal": 300, "p": 25, "c": 30, "f": 8}
API_BASE = "https://5vvp43vamk.execute-api.us-west-2.amazonaws.com"


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur.isoformat()
        cur += timedelta(days=1)


def _matches_dummy(item: dict) -> bool:
    """Return True if the item's macros exactly match the old hardcoded values."""
    for key, expected in DUMMY_SIGNATURE.items():
        actual = item.get(key)
        if actual is None:
            return False
        try:
            if float(actual) != float(expected):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _call_estimate(text: str) -> dict:
    req = urllib.request.Request(
        urljoin(API_BASE, "/api/meal/estimate"),
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single YYYY-MM-DD")
    parser.add_argument("--start", help="Range start YYYY-MM-DD")
    parser.add_argument("--end", help="Range end YYYY-MM-DD")
    parser.add_argument("--table", default="fitness-nutrition")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.date:
        dates = [args.date]
    elif args.start and args.end:
        dates = list(_daterange(date.fromisoformat(args.start), date.fromisoformat(args.end)))
    else:
        parser.error("Specify --date OR --start and --end")

    ddb = boto3.resource("dynamodb", region_name=args.region)
    table = ddb.Table(args.table)

    total_found = 0
    total_updated = 0
    for d in dates:
        resp = table.query(KeyConditionExpression="#d = :d",
                           ExpressionAttributeNames={"#d": "date"},
                           ExpressionAttributeValues={":d": d})
        items = resp.get("Items", [])
        meals = [m for m in items if str(m.get("meal_id", "")).startswith("meal_")]
        dummies = [m for m in meals if _matches_dummy(m)]
        if not dummies:
            continue
        print(f"\n{d}: {len(dummies)} dummy meal(s) found")
        total_found += len(dummies)
        for m in dummies:
            name = m.get("name", "").strip()
            if not name:
                print(f"  skip {m['meal_id']}: empty name")
                continue
            display = name[:70].replace("\n", " ")
            print(f"  {m['meal_id']}  {display!r}")
            if args.dry_run:
                continue
            try:
                est = _call_estimate(name)
            except Exception as e:
                print(f"    FAIL estimator: {e}")
                continue
            print(f"    -> {est['cal']} cal, P{est['p']} C{est['c']} F{est['f']} (confidence={est.get('confidence')})")
            table.update_item(
                Key={"date": d, "meal_id": m["meal_id"]},
                UpdateExpression="SET cal = :cal, p = :p, c = :c, f = :f, tag = :tag, reestimated_at = :ts",
                ExpressionAttributeValues={
                    ":cal": _dec(est["cal"]),
                    ":p": _dec(est["p"]),
                    ":c": _dec(est["c"]),
                    ":f": _dec(est["f"]),
                    ":tag": est.get("tag", m.get("tag", "")),
                    ":ts": str(int(time.time())),
                },
            )
            total_updated += 1
            time.sleep(0.3)  # gentle throttle on Bedrock

    print(f"\nSummary: found {total_found}, updated {total_updated}" + (" (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
