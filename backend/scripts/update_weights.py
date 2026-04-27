"""
Adjust scoring weights without redeploying Lambda.

The compute function loads its scoring config from the fitness-user-config
table (key='scoring') with a 5-minute in-container TTL cache. After running
this script, next compute invocation picks up the new values.

Examples:
  # Shift HRV weight down, sleep up
  python3 backend/scripts/update_weights.py --hrv 0.35 --sleep 0.25

  # Change strain coefficient
  python3 backend/scripts/update_weights.py --strain-coef 2.2

  # Change baseline window
  python3 backend/scripts/update_weights.py --baseline-window 21
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--hrv", type=float, help="Recovery weight: HRV")
    parser.add_argument("--rhr", type=float, help="Recovery weight: RHR")
    parser.add_argument("--sleep", type=float, help="Recovery weight: sleep")
    parser.add_argument("--resp", type=float, help="Recovery weight: respiratory rate")
    parser.add_argument("--spo2", type=float, help="Recovery weight: SpO2")
    parser.add_argument("--wrist-temp", type=float, help="Recovery weight: wrist temperature")
    parser.add_argument("--strain-coef", type=float, dest="strain_coef", help="Strain A coefficient (default 2.0)")
    parser.add_argument("--baseline-window", type=int, dest="baseline_window", help="Baseline window days (default 14)")
    parser.add_argument("--normalize", action="store_true", help="Renormalize weights to sum to 1.0")
    args = parser.parse_args()

    boto3.setup_default_session(profile_name=args.profile, region_name=args.region)
    ddb = boto3.resource("dynamodb")
    table = ddb.Table("fitness-user-config")

    current = table.get_item(Key={"key": "scoring"}).get("Item")
    if not current:
        current = {
            "key": "scoring",
            "recovery_weights": {"hrv": 0.4, "rhr": 0.25, "sleep": 0.2, "resp": 0.05, "spo2": 0.05, "wrist_temp": 0.05},
            "strain_coefficient": 2.0,
            "baseline_window_days": 14,
        }

    from decimal import Decimal

    def D(x):
        return Decimal(str(x))

    weights = dict(current.get("recovery_weights", {}))
    changed = False
    for key, val in (
        ("hrv", args.hrv),
        ("rhr", args.rhr),
        ("sleep", args.sleep),
        ("resp", args.resp),
        ("spo2", args.spo2),
        ("wrist_temp", args.wrist_temp),
    ):
        if val is not None:
            weights[key] = D(val)
            changed = True

    if args.normalize:
        total = sum(float(v) for v in weights.values())
        if total > 0:
            weights = {k: D(float(v) / total) for k, v in weights.items()}
            changed = True

    current["recovery_weights"] = weights

    if args.strain_coef is not None:
        current["strain_coefficient"] = D(args.strain_coef)
        changed = True
    if args.baseline_window is not None:
        current["baseline_window_days"] = args.baseline_window
        changed = True

    current["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not changed:
        print("No changes requested. Current config:")
    else:
        table.put_item(Item=current)
        print("✓ Updated. New config:")

    print(json.dumps(
        {k: (float(v) if hasattr(v, "as_tuple") else v)
         for k, v in current.items()},
        indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
