"""
Re-estimate macros for meals.

By default, targets meals with the old hardcoded-dummy signature
(cal=300, p=25, c=30, f=8) — the pre-estimator frontend saved them all
with the same numbers. Pass --force to re-estimate every meal on the
given date range (useful after upgrading the estimator prompt to get
ingredient breakdowns, parsed times, and hydration on old meals).

Usage:
    python backend/scripts/reestimate_meals.py --date 2026-04-26
    python backend/scripts/reestimate_meals.py --date 2026-04-26 --force
    python backend/scripts/reestimate_meals.py --start 2026-04-01 --end 2026-04-26
    python backend/scripts/reestimate_meals.py --date 2026-04-26 --dry-run
"""
import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urljoin

import boto3
import urllib.request


def _dec(v) -> Decimal:
    """DynamoDB Number type — floats must become Decimals."""
    return Decimal(str(v))


def _dec_ingredients(ings):
    out = []
    for ing in ings or []:
        if not isinstance(ing, dict):
            continue
        out.append({
            "name": str(ing.get("name", ""))[:80],
            "portion": str(ing.get("portion", ""))[:60],
            "cal": _dec(ing.get("cal", 0)),
            "p": _dec(ing.get("p", 0)),
            "c": _dec(ing.get("c", 0)),
            "f": _dec(ing.get("f", 0)),
        })
    return out


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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _update_meal(table, d: str, meal_id: str, est: dict, prev_tag: str):
    """Overwrite estimate-produced fields on an existing meal row.

    Uses a single UpdateExpression; only includes fields the estimator
    returned so we don't blow away anything else (e.g., original `name`
    we keep, original_text if already stored).
    """
    sets = [
        "cal = :cal",
        "p = :p",
        "c = :c",
        "f = :f",
        "tag = :tag",
        "reestimated_at = :ts",
    ]
    vals = {
        ":cal": _dec(est.get("cal", 0)),
        ":p": _dec(est.get("p", 0)),
        ":c": _dec(est.get("c", 0)),
        ":f": _dec(est.get("f", 0)),
        ":tag": est.get("tag") or prev_tag or "",
        ":ts": datetime.now(timezone.utc).isoformat(),
    }
    if est.get("assumptions"):
        sets.append("assumptions = :assumptions")
        vals[":assumptions"] = [str(a)[:200] for a in est["assumptions"]]
    if est.get("confidence"):
        sets.append("confidence = :confidence")
        vals[":confidence"] = est["confidence"]
    if est.get("ingredients"):
        sets.append("ingredients = :ingredients")
        vals[":ingredients"] = _dec_ingredients(est["ingredients"])
    if est.get("time"):
        sets.append("#t = :time")
        vals[":time"] = est["time"]
    water_oz = est.get("water_oz")
    if water_oz is not None and water_oz > 0:
        sets.append("water_oz = :water_oz")
        vals[":water_oz"] = _dec(water_oz)

    kwargs = {
        "Key": {"date": d, "meal_id": meal_id},
        "UpdateExpression": "SET " + ", ".join(sets),
        "ExpressionAttributeValues": vals,
    }
    if ":time" in vals:
        kwargs["ExpressionAttributeNames"] = {"#t": "time"}
    table.update_item(**kwargs)

    # Also log the water intake if the estimator flagged this as a beverage.
    # Idempotent: only insert if no existing water_ row already points at this meal.
    if water_oz is not None and water_oz > 0:
        existing = table.query(
            KeyConditionExpression="#d = :d AND begins_with(meal_id, :prefix)",
            ExpressionAttributeNames={"#d": "date"},
            ExpressionAttributeValues={":d": d, ":prefix": "water_"},
        ).get("Items", [])
        already_logged = any(
            str(r.get("source_meal_id")) == meal_id for r in existing
        )
        if not already_logged:
            water_row = {
                "date": d,
                "meal_id": f"water_{int(time.time() * 1000)}",
                "oz": _dec(water_oz),
                "source_meal_id": meal_id,
                "source": "reestimate",
                "logged_at": datetime.now(timezone.utc).isoformat(),
            }
            table.put_item(Item=water_row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single YYYY-MM-DD")
    parser.add_argument("--start", help="Range start YYYY-MM-DD")
    parser.add_argument("--end", help="Range end YYYY-MM-DD")
    parser.add_argument("--table", default="fitness-nutrition")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Re-estimate every meal, not just dummy-signature ones. "
                             "Useful after upgrading the estimator prompt.")
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
        targets = meals if args.force else [m for m in meals if _matches_dummy(m)]
        if not targets:
            continue
        label = "meal(s)" if args.force else "dummy meal(s)"
        print(f"\n{d}: {len(targets)} {label} found")
        total_found += len(targets)
        for m in targets:
            name = (m.get("name") or "").strip()
            if not name:
                print(f"  skip {m['meal_id']}: empty name")
                continue
            # Prefer original_text when available (captures "at 3pm" etc. that
            # might have been trimmed out of the name).
            source_text = (m.get("original_text") or name).strip()
            display = source_text[:70].replace("\n", " ")
            print(f"  {m['meal_id']}  {display!r}")
            if args.dry_run:
                continue
            try:
                est = _call_estimate(source_text)
            except Exception as e:
                print(f"    FAIL estimator: {e}")
                continue
            extras = []
            if est.get("time"):
                extras.append(f"time={est['time']}")
            if est.get("water_oz"):
                extras.append(f"water={est['water_oz']}oz")
            if est.get("ingredients"):
                extras.append(f"ings={len(est['ingredients'])}")
            extra_str = (" · " + " ".join(extras)) if extras else ""
            print(f"    -> {est['cal']} cal, P{est['p']} C{est['c']} F{est['f']} "
                  f"({est.get('confidence')}){extra_str}")
            try:
                _update_meal(table, d, m["meal_id"], est, m.get("tag", ""))
            except Exception as e:
                print(f"    FAIL update: {e}")
                continue
            total_updated += 1
            time.sleep(0.3)  # gentle throttle on Bedrock

    print(f"\nSummary: found {total_found}, updated {total_updated}" + (" (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
