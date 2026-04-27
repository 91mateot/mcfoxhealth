import { MONO, type Palette } from "../theme";

interface StatProps {
  C: Palette;
  label: string;
  value: string | number;
  unit?: string;
  sub?: string;
  delta?: string;
  deltaC?: string;
  bar?: number;
  barC?: string;
  valueC?: string;
}

export function Stat({ C, label, value, unit, sub, delta, deltaC, bar, barC, valueC }: StatProps) {
  return (
    <div style={{ background: C.s2, borderRadius: 14, padding: "12px 13px" }}>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
        <div
          style={{
            fontSize: 19,
            fontWeight: 700,
            fontFamily: MONO,
            letterSpacing: "-.04em",
            lineHeight: 1,
            color: valueC ?? C.t,
          }}
        >
          {value}
        </div>
        {unit && <div style={{ fontSize: 11, color: C.t3, fontWeight: 500, fontFamily: MONO }}>{unit}</div>}
      </div>
      {sub && <div style={{ fontSize: 11, color: C.t4, marginTop: 4, fontFamily: MONO, fontWeight: 500 }}>{sub}</div>}
      {delta && (
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            marginTop: 5,
            display: "inline-flex",
            alignItems: "center",
            padding: "2px 7px",
            borderRadius: 5,
            color: deltaC,
            background: (deltaC ?? "") + "18",
          }}
        >
          {delta}
        </div>
      )}
      {bar != null && (
        <div style={{ height: 3, borderRadius: 2, background: C.s4, marginTop: 7, overflow: "hidden" }}>
          <div style={{ height: "100%", borderRadius: 2, width: `${Math.min(bar, 100)}%`, background: barC, transition: "width 1s ease" }} />
        </div>
      )}
    </div>
  );
}
