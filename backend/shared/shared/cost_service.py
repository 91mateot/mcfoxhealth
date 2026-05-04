"""AWS Cost Explorer reader for the infra-cost dashboard tile.

Returns month-to-date and trailing-4-week spend broken down by AWS service.
Cached in UserConfigTable for 6h to avoid paying Cost Explorer's $0.01/query
on every Progress tab render. Numbers are unblended USD, net of any credits.
"""

from datetime import datetime, timedelta, timezone

import boto3

from shared.db import get_item, get_table, put_item

_CACHE_KEY = "infra_cost_cache"
_CACHE_TTL_SEC = 6 * 60 * 60  # 6h

# Costs from services the stack doesn't use are noise; keep the top-N list and
# lump the rest into "other" so the UI stays legible.
_TOP_SERVICES = 6

# Services the fitness stack is known to use. CE results are filtered to this
# list so totals reflect the fitness app only, not co-tenant workloads. Keeping
# it explicit (rather than using cost-allocation tags) avoids a manual Billing
# console step and still works for Bedrock, which doesn't propagate resource
# tags to cost data. Pad with common variants AWS uses across services.
FITNESS_APP_SERVICES = [
    "AWS Lambda",
    "Amazon DynamoDB",
    "Amazon Bedrock",
    "Amazon API Gateway",
    "AWS Secrets Manager",
    "AmazonCloudWatch",
    "Amazon CloudWatch",
    "Amazon EventBridge",
    "AWS CloudFormation",
    "AWS CloudTrail",
    "Amazon Simple Storage Service",
    "AWS Key Management Service",
]

_ce_client = None


def _ce():
    global _ce_client
    if _ce_client is None:
        _ce_client = boto3.client("ce", region_name="us-east-1")
    return _ce_client


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _short_service(name: str) -> str:
    if not name:
        return "other"
    mapping = {
        "AWS Lambda": "Lambda",
        "Amazon DynamoDB": "DynamoDB",
        "Amazon Bedrock": "Bedrock",
        "Amazon API Gateway": "API Gateway",
        "AWS Secrets Manager": "Secrets Mgr",
        "Amazon Simple Storage Service": "S3",
        "AmazonCloudWatch": "CloudWatch",
        "Amazon CloudWatch": "CloudWatch",
        "AWS CloudTrail": "CloudTrail",
        "EventBridge": "EventBridge",
        "Amazon EventBridge": "EventBridge",
        "AWS Key Management Service": "KMS",
    }
    return mapping.get(name, name.replace("Amazon ", "").replace("AWS ", ""))


def _reduce_services(totals: dict) -> list:
    pairs = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top = pairs[:_TOP_SERVICES]
    rest_sum = sum(v for _, v in pairs[_TOP_SERVICES:])
    out = [{"service": _short_service(s), "cost": round(v, 4)} for s, v in top if v > 0]
    if rest_sum > 0:
        out.append({"service": "other", "cost": round(rest_sum, 4)})
    return out


def _ce_by_service(start: str, end: str, granularity: str = "MONTHLY") -> list:
    """Call Cost Explorer and return a list of {period_start, totals: {service: usd}}.
    Start is inclusive, end is exclusive (CE convention). Filtered to the
    fitness-app service allowlist AND the us-west-2 region so co-tenant
    workloads don't pollute totals. The region filter is what keeps
    us-east-1 CloudWatch VendedLog spend from other workloads out of here."""
    resp = _ce().get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity=granularity,
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        Filter={
            "And": [
                {"Dimensions": {"Key": "SERVICE", "Values": FITNESS_APP_SERVICES}},
                {"Dimensions": {"Key": "REGION", "Values": ["us-west-2"]}},
            ]
        },
    )
    out = []
    for result in resp.get("ResultsByTime", []):
        totals: dict = {}
        for group in result.get("Groups", []):
            name = (group.get("Keys") or ["unknown"])[0]
            amount = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount") or 0)
            if amount > 0:
                totals[name] = totals.get(name, 0) + amount
        out.append(
            {
                "period_start": result.get("TimePeriod", {}).get("Start"),
                "period_end": result.get("TimePeriod", {}).get("End"),
                "totals": totals,
            }
        )
    return out


def compute_costs() -> dict:
    """Fresh pull from Cost Explorer. Returns the payload the frontend renders."""
    now = _now_utc()
    today = now.date()
    mtd_start = today.replace(day=1)
    mtd_end = today + timedelta(days=1)  # CE End is exclusive

    # Month-to-date single bucket.
    mtd_rows = _ce_by_service(mtd_start.isoformat(), mtd_end.isoformat(), "MONTHLY")
    mtd_totals = mtd_rows[0]["totals"] if mtd_rows else {}
    mtd_total = round(sum(mtd_totals.values()), 4)
    mtd_breakdown = _reduce_services(mtd_totals)

    # Trailing 4 calendar weeks, Monday-anchored.
    weeks_back = 4
    this_monday = today - timedelta(days=today.weekday())
    weekly_start = this_monday - timedelta(weeks=weeks_back - 1)
    weekly_end = today + timedelta(days=1)
    weekly_rows = _ce_by_service(weekly_start.isoformat(), weekly_end.isoformat(), "DAILY")

    # Bucket daily rows into their containing Monday-anchored week.
    week_buckets: dict = {}
    for row in weekly_rows:
        ps = row.get("period_start")
        if not ps:
            continue
        d = datetime.strptime(ps, "%Y-%m-%d").date()
        monday = d - timedelta(days=d.weekday())
        key = monday.isoformat()
        bucket = week_buckets.setdefault(key, {"week_start": key, "totals": {}})
        for svc, amt in row["totals"].items():
            bucket["totals"][svc] = bucket["totals"].get(svc, 0) + amt

    weekly = []
    for i in range(weeks_back):
        monday = (this_monday - timedelta(weeks=weeks_back - 1 - i)).isoformat()
        bucket = week_buckets.get(monday, {"week_start": monday, "totals": {}})
        total = round(sum(bucket["totals"].values()), 4)
        weekly.append(
            {
                "week_start": monday,
                "total": total,
                "breakdown": _reduce_services(bucket["totals"]),
            }
        )

    return {
        "month_to_date": {
            "period_start": mtd_start.isoformat(),
            "total": mtd_total,
            "breakdown": mtd_breakdown,
        },
        "weekly": weekly,
        "computed_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def get_costs(force: bool = False) -> dict:
    """Cached wrapper. Cache lives in UserConfigTable key=infra_cost_cache."""
    config = get_table("USER_CONFIG_TABLE")
    cached = get_item(config, {"key": _CACHE_KEY}) or {}
    if not force:
        fetched_at = cached.get("fetched_at_epoch") or 0
        age = int(_now_utc().timestamp()) - int(fetched_at)
        if cached.get("payload") and age < _CACHE_TTL_SEC:
            return {**cached["payload"], "cached": True, "age_sec": age}

    try:
        payload = compute_costs()
    except Exception as e:
        # Cost Explorer can 400/500 intermittently. Fall back to the last good
        # value if we have one; otherwise surface the error without crashing.
        if cached.get("payload"):
            return {**cached["payload"], "cached": True, "stale": True, "error": str(e)}
        raise

    put_item(
        config,
        {
            "key": _CACHE_KEY,
            "payload": payload,
            "fetched_at_epoch": int(_now_utc().timestamp()),
        },
    )
    return {**payload, "cached": False}
