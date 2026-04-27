import { MONO, type Palette } from "../theme";
import { Panel } from "./Panel";
import { Chip } from "./Chip";
import { ProgressBar } from "./ProgressBar";

interface CaffeinePanelProps {
  C: Palette;
  mg: number;
  goal: number;
}

export function CaffeinePanel({ C, mg, goal }: CaffeinePanelProps) {
  const pct = goal > 0 ? Math.round((mg / goal) * 100) : 0;
  const remaining = Math.max(0, goal - mg);
  const over = mg > goal;
  const color = over ? C.danger : C.warn;

  return (
    <Panel C={C} title="Caffeine" right={<Chip C={C} color={color}>{roundMg(mg)} / {goal} mg</Chip>}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
        <div style={{ fontSize: 24, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.04em" }}>
          {roundMg(mg)}
        </div>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
          mg · {pct}% of cap
        </div>
        <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
          {over ? `${roundMg(mg - goal)} mg over` : `${roundMg(remaining)} mg left`}
        </div>
      </div>
      <ProgressBar C={C} val={mg} max={goal} color={color} height={6} />
    </Panel>
  );
}

function roundMg(v: number): string {
  if (!Number.isFinite(v)) return "0";
  return String(Math.round(v));
}
