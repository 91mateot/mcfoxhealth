"""Tests for the shard-aware HAE samples ledger (item-size cap fix).

Production evidence: PutItem raised ValidationException "Item size has
exceeded the maximum allowed size" 6x in 3 days on the ingest Lambda, aborting
whole HAE pushes (silent data loss). Root cause: _merge_samples_and_aggregate
wrote an unbounded samples list into one DynamoDB item; a single high-frequency
metric (steps#hae_samples ~9,226 samples/day) blew past the 400KB per-item
hard cap. Fix: shard the ledger across <base>_samples, _samples#001, #002, ...

These tests cover the required guarantees:
  - a day exceeding one shard writes multiple shards (no unbounded single put)
  - the aggregate over sharded data equals the aggregate over the same samples
  - re-sending an already-stored timestamp is idempotent ACROSS shards
  - a pre-existing large legacy single <base>_samples row is read + migrated
    forward into shards without dropping points
  - the _no_ts_ fallback still folds values in and does not collide cross-shard
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))

from shared.samples_ledger import SHARD_SIZE, shard_key, merge_samples_from_map


class FakeTable:
    """DynamoDB stand-in: last-write-wins per composite key on read, matching
    live PutItem/GetItem semantics for the merge-guard path."""

    def __init__(self):
        self.items = []

    def put_item(self, Item=None, **_kw):
        from decimal import Decimal

        def unwrap(v):
            if isinstance(v, Decimal):
                return float(v) if v != int(v) else int(v)
            if isinstance(v, dict):
                return {k: unwrap(x) for k, x in v.items()}
            if isinstance(v, list):
                return [unwrap(x) for x in v]
            return v

        self.items.append(unwrap(Item))

    def get_item(self, Key=None, **_kw):
        if not Key:
            return {}
        for item in reversed(self.items):
            if all(item.get(k) == v for k, v in Key.items()):
                return {"Item": item}
        return {}

    def rows(self, metric_source):
        """All rows ever put for a metric_source, oldest-first."""
        return [i for i in self.items if i["metric_source"] == metric_source]

    def latest(self, metric_source):
        """Most recent row for a metric_source, or None."""
        rows = self.rows(metric_source)
        return rows[-1] if rows else None

    def latest_map(self):
        """Reduce to the live view: {metric_source: most-recent item}."""
        m = {}
        for i in self.items:
            m[i["metric_source"]] = i
        return m


def _fresh_module():
    import shared.db as db_mod
    fake = FakeTable()
    db_mod.get_table = lambda _env: fake
    db_mod.put_item = lambda table, item: table.put_item(Item=item)
    db_mod.get_item = lambda table, key: (table.get_item(Key=key) or {}).get("Item") or {}

    # Ensure the ingest handler wins module resolution even if another test
    # file left a different `handler` (api/coach) cached in sys.modules.
    sys.path.insert(0, os.path.join(ROOT, "functions", "ingest"))
    sys.modules.pop("handler", None)
    import handler  # noqa
    handler._trigger_compute = lambda *_a, **_k: None
    return handler, fake


def _all_ledger_shards(table, base_key):
    """Live (last-write-wins) shards for base_key: shard 0 then #001, #002..."""
    latest = table.latest_map()
    shards = []
    index = 0
    while True:
        item = latest.get(shard_key(base_key, index))
        if not item:
            break
        shards.append(item)
        index += 1
    return shards


def _merged_ledger_samples(table, base_key):
    """Reassemble every live shard into a flat {ts: v} dict."""
    merged = {}
    for shard in _all_ledger_shards(table, base_key):
        for s in shard.get("samples") or []:
            if s.get("ts"):
                merged[s["ts"]] = s["v"]
    return merged


# ─── 1. A day exceeding one shard writes multiple shards ─────────────

def test_over_one_shard_writes_multiple_shards_no_single_unbounded_put():
    h, t = _fresh_module()
    n = SHARD_SIZE + 500  # forces exactly 2 shards
    pairs = [(f"2026-08-13T{i:06d}", float(i)) for i in range(n)]
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", pairs)

    shards = _all_ledger_shards(t, "steps#hae_samples")
    assert len(shards) == 2, f"expected 2 shards for {n} samples, got {len(shards)}"
    # No single row exceeds the count cap → no row can approach the 400KB limit.
    assert all(len(s.get("samples") or []) <= SHARD_SIZE for s in shards)
    assert len(shards[0]["samples"]) == SHARD_SIZE
    assert len(shards[1]["samples"]) == 500
    # Shard 0 keeps the bare backward-compatible key.
    assert shards[0]["metric_source"] == "steps#hae_samples"
    assert shards[1]["metric_source"] == "steps#hae_samples#001"
    # No point lost across shards.
    assert len(_merged_ledger_samples(t, "steps#hae_samples")) == n


# ─── 2. Aggregate over sharded data == aggregate over the same set ───

def test_sharded_aggregate_equals_unsharded_aggregate():
    n = SHARD_SIZE + 1234  # 2 shards
    pairs = [(f"2026-08-13T{i:06d}", float(i % 100)) for i in range(n)]

    # sum_int
    h, t = _fresh_module()
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", pairs)
    got = t.latest("steps#hae")["value"]
    assert got == int(round(sum(v for _, v in pairs)))

    # avg
    h, t = _fresh_module()
    h._merge_samples_and_aggregate(t, "2026-08-13", "hrv#hae", "ms", "avg", pairs)
    got = t.latest("hrv#hae")["value"]
    assert got == round(sum(v for _, v in pairs) / n, 1)


# ─── 3. Re-sending a stored timestamp is idempotent across shards ────

def test_resend_is_idempotent_across_shard_boundary():
    h, t = _fresh_module()
    n = SHARD_SIZE + 300  # 2 shards
    first = [(f"2026-08-13T{i:06d}", float(i)) for i in range(n)]
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", first)
    agg_1 = t.latest("steps#hae")["value"]

    # Re-send a timestamp that lives in shard 1 (index > SHARD_SIZE) plus one
    # in shard 0 — same ts, same value. Must NOT double count or duplicate.
    resend = [
        (f"2026-08-13T{5:06d}", 5.0),                 # shard 0
        (f"2026-08-13T{(SHARD_SIZE + 100):06d}", float(SHARD_SIZE + 100)),  # shard 1
    ]
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", resend)

    assert len(_merged_ledger_samples(t, "steps#hae_samples")) == n, "no duplicates"
    assert t.latest("steps#hae")["value"] == agg_1, "aggregate unchanged on resend"


# ─── 4. Legacy large single-row ledger migrates forward, no loss ─────

def test_legacy_large_single_row_migrates_into_shards_without_loss():
    h, t = _fresh_module()
    # Simulate a pre-existing production row: one bare <base>_samples row
    # holding ~9,000 samples (well over one shard), keyed exactly as legacy
    # code wrote it, with a `samples` list of {ts, v}.
    legacy_n = 9000
    legacy_samples = [{"ts": f"2026-08-13T{i:06d}", "v": float(i)} for i in range(legacy_n)]
    t.put_item(Item={
        "date": "2026-08-13",
        "metric_source": "steps#hae_samples",
        "samples": legacy_samples,
    })

    # Next write adds a handful of new points.
    new_pairs = [(f"2026-08-13T{(legacy_n + i):06d}", float(legacy_n + i)) for i in range(10)]
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", new_pairs)

    merged = _merged_ledger_samples(t, "steps#hae_samples")
    assert len(merged) == legacy_n + 10, "every legacy point read + migrated, plus new ones"
    # Migrated forward into multiple shards (9010 > SHARD_SIZE).
    shards = _all_ledger_shards(t, "steps#hae_samples")
    assert len(shards) >= 2
    # Aggregate spans the full migrated set.
    assert t.latest("steps#hae")["value"] == int(round(sum(float(i) for i in range(legacy_n + 10))))


# ─── 5. _no_ts_ fallback folds in and does not collide across shards ─

def test_no_ts_fallback_folds_in_and_does_not_collide_cross_shard():
    h, t = _fresh_module()
    # Fill just over one shard with real timestamps, then send several
    # no-timestamp points. Each must get a unique synthetic key (len across
    # ALL shards), so none overwrite each other.
    base_n = SHARD_SIZE + 10
    real = [(f"2026-08-13T{i:06d}", 1.0) for i in range(base_n)]
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", real)

    no_ts = [("", 7.0), ("", 8.0), ("", 9.0)]
    h._merge_samples_and_aggregate(t, "2026-08-13", "steps#hae", "count", "sum_int", no_ts)

    merged = _merged_ledger_samples(t, "steps#hae_samples")
    # base_n real + 3 synthetic = base_n + 3 distinct entries (no collision).
    synthetic_keys = [k for k in merged if k.startswith("_no_ts_")]
    assert len(synthetic_keys) == 3, f"expected 3 unique _no_ts_ keys, got {synthetic_keys}"
    assert len(merged) == base_n + 3
    # All three no-ts values folded into the sum.
    assert t.latest("steps#hae")["value"] == base_n + 24  # base_n*1 + 7+8+9


# ─── compute reader is shard-aware (merge_samples_from_map) ──────────

def test_compute_reader_reassembles_all_shards_from_metric_map():
    """The compute sidecar reader must see the FULL day across shards, not
    just shard 0 — a partial read would be silently wrong."""
    metric_map = {
        "hr#hae_samples": {"samples": [{"ts": "t0", "bpm": 50}, {"ts": "t1", "bpm": 51}]},
        "hr#hae_samples#001": {"samples": [{"ts": "t2", "bpm": 52}]},
        "hr#hae_samples#002": {"samples": [{"ts": "t3", "bpm": 53}]},
    }
    merged = merge_samples_from_map(metric_map, "hr#hae_samples")
    assert [s["ts"] for s in merged] == ["t0", "t1", "t2", "t3"]
    assert [s["bpm"] for s in merged] == [50, 51, 52, 53]


def test_compute_reader_stops_at_first_missing_shard():
    metric_map = {
        "hrv#hae_samples": {"samples": [{"ts": "t0", "v": 40}]},
        # no #001 → chain ends; a stray #002 must NOT be picked up.
        "hrv#hae_samples#002": {"samples": [{"ts": "tX", "v": 999}]},
    }
    merged = merge_samples_from_map(metric_map, "hrv#hae_samples")
    assert [s["ts"] for s in merged] == ["t0"]
