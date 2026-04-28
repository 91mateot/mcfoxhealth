import { FONT, type Palette } from "../theme";

export interface Tab {
  id: string;
  label: string;
  activeColor?: string;
}

interface TabBarProps {
  C: Palette;
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  onFabClick: () => void;
}

export function TabBar({ C, tabs, active, onChange, onFabClick }: TabBarProps) {
  // Split the 4 tabs around the center FAB: first half left of FAB, second half right.
  const mid = Math.floor(tabs.length / 2);
  const leftTabs = tabs.slice(0, mid);
  const rightTabs = tabs.slice(mid);

  return (
    <nav
      aria-label="Main sections"
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 40,
        padding: "8px 12px calc(26px + env(safe-area-inset-bottom, 0px))",
        background: `linear-gradient(180deg, ${C.bg}00 0%, ${C.bg} 35%)`,
        fontFamily: FONT,
      }}
    >
      <div
        style={{
          position: "relative",
          display: "flex",
          alignItems: "center",
          background: C.s,
          borderRadius: 22,
          padding: 5,
          border: `1px solid ${C.border}`,
          boxShadow: "0 12px 32px rgba(0,0,0,.4)",
          maxWidth: 420,
          margin: "0 auto",
        }}
      >
        {leftTabs.map((t) => (
          <TabButton key={t.id} C={C} tab={t} active={active === t.id} onClick={() => onChange(t.id)} />
        ))}

        {/* Center FAB spacer — the FAB is absolutely positioned so it sits above the bar. */}
        <div style={{ flex: 1, minWidth: 56 }} aria-hidden="true" />

        {rightTabs.map((t) => (
          <TabButton key={t.id} C={C} tab={t} active={active === t.id} onClick={() => onChange(t.id)} />
        ))}

        <button
          onClick={onFabClick}
          aria-label="Ask coach"
          style={{
            position: "absolute",
            left: "50%",
            top: -18,
            transform: "translateX(-50%)",
            width: 56,
            height: 56,
            borderRadius: 28,
            border: `1px solid ${C.border}`,
            background: C.primary,
            color: "#0a0a0a",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            boxShadow: "0 10px 24px rgba(0,0,0,.45)",
            padding: 0,
          }}
        >
          <ChatGlyph color="#0a0a0a" />
        </button>
      </div>
    </nav>
  );
}

function TabButton({ C, tab, active, onClick }: { C: Palette; tab: Tab; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      style={{
        flex: 1,
        background: active ? C.s3 : "transparent",
        border: "none",
        color: active ? C.t : C.t3,
        padding: "9px 6px",
        borderRadius: 18,
        fontFamily: FONT,
        fontSize: 11,
        fontWeight: 700,
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 3,
        transition: "all .2s ease",
        letterSpacing: ".01em",
      }}
    >
      <TabIcon id={tab.id} color={active ? tab.activeColor ?? C.primary : C.t3} />
      {tab.label}
    </button>
  );
}

function TabIcon({ id, color }: { id: string; color: string }) {
  const s = 18;
  const p = {
    width: s,
    height: s,
    stroke: color,
    strokeWidth: 2,
    fill: "none",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (id === "today")
    return (
      <svg viewBox="0 0 24 24" {...p}>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="4.5" />
        <circle cx="12" cy="12" r="1.5" fill={color} />
      </svg>
    );
  if (id === "train")
    return (
      <svg viewBox="0 0 24 24" {...p}>
        <path d="M4 9v6M8 7v10M12 5v14M16 7v10M20 9v6" />
      </svg>
    );
  if (id === "fuel")
    return (
      <svg viewBox="0 0 24 24" {...p}>
        <path d="M6 3h12l-1 10a6 6 0 01-10 0L6 3z" />
        <path d="M9 3v4M15 3v4" />
      </svg>
    );
  if (id === "progress")
    return (
      <svg viewBox="0 0 24 24" {...p}>
        <path d="M3 17l5-5 4 4 8-9" />
        <path d="M15 7h5v5" />
      </svg>
    );
  return null;
}

function ChatGlyph({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 24 24" width={24} height={24} fill="none" stroke={color} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6a2 2 0 012-2h12a2 2 0 012 2v9a2 2 0 01-2 2H9l-4 4v-4H6a2 2 0 01-2-2V6z" />
    </svg>
  );
}
