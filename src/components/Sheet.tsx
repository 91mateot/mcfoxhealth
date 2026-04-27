import { useEffect, useRef, type ReactNode } from "react";
import { FONT, type Palette } from "../theme";

interface SheetProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children?: ReactNode;
  height?: string;
}

export function Sheet({ C, open, onClose, title, children, height = "70%" }: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", esc);
    panelRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", esc);
      lastFocusedRef.current?.focus?.();
    };
  }, [open, onClose]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        pointerEvents: open ? "auto" : "none",
      }}
      aria-hidden={!open}
    >
      <div
        onClick={onClose}
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(0,0,0,.55)",
          opacity: open ? 1 : 0,
          transition: "opacity .25s ease",
        }}
      />
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height,
          background: C.bg,
          borderRadius: "24px 24px 0 0",
          border: `1px solid ${C.border}`,
          borderBottom: "none",
          transform: open ? "translateY(0)" : "translateY(110%)",
          transition: "transform .3s cubic-bezier(.2,.8,.2,1)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 -20px 60px rgba(0,0,0,.6)",
          outline: "none",
          maxWidth: 520,
          margin: "0 auto",
        }}
      >
        <div style={{ padding: "10px 0 4px", display: "flex", justifyContent: "center" }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: C.s4 }} />
        </div>
        {title && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 18px 10px" }}>
            <div
              style={{
                fontSize: 15,
                fontWeight: 700,
                color: C.t,
                fontFamily: FONT,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {title}
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              style={{
                background: C.s2,
                border: "none",
                color: C.t2,
                width: 28,
                height: 28,
                borderRadius: 14,
                cursor: "pointer",
                fontSize: 14,
                fontFamily: FONT,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              ✕
            </button>
          </div>
        )}
        <div style={{ flex: 1, overflow: "auto", padding: "0 16px 24px" }}>{children}</div>
      </div>
    </div>
  );
}
