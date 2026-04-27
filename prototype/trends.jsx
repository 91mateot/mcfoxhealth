// Trends screen — 30-day metrics + behavior correlations

function TrendsScreen({ C }) {
  const T = TRENDS_30D;
  return (
    <div>
      <SectionHead C={C} kicker="Last 30 vs previous 30" title="Trends" />

      {/* Hero — recovery + HRV */}
      <Panel C={C}>
        <div style={{ display: "flex", gap: 10 }}>
          <TrendHero C={C} label="Avg recovery" m={T.recovery} color={C.primary}
            series={TREND_SERIES.recovery} />
          <TrendHero C={C} label="Avg HRV" m={T.hrv} color={C.primary}
            series={TREND_SERIES.hrv} />
        </div>
      </Panel>

      {/* Grid of smaller metrics */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, marginBottom: 10 }}>
        <TrendTile C={C} label="Resting HR"    m={T.rhr}       color={C.primary} />
        <TrendTile C={C} label="Avg sleep"     m={T.sleep}     color={C.cyan} fmt={minToHm} />
        <TrendTile C={C} label="Weight"        m={T.weight}    color={C.cyan} precise />
        <TrendTile C={C} label="Body fat"      m={T.bodyFat}   color={C.cyan} precise />
        <TrendTile C={C} label="Avg protein"   m={T.protein}   color={C.primary} />
        <TrendTile C={C} label="Protein hit %" m={T.proteinHit}color={C.primary} />
        <TrendTile C={C} label="Avg strain"    m={T.strain}    color={C.warn} precise />
        <TrendTile C={C} label="Avg steps"     m={T.steps}     color={C.cyan} fmt={steps => (steps/1000).toFixed(1) + "k"} />
      </div>

      {/* Correlations — the key insight */}
      <SectionHead C={C} kicker="Behavior → outcome" title="What's moving the needle" right={
        <Chip C={C} color={C.primary}>from journal</Chip>
      } />
      <Panel C={C} style={{ padding: 4 }}>
        {CORRELATIONS.slice(0, 7).map((c, i) => (
          <CorrelationRow key={i} C={C} c={c} last={i === 6} />
        ))}
      </Panel>

      <div style={{ padding: "0 4px 8px" }}>
        <div style={{ fontSize: 10.5, color: C.t3, lineHeight: 1.55 }}>
          Correlations update nightly. Higher <span style={{ color: C.t2, fontWeight: 700 }}>n</span> = more confidence.
          Tag at least <span style={{ color: C.t2, fontWeight: 700 }}>14 nights</span> for a signal to stabilize.
        </div>
      </div>

      {/* Weight trend sparkline — long view */}
      <SectionHead C={C} kicker="Composition" title="Weight · 30 days" />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
          <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>{T.weight.cur}</div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>lbs · 30d avg</div>
          <DeltaBadge C={C} m={T.weight} />
        </div>
        <Sparkline data={TREND_SERIES.weight} color={C.cyan} h={54} baseline={170} />
        <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between", fontSize: 9, color: C.t4, fontFamily: MONO }}>
          <span>30 days ago</span><span>today</span>
        </div>
      </Panel>

      {/* Protein trend */}
      <SectionHead C={C} kicker="Nutrition" title="Protein · 30 days" />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
          <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color: C.primary, letterSpacing: "-.04em" }}>{T.protein.cur}</div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>g/day avg · target 180g</div>
          <DeltaBadge C={C} m={T.protein} />
        </div>
        <Sparkline data={TREND_SERIES.protein} color={C.primary} h={54} baseline={180} />
        <div style={{ marginTop: 10, padding: 10, background: C.s2, borderRadius: 10, fontSize: 11, color: C.t2, lineHeight: 1.5 }}>
          <span style={{ color: C.primary, fontWeight: 700 }}>Up from 98g</span> last 30d.
          Weekend gap (Fri–Sun) still the weak point — plan a Saturday protein anchor.
        </div>
      </Panel>
    </div>
  );
}

function TrendHero({ C, label, m, color, series }) {
  const deltaAbs = (m.cur - m.prev);
  const deltaPct = (deltaAbs / m.prev * 100);
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";

  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 6 }}>
        <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.04em" }}>
          {typeof m.cur === "number" && m.cur > 100 ? Math.round(m.cur) : m.cur}
        </div>
        <div style={{ fontSize: 9, color: C.t3, fontFamily: MONO }}>{m.unit}</div>
      </div>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: col, fontFamily: MONO, marginTop: 3 }}>
        {arrow} {Math.abs(deltaPct).toFixed(0)}% vs prev 30
      </div>
      <div style={{ marginTop: 6 }}>
        <Sparkline data={series} color={col} h={28} fill />
      </div>
    </div>
  );
}

function TrendTile({ C, label, m, color, precise, fmt }) {
  const deltaAbs = m.cur - m.prev;
  const deltaPct = (deltaAbs / m.prev * 100);
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";
  const display = fmt ? fmt(m.cur) : (precise ? m.cur : Math.round(m.cur));

  return (
    <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: "11px 12px" }}>
      <div style={{ fontSize: 9, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 5 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3, whiteSpace: "nowrap" }}>
        <div style={{ fontSize: 17, fontWeight: 800, fontFamily: MONO, color: C.t, letterSpacing: "-.04em", lineHeight: 1, whiteSpace: "nowrap" }}>
          {display}
        </div>
        {m.unit && !fmt && <div style={{ fontSize: 9, color: C.t3, fontFamily: MONO }}>{m.unit}</div>}
      </div>
      <div style={{ fontSize: 9, fontWeight: 700, color: col, fontFamily: MONO, marginTop: 5 }}>
        {arrow} {Math.abs(deltaPct).toFixed(0)}%
      </div>
    </div>
  );
}

function DeltaBadge({ C, m }) {
  const deltaAbs = m.cur - m.prev;
  const deltaPct = (deltaAbs / m.prev * 100);
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";
  return (
    <div style={{
      marginLeft: "auto", fontSize: 9, fontWeight: 700, fontFamily: MONO,
      color: col, background: col + "18", padding: "3px 8px", borderRadius: 5,
    }}>{arrow} {Math.abs(deltaPct).toFixed(0)}%</div>
  );
}

function CorrelationRow({ C, c, last }) {
  const tag = JOURNAL_TAGS.find(t => t.id === c.tag);
  const col = c.direction === "positive" ? C.primary : C.warn;
  const arrow = c.effect > 0 ? "▲" : "▼";
  const confCol = c.confidence === "high" ? C.primary : c.confidence === "medium" ? C.yellow : C.t4;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, padding: "11px 12px",
      borderBottom: last ? "none" : `1px solid ${C.border}`,
    }}>
      <div style={{
        width: 34, height: 34, borderRadius: 10, flexShrink: 0,
        background: col + "15", border: `1px solid ${col}30`,
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16,
      }}>{tag?.icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, whiteSpace: "nowrap", overflow: "hidden" }}>
          <span style={{ fontSize: 12.5, color: C.t, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{tag?.label}</span>
          <span style={{ fontSize: 10.5, color: C.t3, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>→ {c.metric}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3, whiteSpace: "nowrap" }}>
          <div style={{ fontSize: 9, color: confCol, fontFamily: MONO, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em" }}>
            {c.confidence}
          </div>
          <div style={{ width: 3, height: 3, borderRadius: 2, background: C.t4, flexShrink: 0 }} />
          <div style={{ fontSize: 9, color: C.t4, fontFamily: MONO }}>n={c.n}</div>
        </div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 16, fontWeight: 800, fontFamily: MONO, color: col, letterSpacing: "-.04em", whiteSpace: "nowrap" }}>
          {arrow} {Math.abs(c.effect)}{c.unit === "%" ? "%" : ""}
        </div>
        <div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap" }}>
          {c.unit !== "%" ? c.unit : "effect"}
        </div>
      </div>
    </div>
  );
}

function minToHm(min) {
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  return h + "h " + (m < 10 ? "0" : "") + m + "m";
}

Object.assign(window, { TrendsScreen, TrendHero, TrendTile, DeltaBadge, CorrelationRow, minToHm });
