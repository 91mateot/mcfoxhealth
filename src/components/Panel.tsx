import type { CSSProperties, ReactNode } from "react";
import type { Palette } from "../theme";

interface PanelProps {
  C: Palette;
  title?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
  onClick?: () => void;
  style?: CSSProperties;
}

export function Panel({ C, title, right, children, onClick, style }: PanelProps) {
  return (
    <div
      onClick={onClick}
      style={{
        background: C.s,
        borderRadius: 20,
        padding: 16,
        marginBottom: 10,
        border: `1px solid ${C.border}`,
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    >
      {title && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, gap: 8 }}>
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: C.t2,
              letterSpacing: ".01em",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              minWidth: 0,
              flex: 1,
            }}
          >
            {title}
          </span>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}
