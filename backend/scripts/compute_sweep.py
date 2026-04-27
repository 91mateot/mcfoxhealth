"""
Sweep the ComputeFunction Lambda across a date range.

Used after a bulk backfill of HealthMetrics, to populate DailyScores for
all newly-backfilled dates. Invokes compute_day per date with a small
thread pool for parallelism.

Usage:
    python backend/scripts/compute_sweep.py --start 2025-01-01 --end 2025-12-31 \
        [--stack-name fitness-dashboard] [--region us-west-2] [--dry-run] \
        [--concurrency 4] [--skip-existing]
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import boto3


def _resolve_function_name(stack_name: str, region: str) -> str:
    cf = boto3.client("cloudformation", region_name=region)
    resp = cf.describe_stack_resource(
        StackName=stack_name,
        LogicalResourceId="ComputeFunction",
    )
    return resp["StackResourceDetail"]["PhysicalResourceId"]


def _resolve_scores_table(stack_name: str, region: str) -> str:
    cf = boto3.client("cloudformation", region_name=region)
    resp = cf.describe_stack_resource(
        StackName=stack_name,
        LogicalResourceId="DailyScoresTable",
    )
    return resp["StackResourceDetail"]["PhysicalResourceId"]


def _existing_dates(table_name: str, region: str, require_field: str | None = None) -> set[str]:
    """Return the set of dates already in DailyScoresTable.

    If `require_field` is set (e.g. 'recovery'), only dates whose row has
    that field populated are considered 'existing' — a partial row missing
    the required field will NOT be in the return set, so the sweep will
    recompute it.
    """
    ddb = boto3.client("dynamodb", region_name=region)
    dates = set()
    kwargs = {
        "TableName": table_name,
        "ProjectionExpression": "#d" + (", #f" if require_field else ""),
        "ExpressionAttributeNames": {"#d": "date", **({"#f": require_field} if require_field else {})},
    }
    while True:
        resp = ddb.scan(**kwargs)
        for item in resp.get("Items", []):
            d = item.get("date", {}).get("S")
            if not d:
                continue
            if require_field:
                # Only count as "existing" if the field is present AND non-null
                f = item.get(require_field)
                if f is None:
                    continue
                # DynamoDB nulls show as {"NULL": True}; skip those
                if f.get("NULL"):
                    continue
            dates.add(d)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return dates


def _invoke_compute(client, function_name: str, date_str: str) -> tuple[str, bool, str]:
    """Invoke ComputeFunction synchronously for a date. Returns (date, ok, msg)."""
    try:
        resp = client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"action": "compute_day", "date": date_str}),
        )
        payload = json.loads(resp["Payload"].read())
        if resp.get("FunctionError"):
            return (date_str, False, str(payload)[:200])
        # compute_day returns {"date":..., "recovery":..., "strain":..., "sleep_score":...}
        if isinstance(payload, dict) and payload.get("error"):
            return (date_str, False, str(payload.get("error"))[:200])
        return (date_str, True, f"recovery={payload.get('recovery')} strain={payload.get('strain')} sleep={payload.get('sleep_score')}")
    except Exception as e:
        return (date_str, False, str(e)[:200])


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--stack-name", default="fitness-dashboard")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip dates that already have a DailyScores row.")
    parser.add_argument("--skip-if-field", default=None,
                        help="Only skip dates whose row has this field populated "
                             "(e.g. 'recovery'). Use to re-run compute for rows "
                             "that exist but are partially populated.")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    all_dates = [d.isoformat() for d in _daterange(start, end)]
    print(f"Range: {args.start} .. {args.end}  ({len(all_dates)} days)")

    existing: set[str] = set()
    if args.skip_existing or args.skip_if_field:
        print("Loading existing DailyScores dates...")
        table_name = _resolve_scores_table(args.stack_name, args.region)
        existing = _existing_dates(table_name, args.region, require_field=args.skip_if_field)
        if args.skip_if_field:
            print(f"Rows with {args.skip_if_field} populated: {len(existing)}")
        else:
            print(f"Already scored: {len(existing)} dates")

    pending = [d for d in all_dates if d not in existing]
    print(f"To compute: {len(pending)}")

    if args.dry_run:
        print("(dry-run) sample first 5:", pending[:5])
        print("(dry-run) sample last 5:", pending[-5:])
        return

    fn_name = _resolve_function_name(args.stack_name, args.region)
    print(f"Target Lambda: {fn_name}")

    # boto3 Lambda client is thread-safe.
    lam = boto3.client("lambda", region_name=args.region)

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(_invoke_compute, lam, fn_name, d) for d in pending]
        for i, fut in enumerate(as_completed(futures), start=1):
            d, success, msg = fut.result()
            if success:
                ok += 1
            else:
                fail += 1
                print(f"  FAIL {d}: {msg}")
            if i % 25 == 0 or i == len(pending):
                print(f"  {i}/{len(pending)}  ok={ok} fail={fail}")

    print(f"\nDone. {ok} succeeded, {fail} failed.")


if __name__ == "__main__":
    main()
