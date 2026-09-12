import assert from "node:assert/strict";
import test from "node:test";
import { formatFreshness } from "../src/freshness.ts";

const now = Date.parse("2026-09-12T14:20:00Z");
const updatedAt = "2026-09-12T14:07:00Z";

test("before a manual check, the label describes source age", () => {
  assert.equal(formatFreshness({ updatedAt, checkedAt: null, now }), "updated 13m ago");
});

test("a successful check does not reset unchanged source freshness", () => {
  assert.equal(
    formatFreshness({ updatedAt, checkedAt: now, now }),
    "checked just now · data 13m ago",
  );
  assert.equal(
    formatFreshness({ updatedAt, checkedAt: now, now: now + 120_000 }),
    "checked 2m ago · data 15m ago",
  );
});

test("a new source timestamp changes only the data clock", () => {
  assert.equal(
    formatFreshness({ updatedAt: new Date(now + 120_000).toISOString(), checkedAt: now, now: now + 120_000 }),
    "checked 2m ago · data just now",
  );
});

test("pending and rejected refreshes take precedence over a previous success", () => {
  assert.equal(
    formatFreshness({ updatedAt, checkedAt: now, now, refreshing: true, refreshFailed: true }),
    "refreshing app data…",
  );
  assert.equal(
    formatFreshness({ updatedAt, checkedAt: now, now, refreshFailed: true }),
    "refresh failed · retry",
  );
});

test("successful requests with absent or invalid source timestamps preserve missingness", () => {
  for (const source of [null, undefined, "", "invalid"]) {
    assert.equal(formatFreshness({ updatedAt: source, checkedAt: null, now }), "no data yet");
    assert.equal(formatFreshness({ updatedAt: source, checkedAt: now, now }), "checked just now · no data yet");
  }
});

test("ages advance through minute, hour and day boundaries without hiding the date", () => {
  for (const [elapsed, age] of [[59_999, "just now"], [60_000, "1m ago"], [3_600_000, "1h ago"], [86_400_000, "1d ago"], [172_800_000, "2d ago"]]) {
    assert.equal(
      formatFreshness({ updatedAt: new Date(now).toISOString(), checkedAt: now, now: now + elapsed }),
      `checked ${age} · data ${age}`,
    );
  }
});

test("clock skew cannot produce negative ages", () => {
  assert.equal(
    formatFreshness({ updatedAt: new Date(now + 1000).toISOString(), checkedAt: now + 1000, now }),
    "checked just now · data just now",
  );
});
