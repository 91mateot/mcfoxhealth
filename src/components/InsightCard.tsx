import { MONO, type Palette } from "../theme";
import type { NumericCorrelation } from "../types";

interface InsightCardProps {
  C: Palette;
  c: NumericCorrelation;
  onClick?: () => void;
}

/** Natural-language card for a single numeric correlation. The server-rendered
 * `insight` sentence does the heavy lifting; this component wraps it with a
 * confidence chip and a tap target that opens the detail drawer.
 *
 * The accent color signals whether the correlation matches "better" — e.g.
 * caffeine→deep_sleep has better="down", so a negative slope is expected and
 * drawn in the palette's primary color. */
export function InsightCard({ C, c, onClick }: InsightCardProps) {
  const noSignal = c.confidence === "none";
  const expected = c.better === "up" ? c.r > 0 : c.r < 0;
  const col = noSignal ? C.t4 : expected ? C.primary : C.warn;
  const confCol = c.confidence === "high" ? C.primary : c.confidence === "medium" ? C.yellow : C.t4;

  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (!onClick) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      style={{
        background: C.s,
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${col}`,
        borderRadius: 16,
        padding: "14px 14px",
        marginBottom: 8,
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <div style={{ fontSize: 14, color: C.t, fontWeight: 600, lineHeight: 1.45, letterSpacing: "-.005em" }}>
        {c.insight}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
        <div
          style={{
            fontSize: 10,
            color: confCol,
            fontFamily: MONO,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: ".08em",
          }}
        >
          {c.confidence}
        </div>
        <div style={{ width: 3, height: 3, borderRadius: 2, background: C.t4 }} />
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO }}>n={c.n}</div>
        <div style={{ width: 3, height: 3, borderRadius: 2, background: C.t4 }} />
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO }}>{c.windowDays}d window</div>
      </div>
    </div>
  );
}
