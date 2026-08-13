"""Shard-aware per-day samples ledger for HAE metrics.

Background
----------
HealthAutoExport (HAE) fires multiple automations per day, each carrying only
the samples from its own export window. A bare per-POST overwrite meant
"last webhook wins" and silently discarded earlier same-day data — the root
cause of the steps-undercount and HRV-discrepancy bugs. The fix (PR #2) was a
per-day, timestamp-deduped samples ledger stored in a sidecar row
``<metric_source>_samples`` with the daily aggregate recomputed over the FULL
merged set.

That ledger had NO cap and NO chunking. A single high-frequency metric's daily
ledger (e.g. ``steps#hae_samples`` at ~9,226 samples, ``stand_min#hae_samples``
at ~8,700) outgrew DynamoDB's hard 400KB per-item limit, so ``PutItem`` raised
``ValidationException`` and aborted the WHOLE ingest request — every metric in
that POST wrote nothing. Silent data loss.

Design
------
Shard the per-day ledger across multiple sidecar rows with a deterministic,
idempotent key scheme:

  - shard 0  -> ``<base_key>``            (unchanged; backward-compatible with
                                            every row already in the table)
  - shard 1  -> ``<base_key>#001``
  - shard 2  -> ``<base_key>#002``
  - ...

Each shard holds at most ``SHARD_SIZE`` samples. The cap is by SAMPLE COUNT,
not guessed bytes: with a conservative 2,000-sample cap, even long ISO-8601
timestamp strings (~40 bytes/sample incl. keys) keep a shard around ~80KB —
5x under the 400KB limit — so no shard can approach the ceiling.

Invariants
----------
- Sample counts for a given (date, metric) only GROW within a day (dedup by
  timestamp only ever adds keys), so the shard count is monotonic and no
  "orphan" trailing shards with stale data can appear. Readers therefore stop
  at the first missing shard.
- Backward compatibility: a legacy single ``<base_key>`` row (shard 0) with a
  large ``samples`` list is read in full, merged, and re-sharded forward on the
  next write without dropping points.
- Dedup by timestamp is enforced across ALL shards on read, so a re-sent point
  is idempotent regardless of which shard it originally landed in.
"""

from typing import Callable, Optional

# Conservative max samples per shard. Chosen by COUNT, not byte estimate:
# 2,000 * ~40 bytes/sample (ts string + numeric value + list overhead) ~= 80KB,
# comfortably under DynamoDB's 400KB per-item hard limit even for the longest
# timestamp strings HAE emits. See module docstring.
SHARD_SIZE = 2000

# Cap on the number of shards we will scan/write for a single (date, metric).
# 200 shards * 2,000 = 400,000 samples/day — far beyond any real HAE volume
# (worst observed ~9,226). Acts as a runaway guard so a corrupt read loop can
# never scan unbounded rows.
MAX_SHARDS = 200


def shard_key(base_key: str, index: int) -> str:
    """Deterministic sidecar row key for shard ``index`` of ``base_key``.

    Shard 0 is the bare ``base_key`` (backward-compatible with every legacy
    row already in the table). Shards >= 1 are ``<base_key>#NNN`` zero-padded
    to 3 digits.
    """
    if index < 0:
        raise ValueError(f"shard index must be >= 0, got {index}")
    if index == 0:
        return base_key
    return f"{base_key}#{index:03d}"


def read_merged_samples(
    get_item_fn: Callable,
    table,
    date_str: str,
    base_key: str,
) -> tuple[dict, dict]:
    """Read and merge every shard of a per-day ledger.

    Reads shard 0 (``base_key``), then ``#001``, ``#002``, ... until a shard is
    missing, merging their ``samples`` lists into a single timestamp-keyed dict
    (later shards win on collision, but within one write the same ts never
    lands in two shards). Also returns the first shard's item so callers can
    recover stored temporal metadata.

    Returns ``(merged_samples, shard0_item)`` where ``merged_samples`` maps
    ``ts -> value`` preserving insertion order, and ``shard0_item`` is the raw
    shard-0 row (or ``{}`` if none exists).
    """
    merged: dict = {}
    shard0_item: dict = {}
    for index in range(MAX_SHARDS):
        item = get_item_fn(table, {"date": date_str, "metric_source": shard_key(base_key, index)}) or {}
        if not item:
            # First missing shard ends the chain (counts are monotonic, so
            # there are no gaps). If shard 0 itself is missing, there's no
            # ledger yet — return empty.
            break
        if index == 0:
            shard0_item = item
        for s in item.get("samples") or []:
            ts = s.get("ts")
            if ts:
                merged[ts] = s.get("v")
    return merged, shard0_item


def merge_samples_from_map(metric_map: dict, base_key: str) -> list[dict]:
    """Concatenate the ``samples`` of every shard present in a ``metric_map``.

    ``metric_map`` is the ``{metric_source: item}`` dict compute builds from a
    single ``query_items(date)`` call — it already contains every row for the
    day, so reassembling shards costs no extra DynamoDB reads. Preserves each
    sample dict verbatim (works for both the generic ``{ts, v}`` ledger shape
    and the HR sidecar's ``{ts, bpm}`` shape).

    Returns a flat list of sample dicts across shards 0..N, in shard order.
    """
    out: list[dict] = []
    for index in range(MAX_SHARDS):
        item = metric_map.get(shard_key(base_key, index))
        if not item:
            break
        out.extend(item.get("samples") or [])
    return out


def write_sharded_ledger(
    put_item_fn: Callable,
    table,
    date_str: str,
    base_key: str,
    merged_samples: dict,
    *,
    extra: Optional[dict] = None,
    ingested_at: Optional[str] = None,
) -> int:
    """Write ``merged_samples`` across as many shard rows as needed.

    ``merged_samples`` is an ordered ``ts -> value`` dict (as produced by
    :func:`read_merged_samples` after folding in new points). It is chunked
    into ``SHARD_SIZE``-sample rows written to ``shard_key(base_key, 0..N)``.
    Shard 0 keeps the bare ``base_key`` so the row layout stays backward
    compatible with every reader and every legacy row.

    ``extra`` (e.g. stored temporal metadata) is merged onto EVERY shard so
    per-shard metadata behavior matches the pre-sharding single-row behavior.

    Returns the number of shard rows written (always >= 1).
    """
    items = [{"ts": ts, "v": v} for ts, v in merged_samples.items()]
    # Deterministic chunking: shard i holds items[i*SHARD_SIZE:(i+1)*SHARD_SIZE].
    chunks = [items[i : i + SHARD_SIZE] for i in range(0, len(items), SHARD_SIZE)] or [[]]
    if len(chunks) > MAX_SHARDS:
        raise ValueError(
            f"{base_key} on {date_str} needs {len(chunks)} shards, exceeds MAX_SHARDS={MAX_SHARDS}"
        )
    for index, chunk in enumerate(chunks):
        item = {
            "date": date_str,
            "metric_source": shard_key(base_key, index),
            "samples": chunk,
        }
        if ingested_at is not None:
            item["ingested_at"] = ingested_at
        if extra:
            item.update(extra)
        put_item_fn(table, item)
    return len(chunks)
