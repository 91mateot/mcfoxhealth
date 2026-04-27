import { useState } from "react";
import { MONO, type Palette } from "../theme";
import { Panel } from "./Panel";
import { Chip } from "./Chip";
import { ProgressBar } from "./ProgressBar";
import { logWater } from "../api";

interface HydrationPanelProps {
  C: Palette;
  water: number;
  waterGoal: number;
  onOpenDetail?: () => void;
}

export function HydrationPanel({ C, water, waterGoal, onOpenDetail }: HydrationPanelProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = async (oz: number) => {
    if (busy || oz <= 0) return;
    setBusy(true);
    setError(null);
    try {
      await logWater(oz);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't log water.");
    } finally {
      setBusy(false);
    }
  };

  const promptCustom = async () => {
    const raw = window.prompt("How many oz?", "12");
    if (raw === null) return;
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) {
      setError("Enter a positive number.");
      return;
    }
    await add(n);
  };

  const pct = waterGoal > 0 ? Math.round((water / waterGoal) * 100) : 0;
  const remaining = Math.max(0, waterGoal - water);

  return (
    <Panel C={C} title="Hydration" right={<Chip C={C} color={C.cyan}>{roundOz(water)} / {waterGoal} oz</Chip>}>
      <button
        type="button"
        onClick={onOpenDetail}
        disabled={!onOpenDetail}
        style={{
          all: "unset",
          display: "block",
          width: "100%",
          cursor: onOpenDetail ? "pointer" : "default",
        }}
        aria-label={onOpenDetail ? "Show hydration breakdown" : undefined}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
          <div style={{ fontSize: 24, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>
            {roundOz(water)}
          </div>
          <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
            oz · {pct}% of daily
          </div>
          <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
            {roundOz(remaining)} oz left
          </div>
        </div>
        <ProgressBar C={C} val={water} max={waterGoal} color={C.cyan} height={6} />
      </button>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginTop: 10 }}>
        <WaterBtn C={C} label="+8 oz" onClick={() => add(8)} disabled={busy} />
        <WaterBtn C={C} label="+16 oz" onClick={() => add(16)} disabled={busy} />
        <WaterBtn C={C} label="+ custom" onClick={promptCustom} disabled={busy} />
      </div>
      {error && <div style={{ fontSize: 11, color: C.warn, fontFamily: MONO, marginTop: 6 }}>{error}</div>}
    </Panel>
  );
}

function WaterBtn({ C, label, onClick, disabled }: { C: Palette; label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: C.s,
        border: `1px solid ${C.cyan}40`,
        color: C.cyan,
        padding: "8px 6px",
        borderRadius: 10,
        fontFamily: MONO,
        fontSize: 12,
        fontWeight: 700,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        letterSpacing: ".02em",
      }}
    >
      {label}
    </button>
  );
}

function roundOz(v: number): string {
  if (!Number.isFinite(v)) return "0";
  if (Math.abs(v - Math.round(v)) < 0.05) return String(Math.round(v));
  return v.toFixed(1);
}
