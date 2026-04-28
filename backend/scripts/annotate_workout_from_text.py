#!/usr/bin/env python3
"""Annotate a historical workout with lift notes from a text file.

Usage:
  uv run --with requests python backend/scripts/annotate_workout_from_text.py \\
    --date 2026-04-20 \\
    --file path/to/notes.txt

If --workout_id isn't given the script picks the first Strava row for the date
(or creates a manual shell if there's none).

Hits the public /api/workout/{date}/{id}/annotate endpoint. No auth today — the
existing dashboard is unauthenticated per HANDOFF.md (non-guessable URL is the
only moat). Keep this script off public servers.
"""
import argparse
import json
import sys
import urllib.request

API_BASE = "https://5vvp43vamk.execute-api.us-west-2.amazonaws.com"


def get_workout_id(date: str) -> str:
    with urllib.request.urlopen(f"{API_BASE}/api/workouts", timeout=15) as resp:
        data = json.loads(resp.read())
    for w in data.get("workouts", []):
        if w.get("date") == date:
            return w.get("strava_id") or "manual_backfill"
    return "manual_backfill"


def annotate(date: str, workout_id: str, text: str) -> dict:
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/api/workout/{date}/{workout_id}/annotate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--file", required=True, help="Path to the text file with lift notes")
    ap.add_argument("--workout_id", help="Optional strava_id; otherwise auto-detected.")
    args = ap.parse_args()

    with open(args.file, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        print("error: file is empty", file=sys.stderr)
        sys.exit(1)

    workout_id = args.workout_id or get_workout_id(args.date)
    print(f"Annotating workout {workout_id} on {args.date}…")
    result = annotate(args.date, workout_id, text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
