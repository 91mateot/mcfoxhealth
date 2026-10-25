"""Generate only non-secret, frozen daily rollout parameters. Never deploys."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path


def release(anchor):
    start = date.fromisoformat(anchor)
    if start.isoformat() != anchor:
        raise ValueError('canonical anchor required')
    dates = [(start + timedelta(days=i)).isoformat() for i in range(-3, 89)]
    return {'AccessMode': 'daily', 'DailyAnchor': anchor,
            'DailyApprovedDates': ','.join(dates),
            'HealthMetricsTableName': 'fitness-health-metrics',
            'AllowedDate': '2026-10-23'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--anchor', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(release(args.anchor), indent=2) + '\n')


if __name__ == '__main__':
    main()
