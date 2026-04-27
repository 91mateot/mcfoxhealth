"""
Daily comparison: our scores vs Mateo's Whoop-proxy reference.

Reads from the fitness-calibration table (reference) and fitness-daily-scores
(our computed values). Prints a side-by-side for the last N days with delta
columns and summary stats so we can spot systematic bias.

Usage:
  python3 backend/scripts/calibration_report.py --days 7
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default="us-west-2")
    args = parser.parse_args()

    boto3.setup_default_session(profile_name=args.profile, region_name=args.region)
    ddb = boto3.resource("dynamodb")
    cal = ddb.Table("fitness-calibration")
    scores = ddb.Table("fitness-daily-scores")

    today = datetime.now(timezone.utc)
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    print(f"\n{'DATE':<12} {'OUR REC':>8} {'REF REC':>8} {'ΔREC':>6}    {'OUR STRN':>9} {'REF STRN':>9} {'ΔSTRN':>6}    {'OUR SLP':>8} {'REF SLP':>8} {'ΔSLP':>6}")
    print("-" * 110)

    rec_deltas = []
    strn_deltas = []
    slp_deltas = []

    for d in reversed(dates):
        ref = cal.get_item(Key={"date": d}).get("Item") or {}
        ours = scores.get_item(Key={"date": d}).get("Item") or {}

        our_rec = ours.get("recovery")
        ref_rec = ref.get("recovery")
        our_strn = ours.get("strain")
        ref_strn = ref.get("strain")
        our_slp = ours.get("sleep_score")
        ref_slp = ref.get("sleep")

        def fmt(v, prec=0):
            if v is None:
                return "—"
            if prec == 0:
                return f"{int(float(v))}"
            return f"{float(v):.{prec}f}"

        def diff(a, b):
            if a is None or b is None:
                return None
            return float(a) - float(b)

        d_rec = diff(our_rec, ref_rec)
        d_strn = diff(our_strn, ref_strn)
        d_slp = diff(our_slp, ref_slp)

        if d_rec is not None:
            rec_deltas.append(d_rec)
        if d_strn is not None:
            strn_deltas.append(d_strn)
        if d_slp is not None:
            slp_deltas.append(d_slp)

        print(
            f"{d:<12} "
            f"{fmt(our_rec):>8} {fmt(ref_rec):>8} {fmt(d_rec):>6}    "
            f"{fmt(our_strn, 1):>9} {fmt(ref_strn, 1):>9} {fmt(d_strn, 1):>6}    "
            f"{fmt(our_slp):>8} {fmt(ref_slp):>8} {fmt(d_slp):>6}"
        )

    print("\nSummary (our - reference):")
    def stats(label, vals, target_mae):
        if not vals:
            print(f"  {label}: no calibration data")
            return
        mae = sum(abs(v) for v in vals) / len(vals)
        me = sum(vals) / len(vals)
        status = "✓" if mae <= target_mae else "✗"
        print(f"  {label}: n={len(vals)}  mean_error={me:+.1f}  MAE={mae:.1f} (target ≤ {target_mae})  {status}")
    stats("recovery", rec_deltas, 5.0)
    stats("strain  ", strn_deltas, 1.0)
    stats("sleep   ", slp_deltas, 3.0)

    print(
        "\nTuning hints:\n"
        "  - If recovery MAE > 5, adjust recovery_weights via scripts/update_weights.py\n"
        "  - If strain systematically high/low, try --strain-coef 2.2 or 2.4\n"
        "  - If sleep off, revisit sleep_duration_target_min / efficiency thresholds\n"
    )


if __name__ == "__main__":
    main()
