import { MONO, type Palette } from "../theme";
import {
  JOURNAL_TAGS,
  MATEO,
  type BodyResponse,
  type Correlation,
  type ProgressResponse,
  type TodayResponse,
  type TrendMetric,
  type TrendsResponse,
} from "../types";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { BarRow } from "../components/BarRow";
import { Sparkline } from "../components/Sparkline";
import { Stat } from "../components/Stat";
import { SectionHead } from "../components/SectionHead";

interface ProgressScreenProps {
  C: Palette;
  today: TodayResponse;
  progress: ProgressResponse;
}

export function ProgressScreen({ C, today, progress }: ProgressScreenProps) {
  return (
    <div>
      <NowSection C={C} today={today} body={progress.now} />
      <TrendSection C={C} trends={progress.trend} />
    </div>
  );
}

function NowSection({ C, today, body }: { C: Palette; today: TodayResponse; body: BodyResponse }) {
  const weight14d = body.weight14d ?? [];
  const currentWeight = body.current?.weight ?? (weight14d.length ? weight14d[weight14d.length - 1] : MATEO.weight);
  const bodyFat = body.current?.bodyFat ?? MATEO.bodyFat;
  const leanMass = body.current?.leanMass ?? MATEO.leanMass;
  const avgWt = weight14d.length ? (weight14d.reduce((a, b) => a + b, 0) / weight14d.length).toFixed(1) : currentWeight.toFixed(1);
  const stepsWeek = today.stepsWeek ?? [];
  const stepsSum = stepsWeek.reduce((a, s) => a + s.v, 0);
  const stepsAvg = stepsWeek.length ? Math.round(stepsSum / stepsWeek.length) : 0;

  return (
    <>
      <SectionHead C={C} kicker="Now" title="Body & movement" />

      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
              Weight · last 14 days
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 4 }}>
              <div style={{ fontSize: 32, fontWeight: 800, color: C.t, fontFamily: MONO, letterSpacing: "-.04em" }}>
                {currentWeight.toFixed(1)}
              </div>
              <div style={{ fontSize: 12, color: C.t3, fontFamily: MONO }}>lbs</div>
              <div style={{ fontSize: 11, color: C.primary, fontFamily: MONO, fontWeight: 700, marginLeft: 6 }}>
                14-day avg {avgWt}
              </div>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>Body fat</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: C.cyan, fontFamily: MONO, letterSpacing: "-.04em", marginTop: 3 }}>
              {bodyFat}%
            </div>
            <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>goal &lt;12%</div>
          </div>
        </div>
        {weight14d.length > 0 && <Sparkline data={weight14d} color={C.cyan} h={52} />}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 10 }}>
          <Stat C={C} label="Muscle" value={leanMass} unit="lbs" valueC={C.primary} sub="lean mass" />
          <Stat C={C} label="Height" value={MATEO.height} sub="173 cm" />
          <Stat C={C} label="BMI" value="25.7" sub="athletic range" />
        </div>
      </Panel>

      <SectionHead C={C} kicker="Movement" title="Steps · 7 days" right={<Chip C={C} color={C.cyan}>avg {stepsAvg.toLocaleString()}</Chip>} />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 10 }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: C.t, fontFamily: MONO, letterSpacing: "-.04em" }}>
            {today.steps.toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>of {today.stepsGoal.toLocaleString()} today</div>
        </div>
        <BarRow
          C={C}
          items={stepsWeek}
          accessor="v"
          height={48}
          colorFn={(_it, v) => (v >= 10000 ? C.primary : v >= 7000 ? C.yellow : C.t4)}
          valueFn={(it) => (it.v / 1000).toFixed(0) + "k"}
        />
      </Panel>

      <SectionHead C={C} kicker="Last night" title="Sleep stages" />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: C.cyan, fontFamily: MONO, letterSpacing: "-.04em" }}>
            {today.sleep.hours}
            <span style={{ fontSize: 18 }}>h</span> {today.sleep.minutes}
            <span style={{ fontSize: 18 }}>m</span>
          </div>
          <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, marginLeft: 4 }}>
            {today.sleep.efficiency}% of time in bed was asleep
          </div>
        </div>
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, margin: "6px 0 10px" }}>
          Your body cycles through stages. <span style={{ color: "#6a84ff", fontWeight: 600 }}>Deep</span> rebuilds the body,
          <span style={{ color: C.purple, fontWeight: 600 }}> REM</span> is for memory + mood,
          <span style={{ color: C.cyan, fontWeight: 600 }}> Light</span> is the in-between.
        </div>
        <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 10 }}>
          <div style={{ flex: today.sleep.deep, background: "#3b5cff" }} />
          <div style={{ flex: today.sleep.rem, background: C.purple }} />
          <div style={{ flex: today.sleep.core, background: C.cyan, opacity: 0.6 }} />
          <div style={{ flex: today.sleep.awake, background: C.t4 }} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
          <SleepStage C={C} label="Deep" min={today.sleep.deep} col="#3b5cff" />
          <SleepStage C={C} label="REM" min={today.sleep.rem} col={C.purple} />
          <SleepStage C={C} label="Light" min={today.sleep.core} col={C.cyan} />
          <SleepStage C={C} label="Awake" min={today.sleep.awake} col={C.t4} />
        </div>
      </Panel>
    </>
  );
}

function TrendSection({ C, trends }: { C: Palette; trends: TrendsResponse }) {
  const T = trends.trends30d;
  const S = trends.trendSeries;

  return (
    <>
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
    </>
  );
}

function SleepStage({ C, label, min, col }: { C: Palette; label: string; min: number; col: string }) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return (
    <div style={{ background: C.s2, borderRadius: 10, padding: "8px 6px", textAlign: "center" }}>
      <div style={{ width: 6, height: 6, borderRadius: 3, background: col, margin: "0 auto 4px" }} />
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: MONO, color: C.t, marginTop: 2, letterSpacing: "-.02em" }}>
        {h > 0 && h + "h"}
        {m}m
      </div>
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
