import type { ReactNode } from "react";
import type { Palette } from "../theme";

interface SectionHeadProps {
  C: Palette;
  kicker?: string;
  title: string;
  right?: ReactNode;
}

export function SectionHead({ C, kicker, title, right }: SectionHeadProps) {
  return (
    <div style={{ padding: "18px 4px 10px", display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 8 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        {kicker && (
          <div
            style={{
              fontSize: 11,
              textTransform: "uppercase",
              letterSpacing: ".18em",
              color: C.t4,
              fontWeight: 700,
              marginBottom: 2,
              whiteSpace: "nowrap",
            }}
          >
            {kicker}
          </div>
        )}
        <div style={{ fontSize: 16, fontWeight: 700, color: C.t, letterSpacing: "-.01em", whiteSpace: "nowrap" }}>
          {title}
        </div>
      </div>
      <div style={{ flexShrink: 0 }}>{right}</div>
    </div>
  );
}
