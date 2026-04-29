import { MONO, type Palette } from "../theme";

interface WeightChartProps {
  C: Palette;
  /** Chronological weights — data[0] is oldest, data[last] is most recent. */
  data: number[];
  color: string;
  /** Height of the SVG plot area in px. Y labels and date strip render outside this. */
  h?: number;
}

function formatMonthDay(d: Date): string {
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Weight chart with axes the user can actually read:
 *   - Min / max Y labels pinned to the plot
 *   - Start / end date strip (derived from array length, anchored to today)
 *   - Dot on the latest reading
 *
 * Intentionally not a generic chart — weight is the one place on this screen
 * where the absolute numbers matter. Sparklines elsewhere stay decorative.
 */
export function WeightChart({ C, data, color, h = 72 }: WeightChartProps) {
  if (!data || data.length === 0) {
    return <div style={{ height: h, color: C.t4, fontSize: 11, fontFamily: MONO }}>No weight history.</div>;
  }

  const w = 300; // viewBox width; preserveAspectRatio scales to container
  const padX = 4;
  const plotW = w - padX * 2;

  const min = Math.min(...data);
  const max = Math.max(...data);
  // Pad the Y range so a near-flat trace doesn't hug the edges.
  const pad = Math.max(0.6, (max - min) * 0.2);
  const yMin = min - pad;
  const yMax = max + pad;
  const range = yMax - yMin || 1;

  const stepX = plotW / Math.max(1, data.length - 1);
  const pts = data.map((v, i) => [padX + i * stepX, h - ((v - yMin) / range) * h] as const);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = line + ` L${w - padX},${h} L${padX},${h} Z`;

  const lastPt = pts[pts.length - 1];
  const last = data[data.length - 1];
  const first = data[0];
  const delta = last - first;

  // Dates: the array is daily, with today at the end.
  const today = new Date();
  const startDate = new Date(today);
  startDate.setDate(today.getDate() - (data.length - 1));

  const deltaColor = delta < 0 ? C.primary : delta > 0 ? C.warn : C.t3;
  const deltaSign = delta > 0 ? "+" : "";

  return (
    <div style={{ position: "relative" }}>
      {/* Plot + Y-axis labels stacked */}
      <div style={{ display: "flex", alignItems: "stretch", gap: 6 }}>
        <div style={{ width: 36, display: "flex", flexDirection: "column", justifyContent: "space-between", paddingTop: 2, paddingBottom: 2, fontSize: 10, color: C.t4, fontFamily: MONO, textAlign: "right" }}>
          <div>{max.toFixed(1)}</div>
          <div>{min.toFixed(1)}</div>
        </div>
        <div style={{ flex: 1, position: "relative" }}>
          <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }} preserveAspectRatio="none" aria-hidden>
            <path d={area} fill={color} fillOpacity="0.12" />
            <path d={line} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx={lastPt[0]} cy={lastPt[1]} r="3.2" fill={color} stroke={C.bg} strokeWidth="1.5" />
          </svg>
        </div>
      </div>

      {/* X-axis date strip + delta */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6, paddingLeft: 42, fontSize: 10, color: C.t4, fontFamily: MONO }}>
        <span>{formatMonthDay(startDate)}</span>
        <span style={{ color: deltaColor, fontWeight: 700 }}>
          {deltaSign}{delta.toFixed(1)} lbs · {data.length}d
        </span>
        <span>{formatMonthDay(today)}</span>
      </div>
    </div>
  );
}
