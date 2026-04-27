import { useMemo, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { Meal, WaterLog } from "../types";
import { Sheet } from "../components/Sheet";
import { ProgressBar } from "../components/ProgressBar";
import { deleteWater, formatMealTime } from "../api";

interface HydrationDetailProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  date: string;
  water: number;
  waterGoal: number;
  waterLogs: WaterLog[];
  meals: Meal[];
}

// Each row is one contribution to today's hydration: either a standalone
// log_water entry (deletable) or a beverage's waterOz hydration share (linked
// to a meal).
type Row =
  | { kind: "water"; id: string; oz: number; sortKey: string; display: string }
  | { kind: "beverage"; id: string; oz: number; sortKey: string; display: string; mealName: string };

export function HydrationDetail({ C, open, onClose, date, water, waterGoal, waterLogs, meals }: HydrationDetailProps) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Map logs to displayable rows. Plain-water rows have no time in the DB
  // (only a loggedAt UTC timestamp), so we show the local-time HH:MM derived
  // from loggedAt. Beverage rows use the meal's own `time` field.
  const rows: Row[] = useMemo(() => {
    const mealById = new Map(meals.map((m) => [String(m.id), m]));
    const out: Row[] = [];

    for (const w of waterLogs ?? []) {
      // If this water row was auto-created by a beverage meal, attribute it to
      // the meal so we don't double-count with the meal.waterOz pass below.
      if (w.sourceMealId && mealById.has(w.sourceMealId)) {
        const m = mealById.get(w.sourceMealId)!;
        out.push({
          kind: "beverage",
          id: String(w.id),
          oz: Number(w.oz) || 0,
          sortKey: m.time || loggedAtToHM(w.loggedAt) || "",
          display: m.time ? formatMealTime(m.time) : loggedAtToDisplay(w.loggedAt),
          mealName: m.name || "Beverage",
        });
      } else {
        out.push({
          kind: "water",
          id: String(w.id),
          oz: Number(w.oz) || 0,
          sortKey: loggedAtToHM(w.loggedAt) || "",
          display: loggedAtToDisplay(w.loggedAt),
        });
      }
    }

    out.sort((a, b) => (a.sortKey < b.sortKey ? -1 : a.sortKey > b.sortKey ? 1 : 0));
    return out;
  }, [waterLogs, meals]);

  const totalShown = rows.reduce((s, r) => s + r.oz, 0);
  const pct = waterGoal > 0 ? Math.round((water / waterGoal) * 100) : 0;
  const remaining = Math.max(0, waterGoal - water);

  const onDelete = async (id: string) => {
    if (busyId) return;
    setBusyId(id);
    setError(null);
    try {
      await deleteWater(date, id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Hydration" height="72%">
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
        <div style={{ fontSize: 32, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>
          {roundOz(water)}
        </div>
        <div style={{ fontSize: 12, color: C.t3, fontFamily: MONO }}>
          / {waterGoal} oz · {pct}%
        </div>
        <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
          {roundOz(remaining)} oz left
        </div>
      </div>
      <ProgressBar C={C} val={water} max={waterGoal} color={C.cyan} height={6} />

      <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 14, marginBottom: 6, letterSpacing: ".05em" }}>
        CONTRIBUTIONS ({rows.length})
      </div>

      {rows.length === 0 && (
        <div style={{ fontSize: 12, color: C.t3, padding: "14px 2px" }}>
          Nothing logged yet today.
        </div>
      )}

      {rows.map((r) => (
        <div
          key={r.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 10px",
            borderBottom: `1px solid ${C.border}`,
          }}
        >
          <div style={{ width: 56, fontSize: 11, color: C.t3, fontFamily: MONO, fontWeight: 600 }}>
            {r.display}
          </div>
          <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: C.t, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {r.kind === "water" ? "Water" : r.mealName}
            {r.kind === "beverage" && (
              <span style={{ fontSize: 10, color: C.t4, marginLeft: 6, fontFamily: MONO }}>from meal</span>
            )}
          </div>
          <div style={{ fontSize: 12.5, fontFamily: MONO, fontWeight: 700, color: C.cyan, minWidth: 48, textAlign: "right" }}>
            {roundOz(r.oz)} oz
          </div>
          {r.kind === "water" && (
            <button
              onClick={() => onDelete(r.id)}
              disabled={busyId === r.id}
              aria-label="Delete water entry"
              style={{
                background: "transparent",
                border: `1px solid ${C.border}`,
                color: C.t3,
                width: 24,
                height: 24,
                borderRadius: 12,
                cursor: busyId === r.id ? "wait" : "pointer",
                fontSize: 11,
                fontFamily: FONT,
                fontWeight: 700,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                opacity: busyId === r.id ? 0.5 : 1,
              }}
            >
              ✕
            </button>
          )}
        </div>
      ))}

      {Math.abs(totalShown - water) > 0.5 && (
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginTop: 10 }}>
          Note: contributions total {roundOz(totalShown)} oz. Discrepancy vs {roundOz(water)} oz panel total is usually a beverage whose companion water row is missing its source link.
        </div>
      )}

      {error && <div style={{ fontSize: 11, color: C.warn, fontFamily: MONO, marginTop: 10 }}>{error}</div>}
    </Sheet>
  );
}

function roundOz(v: number): string {
  if (!Number.isFinite(v)) return "0";
  if (Math.abs(v - Math.round(v)) < 0.05) return String(Math.round(v));
  return v.toFixed(1);
}

function loggedAtToHM(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

function loggedAtToDisplay(iso?: string): string {
  const hm = loggedAtToHM(iso);
  return hm ? formatMealTime(hm) : "—";
}
