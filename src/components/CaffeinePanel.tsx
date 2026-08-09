import { MONO, type Palette } from "../theme";
import { Panel } from "./Panel";
import { Chip } from "./Chip";
import { ProgressBar } from "./ProgressBar";

interface CaffeinePanelProps {
  C: Palette;
  mg: number | null;
  goal: number;
}

export function CaffeinePanel({ C, mg, goal }: CaffeinePanelProps) {
  const available = mg != null;
  const measuredMg = mg ?? 0;
  const pct = available && goal > 0 ? Math.round((measuredMg / goal) * 100) : null;
  const remaining = available ? Math.max(0, goal - measuredMg) : null;
  const over = available && measuredMg > goal;
  const color = over ? C.danger : C.warn;

  return (
    <Panel C={C} title="Caffeine" right={<Chip C={C} color={available ? color : C.t3}>{available ? `${roundMg(measuredMg)} / ${goal} mg` : "no data"}</Chip>}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
        <div style={{ fontSize: 24, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.04em" }}>
          {available ? roundMg(measuredMg) : "—"}
        </div>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
          {available ? `mg · ${pct}% of cap` : "unavailable"}
        </div>
        <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
          {remaining == null ? "" : over ? `${roundMg(measuredMg - goal)} mg over` : `${roundMg(remaining)} mg left`}
        </div>
      </div>
      <ProgressBar C={C} val={measuredMg} max={goal} color={color} height={6} />
    </Panel>
  );
}

function roundMg(v: number): string {
  if (!Number.isFinite(v)) return "0";
  return String(Math.round(v));
}
