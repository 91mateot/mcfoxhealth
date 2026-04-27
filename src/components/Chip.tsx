import type { ReactNode } from "react";
import { MONO, type Palette } from "../theme";

interface ChipProps {
  C: Palette;
  children: ReactNode;
  color?: string;
}

export function Chip({ C, children, color }: ChipProps) {
  return (
    <span
      style={{
        fontSize: 11,
        color: color ?? C.t4,
        fontFamily: MONO,
        fontWeight: 600,
        background: C.s2,
        padding: "3px 8px",
        borderRadius: 8,
        letterSpacing: ".02em",
        border: `1px solid ${C.border}`,
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {children}
    </span>
  );
}
