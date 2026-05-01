import { MONO, type Palette } from "../theme";

export interface Scale5Props {
  C: Palette;
  label: string;
  val: number | null;
  set: (n: number) => void;
  good: "high" | "low";
}

export function Scale5({ C, label, val, set, good }: Scale5Props) {
  return (
    <div style={{ background: C.s2, borderRadius: 12, padding: "10px 10px" }}>
      <div
        style={{
          fontSize: 11,
          color: C.t3,
          textTransform: "uppercase",
          letterSpacing: ".1em",
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ display: "flex", gap: 3, justifyContent: "space-between" }}>
        {[1, 2, 3, 4, 5].map((n) => {
          const active = val === n;
          const isGood = good === "high" ? n >= 4 : n <= 2;
          const isBad = good === "high" ? n <= 2 : n >= 4;
          const col = active ? (isGood ? C.primary : isBad ? C.warn : C.yellow) : C.s4;
          return (
            <button
              key={n}
              onClick={() => set(n)}
              aria-pressed={active}
              style={{
                flex: 1,
                height: 26,
                border: "none",
                borderRadius: 6,
                background: col,
                color: active ? C.bg : C.t3,
                fontSize: 11,
                fontWeight: 800,
                fontFamily: MONO,
                cursor: "pointer",
                transition: "all .15s ease",
              }}
            >
              {n}
            </button>
          );
        })}
      </div>
    </div>
  );
}
