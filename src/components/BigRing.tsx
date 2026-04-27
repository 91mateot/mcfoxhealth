import { FONT, MONO, type Palette } from "../theme";
import { Ring } from "./Ring";

interface BigRingProps {
  C: Palette;
  val: number;
  max: number;
  color: string;
  label: string;
  display: string | number;
  unit?: string;
  tag: string;
  tagC: string;
  onClick?: () => void;
  pending?: boolean;
}

export function BigRing({ C, val, max, color, label, display, unit, tag, tagC, onClick, pending }: BigRingProps) {
  const tagBg = pending
    ? C.s3
    : tagC === C.primary
    ? C.primaryDim
    : tagC === C.warn
    ? C.warnDim
    : tagC === C.yellow
    ? C.yellowDim
    : C.cyanDim;
  return (
    <button
      onClick={onClick}
      aria-label={`${label}: ${display}${unit ?? ""}`}
      style={{
        background: C.s,
        borderRadius: 22,
        padding: "16px 8px 14px",
        textAlign: "center",
        border: `1px solid ${C.border}`,
        cursor: "pointer",
        fontFamily: FONT,
        color: C.t,
        transition: "transform .12s ease, background .2s ease",
      }}
      onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.97)")}
      onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
      onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
    >
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".14em", color: C.t3, fontWeight: 700, marginBottom: 12, whiteSpace: "nowrap" }}>
        {label}
      </div>
      <div style={{ position: "relative", width: 82, height: 82, margin: "0 auto 10px" }}>
        <Ring val={val} max={max} color={color} trackColor={C.s3} size={82} stroke={5.5} />
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div
            style={{
              fontSize: 26,
              fontWeight: 700,
              fontFamily: MONO,
              letterSpacing: "-.05em",
              lineHeight: 1,
              color: pending ? C.t4 : color,
            }}
          >
            {display}
          </div>
          {unit && (
            <div style={{ fontSize: 11, fontWeight: 500, color: C.t3, marginTop: 2, fontFamily: MONO }}>
              {unit}
            </div>
          )}
        </div>
      </div>
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          padding: "4px 10px",
          borderRadius: 20,
          color: pending ? C.t3 : tagC,
          background: tagBg,
          textTransform: "uppercase",
          letterSpacing: ".08em",
        }}
      >
        {tag}
      </span>
    </button>
  );
}
