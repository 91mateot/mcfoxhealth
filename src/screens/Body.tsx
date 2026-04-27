import { MONO, type Palette } from "../theme";
import { MATEO, type BodyResponse, type TodayResponse } from "../types";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { BarRow } from "../components/BarRow";
import { Sparkline } from "../components/Sparkline";
import { Stat } from "../components/Stat";
import { SectionHead } from "../components/SectionHead";

interface BodyScreenProps {
  C: Palette;
  today: TodayResponse;
  body: BodyResponse;
}

export function BodyScreen({ C, today, body }: BodyScreenProps) {
  const weight14d = body.weight14d ?? [];
  const currentWeight = body.current?.weight ?? (weight14d.length ? weight14d[weight14d.length - 1] : MATEO.weight);
  const bodyFat = body.current?.bodyFat ?? MATEO.bodyFat;
  const leanMass = body.current?.leanMass ?? MATEO.leanMass;
  const avgWt = weight14d.length ? (weight14d.reduce((a, b) => a + b, 0) / weight14d.length).toFixed(1) : currentWeight.toFixed(1);
  const stepsWeek = today.stepsWeek ?? [];
  const stepsSum = stepsWeek.reduce((a, s) => a + s.v, 0);
  const stepsAvg = stepsWeek.length ? Math.round(stepsSum / stepsWeek.length) : 0;

  return (
    <div>
      <SectionHead C={C} kicker="Synced from Withings + Apple Health" title="Body & movement" />

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

      {/* Steps */}
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

      {/* Sleep detail */}
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
    </div>
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
