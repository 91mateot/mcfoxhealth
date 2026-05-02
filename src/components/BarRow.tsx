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
}: BarRowProps<T>) {
  const max = Math.max(...items.map((i) => Number(i[accessor]) || 0)) || 1;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height }}>
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
                opacity: v ? 1 : 0.25,
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
