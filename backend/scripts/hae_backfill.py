"""
One-time HAE backfill script.

Reads a HealthAutoExport JSON file (v2, daily-summarized) and writes rows
directly to DynamoDB using the same parsing logic as the ingest Lambda.

Why a standalone script: a 2+ MB payload exceeds API Gateway's 10 MB ceiling
only if encoded naively, but driving it through the Lambda would still
require multiple network round-trips. Direct boto3 `batch_writer` writes
let us process a 16-month export in seconds with no infrastructure.

Usage:
    python backend/scripts/hae_backfill.py path/to/HealthAutoExport.json \
        --stack-name fitness-dashboard --region us-west-2 [--dry-run]
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

import boto3


ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
INGEST_HANDLER = ROOT / "functions" / "ingest" / "handler.py"


def _load_ingest_handler():
    """Import the ingest Lambda handler as a module without triggering its
    boto3/AWS-wired helpers. We only need its parser functions."""
    sys.path.insert(0, str(SHARED))
    # Stub out the `shared.db` module so importing handler doesn't fail
    # when we later want to redirect writes through our batch_writer.
    spec = importlib.util.spec_from_file_location("hae_ingest_handler", INGEST_HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_table_name(stack_name: str, region: str) -> str:
    cf = boto3.client("cloudformation", region_name=region)
    resp = cf.describe_stack_resource(
        StackName=stack_name,
        LogicalResourceId="HealthMetricsTable",
    )
    return resp["StackResourceDetail"]["PhysicalResourceId"]


class CapturingTable:
    """Stand-in for a DynamoDB Table that records every put_item call.

    We replace the ingest Lambda's shared.db helpers with one that routes
    writes here. After parsing, we hand the captured rows to a real
    DynamoDB batch_writer for efficient bulk inserts.
    """

    def __init__(self):
        self.items: list[dict] = []

    def put_item(self, Item=None, **_kw):
        # Dedup by (date, metric_source) — parsers can emit the same row
        # multiple times (e.g. when multiple input shapes overlap).
        self.items.append(dict(Item) if Item else {})


def _patch_ingest_db(module, capture: CapturingTable):
    """Replace the ingest module's get_table/put_item with our capture."""
    import shared.db as db_mod

    def fake_get_table(_env):
        return capture

    def fake_put_item(table, item):
        table.put_item(Item=item)

    db_mod.get_table = fake_get_table
    db_mod.put_item = fake_put_item
    # Module-level imports already resolved; patch at module too in case
    module.get_table = fake_get_table
    module.put_item = fake_put_item


def _dedup(items: list[dict]) -> list[dict]:
    """Keep the latest ingested_at per (date, metric_source)."""
    seen: dict[tuple, dict] = {}
    for item in items:
        key = (item.get("date"), item.get("metric_source"))
        if not key[0] or not key[1]:
            continue
        prev = seen.get(key)
        if prev is None or (item.get("ingested_at", "") > prev.get("ingested_at", "")):
            seen[key] = item
    return list(seen.values())


def _to_dynamodb_safe(item: dict) -> dict:
    """DynamoDB doesn't accept Python floats; convert to Decimal."""
    from decimal import Decimal

    def conv(v):
        if isinstance(v, float):
            return Decimal(str(v))
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    return {k: conv(v) for k, v in item.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="HealthAutoExport JSON file")
    parser.add_argument("--stack-name", default="fitness-dashboard")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Loading {args.file}")
    with open(args.file) as f:
        payload = json.load(f)

    data_field = payload.get("data")
    if isinstance(data_field, dict):
        metrics = data_field.get("metrics") or []
    elif isinstance(data_field, list):
        metrics = data_field
    else:
        raise SystemExit("unexpected payload shape")
    print(f"Found {len(metrics)} metric entries in payload")

    # Load ingest module and wire its writes to our capture
    module = _load_ingest_handler()
    capture = CapturingTable()
    _patch_ingest_db(module, capture)

    # Invoke the ingest parser on the payload. It handles all the name
    # normalization (HAE_NAME_MAP), sleep_analysis special-case, triple HR
    # expansion, and per-metric aggregation.
    module._handle_hae_metrics_array(metrics)

    rows_raw = capture.items
    rows = _dedup(rows_raw)
    print(f"Parser emitted {len(rows_raw)} rows ({len(rows)} after dedup by (date, metric_source))")

    # Per-metric + date coverage summary
    from collections import Counter
    by_metric = Counter(r.get("metric_source") for r in rows)
    dates = sorted({r.get("date") for r in rows if r.get("date")})
    print(f"\nCoverage: {len(dates)} distinct dates from {dates[0] if dates else 'n/a'} to {dates[-1] if dates else 'n/a'}")
    print("Per-metric row counts:")
    for ms, n in sorted(by_metric.items(), key=lambda x: -x[1]):
        print(f"  {ms}: {n}")

    if args.dry_run:
        print("\n(dry-run: no writes)")
        return

    # Resolve actual DynamoDB table name from CloudFormation
    print(f"\nResolving table name from stack {args.stack_name} in {args.region}")
    table_name = _resolve_table_name(args.stack_name, args.region)
    print(f"Target table: {table_name}")

    # Bulk write via batch_writer
    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(table_name)

    print(f"\nWriting {len(rows)} rows to DynamoDB...")
    written = 0
    with table.batch_writer(overwrite_by_pkeys=["date", "metric_source"]) as bw:
        for row in rows:
            bw.put_item(Item=_to_dynamodb_safe(row))
            written += 1
            if written % 250 == 0:
                print(f"  ...{written} / {len(rows)}")
    print(f"Done. {written} rows written.")


if __name__ == "__main__":
    main()
