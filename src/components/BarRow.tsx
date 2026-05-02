import { MONO, type Palette } from "../theme";

interface BarItem {
  [key: string]: any;
  today?: boolean;
}

interface BarRowProps<T extends BarItem> {
  C: Palette;
  items: T[];
  accessor?: keyof T;
  height?: number;
  colorFn?: (item: T, v: number) => string;
  labelFn?: (item: T) => string;
  valueFn?: (item: T) => string;
  todayKey?: keyof T;
  /** If provided, draws a dashed horizontal reference line at this value
   *  across the bar area. Sits inside the max-normalized chart space. */
  goalValue?: number;
  /** Opacity to apply to bars whose value is below `goalValue`. Ignored
   *  when `goalValue` is undefined. Default 1 (no dimming). */
  belowGoalOpacity?: number;
}

export function BarRow<T extends BarItem>({
  C,
  items,
  accessor = "v" as keyof T,
  height = 52,
  colorFn,
  labelFn,
  valueFn,
  todayKey = "today" as keyof T,
  goalValue,
  belowGoalOpacity = 1,
}: BarRowProps<T>) {
  const max = Math.max(...items.map((i) => Number(i[accessor]) || 0), goalValue ?? 0) || 1;
  // Bars occupy the top 82% of the chart area (matches the height calc
  // below). Translate `goalValue` into the same space so the reference
  // line aligns with bar tops that represent that value.
  const barArea = height * 0.82;
  const goalPx = goalValue != null ? barArea - (goalValue / max) * barArea : null;
  return (
    <div style={{ position: "relative", display: "flex", alignItems: "flex-end", gap: 5, height }}>
      {goalPx != null && (
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: goalPx,
            height: 0,
            borderTop: `1px dashed ${C.t4}`,
            opacity: 0.55,
            pointerEvents: "none",
          }}
        />
      )}
      {items.map((it, i) => {
        const v = Number(it[accessor]) || 0;
        const h = Math.max(4, (v / max) * height * 0.82);
        const col = colorFn ? colorFn(it, v) : C.primary;
        const isToday = Boolean(it[todayKey]);
        return (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
            {valueFn && (
              <div
                style={{
                  // Label color tracks bar color so short days ("4k" in warn)
                  // stay readable against the dark panel. Today pops slightly
                  // brighter to keep the "this is today" signal.
                  fontSize: 11,
                  color: col,
                  opacity: isToday ? 1 : 0.75,
                  fontFamily: MONO,
                  fontWeight: isToday ? 700 : 600,
                }}
              >
                {valueFn(it)}
              </div>
            )}
            <div
              style={{
                width: "100%",
                borderRadius: "4px 4px 2px 2px",
                height: h,
                background: col,
                opacity: v
                  ? goalValue != null && v < goalValue
                    ? belowGoalOpacity
                    : 1
                  : 0.25,
                boxShadow: isToday ? `0 0 0 1.5px ${C.t}` : "none",
                transition: "height 1s ease",
              }}
            />
            <span style={{ fontSize: 11, color: isToday ? C.t2 : C.t4, fontFamily: MONO, fontWeight: 700 }}>
              {labelFn ? labelFn(it) : (it.d as string)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
