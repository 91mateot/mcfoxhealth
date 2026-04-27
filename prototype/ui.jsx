// Shared UI primitives — rings, cards, charts, bars
const { useState, useEffect, useRef, useMemo } = React;

// ─── RING ───────────────────────────────────────────────────────
function Ring({ val, max, color, trackColor, size = 88, stroke = 5, animate = true }) {
  const r = (50 - stroke / 2 - 1);
  const ci = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, val / max));
  const off = ci - pct * ci;
  return (
    <svg viewBox="0 0 100 100" style={{ width: size, height: size, transform: "rotate(-90deg)" }}>
      <circle cx="50" cy="50" r={r} stroke={trackColor} strokeWidth={stroke} fill="none" />
      <circle cx="50" cy="50" r={r} stroke={color} strokeWidth={stroke} fill="none"
        strokeLinecap="round" strokeDasharray={ci} strokeDashoffset={off}
        style={{ transition: animate ? "stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)" : "none" }} />
    </svg>
  );
}

// ─── BIG RING (hero) ────────────────────────────────────────────
function BigRing({ C, val, max, color, label, display, unit, tag, tagC, onClick, pending }) {
  const tagBg = pending ? C.s3 : (tagC === C.primary ? C.primaryDim : tagC === C.warn ? C.warnDim : tagC === C.yellow ? C.yellowDim : C.cyanDim);
  return (
    <button onClick={onClick} style={{
      background: C.s, borderRadius: 22, padding: "16px 8px 14px", textAlign: "center",
      border: `1px solid ${C.border}`, cursor: "pointer", fontFamily: FONT, color: C.t,
      transition: "transform .12s ease, background .2s ease",
    }}
    onMouseDown={e => e.currentTarget.style.transform = "scale(0.97)"}
    onMouseUp={e => e.currentTarget.style.transform = "scale(1)"}
    onMouseLeave={e => e.currentTarget.style.transform = "scale(1)"}
    >
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".14em", color: C.t3, fontWeight: 700, marginBottom: 12, whiteSpace: "nowrap" }}>{label}</div>
      <div style={{ position: "relative", width: 82, height: 82, margin: "0 auto 10px" }}>
        <Ring val={val} max={max} color={color} trackColor={C.s3} size={82} stroke={5.5} />
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: MONO, letterSpacing: "-.05em", lineHeight: 1, color: pending ? C.t4 : color }}>{display}</div>
          {unit && <div style={{ fontSize: 9, fontWeight: 500, color: C.t3, marginTop: 2, fontFamily: MONO }}>{unit}</div>}
        </div>
      </div>
      <span style={{ fontSize: 9.5, fontWeight: 700, padding: "4px 10px", borderRadius: 20, color: pending ? C.t3 : tagC, background: tagBg, textTransform: "uppercase", letterSpacing: ".08em" }}>{tag}</span>
    </button>
  );
}

// ─── STAT CARD ──────────────────────────────────────────────────
function Stat({ C, label, value, unit, sub, delta, deltaC, bar, barC, valueC }) {
  return (
    <div style={{ background: C.s2, borderRadius: 14, padding: "12px 13px" }}>
      <div style={{ fontSize: 9, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
        <div style={{ fontSize: 19, fontWeight: 700, fontFamily: MONO, letterSpacing: "-.04em", lineHeight: 1, color: valueC || C.t }}>{value}</div>
        {unit && <div style={{ fontSize: 10, color: C.t3, fontWeight: 500, fontFamily: MONO }}>{unit}</div>}
      </div>
      {sub && <div style={{ fontSize: 9.5, color: C.t4, marginTop: 4, fontFamily: MONO, fontWeight: 500 }}>{sub}</div>}
      {delta && (
        <div style={{ fontSize: 9, fontWeight: 700, marginTop: 5, display: "inline-flex", alignItems: "center", padding: "2px 7px", borderRadius: 5,
          color: deltaC, background: deltaC + "18" }}>{delta}</div>
      )}
      {bar != null && (
        <div style={{ height: 3, borderRadius: 2, background: C.s4, marginTop: 7, overflow: "hidden" }}>
          <div style={{ height: "100%", borderRadius: 2, width: `${Math.min(bar, 100)}%`, background: barC, transition: "width 1s ease" }} />
        </div>
      )}
    </div>
  );
}

// ─── PANEL ──────────────────────────────────────────────────────
function Panel({ C, title, right, children, onClick, style }) {
  return (
    <div onClick={onClick} style={{
      background: C.s, borderRadius: 20, padding: 16, marginBottom: 10,
      border: `1px solid ${C.border}`, cursor: onClick ? "pointer" : "default", ...style,
    }}>
      {title && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: C.t2, letterSpacing: ".01em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0, flex: 1 }}>{title}</span>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

function Chip({ C, children, color }) {
  return (
    <span style={{
      fontSize: 9, color: color || C.t4, fontFamily: MONO, fontWeight: 600,
      background: C.s2, padding: "3px 8px", borderRadius: 8, letterSpacing: ".02em",
      border: `1px solid ${C.border}`, whiteSpace: "nowrap", flexShrink: 0,
    }}>{children}</span>
  );
}

// ─── SPARKLINE ──────────────────────────────────────────────────
function Sparkline({ data, color, w = 280, h = 44, fill = true, baseline }) {
  const min = Math.min(...data) - 2;
  const max = Math.max(...data) + 2;
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, h - ((v - min) / range) * h]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const dFill = d + ` L${w},${h} L0,${h} Z`;
  const baseY = baseline != null ? h - ((baseline - min) / range) * h : null;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }} preserveAspectRatio="none">
      {baseY != null && (
        <line x1="0" x2={w} y1={baseY} y2={baseY} stroke={color} strokeOpacity="0.25" strokeWidth="1" strokeDasharray="3 3" />
      )}
      {fill && <path d={dFill} fill={color} fillOpacity="0.12" />}
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── BARS ───────────────────────────────────────────────────────
function BarRow({ C, items, accessor = "v", height = 52, colorFn, labelFn, valueFn, todayKey = "today" }) {
  const max = Math.max(...items.map(i => i[accessor] || 0)) || 1;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height }}>
      {items.map((it, i) => {
        const v = it[accessor] || 0;
        const h = Math.max(4, (v / max) * height * 0.82);
        const col = colorFn ? colorFn(it, v) : C.primary;
        return (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
            {valueFn && <div style={{ fontSize: 8, color: it[todayKey] ? col : C.t4, fontFamily: MONO, fontWeight: 600 }}>{valueFn(it)}</div>}
            <div style={{
              width: "100%", borderRadius: "4px 4px 2px 2px", height: h,
              background: col, opacity: v ? 1 : 0.25,
              boxShadow: it[todayKey] ? `0 0 0 1.5px ${C.t}` : "none",
              transition: "height 1s ease",
            }} />
            <span style={{ fontSize: 8, color: it[todayKey] ? C.t2 : C.t4, fontFamily: MONO, fontWeight: 700 }}>
              {labelFn ? labelFn(it) : it.d}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── PROGRESS BAR ───────────────────────────────────────────────
function ProgressBar({ C, val, max, color, height = 6 }) {
  const pct = Math.max(0, Math.min(100, (val / max) * 100));
  return (
    <div style={{ height, borderRadius: height / 2, background: C.s4, overflow: "hidden" }}>
      <div style={{ height: "100%", borderRadius: height / 2, width: `${pct}%`, background: color, transition: "width 1s ease" }} />
    </div>
  );
}

// ─── SECTION HEADER ─────────────────────────────────────────────
function SectionHead({ C, kicker, title, right }) {
  return (
    <div style={{ padding: "18px 4px 10px", display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 8 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        {kicker && <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".18em", color: C.t4, fontWeight: 700, marginBottom: 2, whiteSpace: "nowrap" }}>{kicker}</div>}
        <div style={{ fontSize: 16, fontWeight: 700, color: C.t, letterSpacing: "-.01em", whiteSpace: "nowrap" }}>{title}</div>
      </div>
      <div style={{ flexShrink: 0 }}>{right}</div>
    </div>
  );
}

// ─── TAB BAR (bottom nav) ───────────────────────────────────────
function TabBar({ C, tabs, active, onChange }) {
  return (
    <div style={{
      position: "absolute", bottom: 0, left: 0, right: 0, zIndex: 40,
      padding: "8px 12px 26px", background: `linear-gradient(180deg, ${C.bg}00 0%, ${C.bg} 35%)`,
      fontFamily: FONT,
    }}>
      <div style={{
        display: "flex", background: C.s, borderRadius: 22, padding: 5,
        border: `1px solid ${C.border}`, boxShadow: "0 12px 32px rgba(0,0,0,.4)",
      }}>
        {tabs.map(t => {
          const isActive = active === t.id;
          return (
            <button key={t.id} onClick={() => onChange(t.id)} style={{
              flex: 1, background: isActive ? C.s3 : "transparent",
              border: "none", color: isActive ? C.t : C.t3, padding: "9px 6px",
              borderRadius: 18, fontFamily: FONT, fontSize: 9.5, fontWeight: 700,
              cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
              transition: "all .2s ease", letterSpacing: ".01em",
            }}>
              <TabIcon id={t.id} color={isActive ? t.activeColor || C.primary : C.t3} />
              {t.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TabIcon({ id, color }) {
  const s = 18;
  const p = { width: s, height: s, stroke: color, strokeWidth: 2, fill: "none", strokeLinecap: "round", strokeLinejoin: "round" };
  if (id === "today") return <svg viewBox="0 0 24 24" {...p}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1.5" fill={color}/></svg>;
  if (id === "train") return <svg viewBox="0 0 24 24" {...p}><path d="M4 9v6M8 7v10M12 5v14M16 7v10M20 9v6"/></svg>;
  if (id === "fuel") return <svg viewBox="0 0 24 24" {...p}><path d="M6 3h12l-1 10a6 6 0 01-10 0L6 3z"/><path d="M9 3v4M15 3v4"/></svg>;
  if (id === "body") return <svg viewBox="0 0 24 24" {...p}><circle cx="12" cy="5" r="2.5"/><path d="M12 7.5V15M9 15l-2 6M15 15l2 6M8 11h8"/></svg>;
  if (id === "trends") return <svg viewBox="0 0 24 24" {...p}><path d="M3 17l5-5 4 4 8-9"/><path d="M15 7h5v5"/></svg>;
  if (id === "coach") return <svg viewBox="0 0 24 24" {...p}><path d="M4 6a2 2 0 012-2h12a2 2 0 012 2v9a2 2 0 01-2 2H9l-4 4v-4H6a2 2 0 01-2-2V6z"/></svg>;
  return null;
}

// ─── SHEET (bottom modal) ───────────────────────────────────────
function Sheet({ C, open, onClose, title, children, height = "70%" }) {
  return (
    <div style={{
      position: "absolute", inset: 0, zIndex: 100,
      pointerEvents: open ? "auto" : "none",
    }}>
      <div onClick={onClose} style={{
        position: "absolute", inset: 0, background: "rgba(0,0,0,.55)",
        opacity: open ? 1 : 0, transition: "opacity .25s ease",
      }} />
      <div style={{
        position: "absolute", left: 0, right: 0, bottom: 0, height,
        background: C.bg, borderRadius: "24px 24px 0 0",
        border: `1px solid ${C.border}`, borderBottom: "none",
        transform: open ? "translateY(0)" : "translateY(110%)",
        transition: "transform .3s cubic-bezier(.2,.8,.2,1)",
        display: "flex", flexDirection: "column", overflow: "hidden",
        boxShadow: "0 -20px 60px rgba(0,0,0,.6)",
      }}>
        <div style={{ padding: "10px 0 4px", display: "flex", justifyContent: "center" }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: C.s4 }} />
        </div>
        {title && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 18px 10px" }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.t, fontFamily: FONT, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</div>
            <button onClick={onClose} style={{
              background: C.s2, border: "none", color: C.t2, width: 28, height: 28,
              borderRadius: 14, cursor: "pointer", fontSize: 14, fontFamily: FONT, fontWeight: 600,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>✕</button>
          </div>
        )}
        <div style={{ flex: 1, overflow: "auto", padding: "0 16px 24px" }}>{children}</div>
      </div>
    </div>
  );
}

// ─── BUTTON ─────────────────────────────────────────────────────
function Btn({ C, children, onClick, primary, small, full, style }) {
  return (
    <button onClick={onClick} style={{
      background: primary ? C.primary : C.s2,
      color: primary ? "#0a0a0a" : C.t,
      border: primary ? "none" : `1px solid ${C.s3}`,
      padding: small ? "8px 12px" : "12px 16px",
      borderRadius: small ? 10 : 14,
      fontFamily: FONT, fontSize: small ? 11 : 13, fontWeight: 700,
      cursor: "pointer", width: full ? "100%" : "auto",
      letterSpacing: ".01em", whiteSpace: "nowrap",
      transition: "transform .1s ease, opacity .15s ease",
      ...style,
    }}
    onMouseDown={e => e.currentTarget.style.transform = "scale(0.97)"}
    onMouseUp={e => e.currentTarget.style.transform = "scale(1)"}
    onMouseLeave={e => e.currentTarget.style.transform = "scale(1)"}
    >{children}</button>
  );
}

Object.assign(window, {
  Ring, BigRing, Stat, Panel, Chip, Sparkline, BarRow, ProgressBar,
  SectionHead, TabBar, Sheet, Btn,
});
