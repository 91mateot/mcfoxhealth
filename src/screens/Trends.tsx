import { MONO, type Palette } from "../theme";
import { JOURNAL_TAGS, type Correlation, type TrendMetric, type TrendsResponse } from "../types";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { Sparkline } from "../components/Sparkline";
import { SectionHead } from "../components/SectionHead";

interface TrendsScreenProps {
  C: Palette;
  trends: TrendsResponse;
}

export function TrendsScreen({ C, trends }: TrendsScreenProps) {
  const T = trends.trends30d;
  const S = trends.trendSeries;

  return (
    <div>
      <SectionHead C={C} kicker="Last 30 vs previous 30" title="Trends" />

      <Panel C={C}>
        <div style={{ display: "flex", gap: 10 }}>
          <TrendHero C={C} label="Avg recovery" m={T.recovery} color={C.primary} series={S.recovery} />
          <TrendHero C={C} label="Avg HRV" m={T.hrv} color={C.primary} series={S.hrv} />
        </div>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, marginBottom: 10 }}>
        <TrendTile C={C} label="Resting HR" m={T.rhr} />
        <TrendTile C={C} label="Avg sleep" m={T.sleep} fmt={minToHm} />
        {T.weight && <TrendTile C={C} label="Weight" m={T.weight} precise />}
        {T.bodyFat && <TrendTile C={C} label="Body fat" m={T.bodyFat} precise />}
        <TrendTile C={C} label="Avg protein" m={T.protein} />
        {T.proteinHit && <TrendTile C={C} label="Protein hit %" m={T.proteinHit} />}
        <TrendTile C={C} label="Avg strain" m={T.strain} precise />
        <TrendTile C={C} label="Avg steps" m={T.steps} fmt={(v) => (v / 1000).toFixed(1) + "k"} />
      </div>

      {(T.resp || T.spo2 || T.wristTemp) && (
        <>
          <SectionHead C={C} kicker="Body signals · 30 days" title="Breath, oxygen, temp" />
          <Panel C={C}>
            <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.55, marginBottom: 12 }}>
              Three quieter signals from your watch. Big swings here tend to show up before you feel them — illness, inflammation, poor recovery.
            </div>
            {T.resp && S.resp && (
              <BodySignalRow
                C={C}
                label="Breathing rate"
                hint="breaths per minute while asleep · low and steady is ideal"
                m={T.resp}
                series={S.resp}
                color={C.primary}
                precise
              />
            )}
            {T.spo2 && S.spo2 && (
              <BodySignalRow
                C={C}
                label="Blood oxygen"
                hint="overnight · 95%+ is normal"
                m={T.spo2}
                series={S.spo2}
                color={C.cyan}
                precise
              />
            )}
            {T.wristTemp && S.wristTemp && (
              <BodySignalRow
                C={C}
                label="Skin temperature"
                hint="early signal for illness or inflammation"
                m={T.wristTemp}
                series={S.wristTemp}
                color={C.purple}
                precise
                last
              />
            )}
          </Panel>
        </>
      )}

      <SectionHead
        C={C}
        kicker="Behavior → outcome"
        title="What's moving the needle"
        right={<Chip C={C} color={C.primary}>from journal</Chip>}
      />
      {trends.correlations.length === 0 ? (
        <Panel C={C}>
          <div style={{ fontSize: 12, color: C.t3, textAlign: "center", padding: "12px 0", lineHeight: 1.5 }}>
            Tag your mornings in the journal — correlations appear after ~14 days.
          </div>
        </Panel>
      ) : (
        <Panel C={C} style={{ padding: 4 }}>
          {trends.correlations.slice(0, 7).map((c, i) => (
            <CorrelationRow key={i} C={C} c={c} last={i === Math.min(trends.correlations.length, 7) - 1} />
          ))}
        </Panel>
      )}

      <div style={{ padding: "0 4px 8px" }}>
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.55 }}>
          Correlations update nightly. Higher <span style={{ color: C.t2, fontWeight: 700 }}>n</span> = more confidence.
        </div>
      </div>

      {T.weight && S.weight && (
        <>
          <SectionHead C={C} kicker="Composition" title="Weight · 30 days" />
          <Panel C={C}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>
                {T.weight.cur}
              </div>
              <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>lbs · 30d avg</div>
              <DeltaBadge C={C} m={T.weight} />
            </div>
            <Sparkline data={S.weight} color={C.cyan} h={54} baseline={170} />
            <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between", fontSize: 11, color: C.t4, fontFamily: MONO }}>
              <span>30 days ago</span>
              <span>today</span>
            </div>
          </Panel>
        </>
      )}

      <SectionHead C={C} kicker="Nutrition" title="Protein · 30 days" />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
          <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color: C.primary, letterSpacing: "-.04em" }}>
            {Math.round(T.protein.cur)}
          </div>
          <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>g/day avg · target 180g</div>
          <DeltaBadge C={C} m={T.protein} />
        </div>
        <Sparkline data={S.protein} color={C.primary} h={54} baseline={180} />
      </Panel>
    </div>
  );
}

function TrendHero({ C, label, m, color, series }: { C: Palette; label: string; m: TrendMetric; color: string; series: number[] }) {
  const deltaAbs = m.cur - m.prev;
  const deltaPct = m.prev === 0 ? 0 : (deltaAbs / m.prev) * 100;
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";

  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 6 }}>
        <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.04em" }}>
          {typeof m.cur === "number" && m.cur > 100 ? Math.round(m.cur) : m.cur}
        </div>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>{m.unit}</div>
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, color: col, fontFamily: MONO, marginTop: 3 }}>
        {arrow} {Math.abs(deltaPct).toFixed(0)}% vs prev 30
      </div>
      <div style={{ marginTop: 6 }}>
        <Sparkline data={series} color={col} h={28} fill />
      </div>
    </div>
  );
}

function TrendTile({ C, label, m, precise, fmt }: { C: Palette; label: string; m: TrendMetric; precise?: boolean; fmt?: (v: number) => string }) {
  const deltaAbs = m.cur - m.prev;
  const deltaPct = m.prev === 0 ? 0 : (deltaAbs / m.prev) * 100;
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";
  const display = fmt ? fmt(m.cur) : precise ? m.cur : Math.round(m.cur);

  return (
    <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: "11px 12px" }}>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 5 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3, whiteSpace: "nowrap" }}>
        <div style={{ fontSize: 17, fontWeight: 800, fontFamily: MONO, color: C.t, letterSpacing: "-.04em", lineHeight: 1 }}>
          {display}
        </div>
        {m.unit && !fmt && <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>{m.unit}</div>}
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, color: col, fontFamily: MONO, marginTop: 5 }}>
        {arrow} {Math.abs(deltaPct).toFixed(0)}%
      </div>
    </div>
  );
}

function BodySignalRow({
  C,
  label,
  hint,
  m,
  series,
  color,
  precise,
  last,
}: {
  C: Palette;
  label: string;
  hint: string;
  m: TrendMetric;
  series: number[];
  color: string;
  precise?: boolean;
  last?: boolean;
}) {
  const deltaAbs = m.cur - m.prev;
  const deltaPct = m.prev === 0 ? 0 : (deltaAbs / m.prev) * 100;
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";
  const display = precise ? m.cur : Math.round(m.cur);
  const nonZero = series.filter((v) => v > 0);
  const baseline = nonZero.length ? nonZero.reduce((a, b) => a + b, 0) / nonZero.length : undefined;

  return (
    <div
      style={{
        padding: "10px 0",
        borderBottom: last ? "none" : `1px solid ${C.border}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 2 }}>
        <div style={{ fontSize: 12.5, color: C.t, fontWeight: 700 }}>{label}</div>
        <div style={{ fontSize: 15, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.03em", marginLeft: "auto" }}>
          {display}
          {m.unit && <span style={{ fontSize: 11, color: C.t3, marginLeft: 2 }}>{m.unit}</span>}
        </div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            fontFamily: MONO,
            color: col,
            background: col + "18",
            padding: "2px 6px",
            borderRadius: 4,
          }}
        >
          {arrow} {Math.abs(deltaPct).toFixed(0)}%
        </div>
      </div>
      <div style={{ fontSize: 11, color: C.t4, lineHeight: 1.45, marginBottom: 6 }}>{hint}</div>
      <Sparkline data={series} color={color} h={32} baseline={baseline} />
    </div>
  );
}

function DeltaBadge({ C, m }: { C: Palette; m: TrendMetric }) {
  const deltaAbs = m.cur - m.prev;
  const deltaPct = m.prev === 0 ? 0 : (deltaAbs / m.prev) * 100;
  const improved = (m.better === "up" && deltaAbs > 0) || (m.better === "down" && deltaAbs < 0);
  const col = improved ? C.primary : C.warn;
  const arrow = deltaAbs > 0 ? "▲" : "▼";
  return (
    <div
      style={{
        marginLeft: "auto",
        fontSize: 11,
        fontWeight: 700,
        fontFamily: MONO,
        color: col,
        background: col + "18",
        padding: "3px 8px",
        borderRadius: 5,
      }}
    >
      {arrow} {Math.abs(deltaPct).toFixed(0)}%
    </div>
  );
}

function CorrelationRow({ C, c, last }: { C: Palette; c: Correlation; last: boolean }) {
  const tag = JOURNAL_TAGS.find((t) => t.id === c.tag);
  const col = c.direction === "positive" ? C.primary : C.warn;
  const arrow = c.effect > 0 ? "▲" : "▼";
  const confCol = c.confidence === "high" ? C.primary : c.confidence === "medium" ? C.yellow : C.t4;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "11px 12px",
        borderBottom: last ? "none" : `1px solid ${C.border}`,
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 10,
          flexShrink: 0,
          background: col + "15",
          border: `1px solid ${col}30`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 16,
        }}
      >
        {tag?.icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span
            style={{
              fontSize: 12.5,
              color: C.t,
              fontWeight: 700,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {tag?.label ?? c.tag}
          </span>
          <span style={{ fontSize: 11, color: C.t3, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>→ {c.metric}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
          <div
            style={{
              fontSize: 11,
              color: confCol,
              fontFamily: MONO,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: ".06em",
            }}
          >
            {c.confidence}
          </div>
          <div style={{ width: 3, height: 3, borderRadius: 2, background: C.t4, flexShrink: 0 }} />
          <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>n={c.n}</div>
        </div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 16, fontWeight: 800, fontFamily: MONO, color: col, letterSpacing: "-.04em", whiteSpace: "nowrap" }}>
          {arrow} {Math.abs(c.effect)}
          {c.unit === "%" ? "%" : ""}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap" }}>
          {c.unit !== "%" ? c.unit : "effect"}
        </div>
      </div>
    </div>
  );
}

function minToHm(min: number) {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h + "h " + (m < 10 ? "0" : "") + m + "m";
}
