import type { CSSProperties, ReactNode } from "react";
import { FONT, type Palette } from "../theme";

interface BtnProps {
  C: Palette;
  children: ReactNode;
  onClick?: () => void;
  primary?: boolean;
  small?: boolean;
  full?: boolean;
  style?: CSSProperties;
  disabled?: boolean;
}

export function Btn({ C, children, onClick, primary, small, full, style, disabled }: BtnProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: primary ? C.primary : C.s2,
        color: primary ? "#0a0a0a" : C.t,
        border: primary ? "none" : `1px solid ${C.s3}`,
        padding: small ? "8px 12px" : "12px 16px",
        borderRadius: small ? 10 : 14,
        fontFamily: FONT,
        fontSize: small ? 12 : 13,
        fontWeight: 700,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        width: full ? "100%" : "auto",
        letterSpacing: ".01em",
        whiteSpace: "nowrap",
        transition: "transform .1s ease, opacity .15s ease",
        ...style,
      }}
      onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.97)")}
      onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
      onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
    >
      {children}
    </button>
  );
}
