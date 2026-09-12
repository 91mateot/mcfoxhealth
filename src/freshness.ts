interface FreshnessState {
  updatedAt: string | null | undefined;
  checkedAt: number | null;
  now: number;
  refreshing?: boolean;
  refreshFailed?: boolean;
}

function formatAge(timestamp: number, now: number): string {
  const minutes = Math.floor(Math.max(0, now - timestamp) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** A completed request and the latest source observation have separate clocks. */
export function formatFreshness({
  updatedAt, checkedAt, now, refreshing, refreshFailed,
}: FreshnessState): string {
  if (refreshing) return "refreshing app data…";
  if (refreshFailed) return "refresh failed · retry";

  const sourceTime = updatedAt ? Date.parse(updatedAt) : NaN;
  const sourceAge = Number.isFinite(sourceTime) ? formatAge(sourceTime, now) : null;
  if (checkedAt == null) return sourceAge ? `updated ${sourceAge}` : "no data yet";
  return `checked ${formatAge(checkedAt, now)} · ${sourceAge ? `data ${sourceAge}` : "no data yet"}`;
}
