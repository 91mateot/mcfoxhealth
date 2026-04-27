// Fuel, Body, Coach screens

// ─── FUEL ───────────────────────────────────────────────────────
function FuelScreen({ C, onLogMeal }) {
  const eaten = MEALS_TODAY.reduce((a, m) => ({
    cal: a.cal + m.cal, p: a.p + m.p, c: a.c + m.c, f: a.f + m.f,
  }), { cal: 0, p: 0, c: 0, f: 0 });
  const T = NUTRITION_TARGETS;
  const proj = {
    cal: eaten.cal + MEAL_PLANNED.cal, p: eaten.p + MEAL_PLANNED.p,
    c: eaten.c + MEAL_PLANNED.c, f: eaten.f + MEAL_PLANNED.f,
  };
  const proteinGap = T.p - proj.p;

  return (
    <div>
      <SectionHead C={C} kicker="Today" title="Fuel" right={
        <Chip C={C} color={C.primary}>{eaten.cal} / {T.cal} kcal</Chip>
      } />

      {/* Calorie ring + macros */}
      <Panel C={C}>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <div style={{ position: "relative", width: 96, height: 96, flexShrink: 0 }}>
            <Ring val={eaten.cal} max={T.cal} color={C.primary} trackColor={C.s3} size={96} stroke={6.5} />
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: C.primary, fontFamily: MONO, letterSpacing: "-.04em" }}>{Math.round(eaten.cal/T.cal*100)}%</div>
              <div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO }}>of {T.cal}</div>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <MacroLine C={C} label="Protein" val={eaten.p} goal={T.p} color={C.primary} unit="g" />
            <MacroLine C={C} label="Carbs" val={Math.round(eaten.c)} goal={T.c} color={C.yellow} unit="g" />
            <MacroLine C={C} label="Fat" val={eaten.f} goal={T.f} color={C.purple} unit="g" />
          </div>
        </div>
      </Panel>

      {/* Projection */}
      <Panel C={C} style={{ background: C.primaryDim, borderColor: C.primary + "40" }}>
        <div style={{ fontSize: 10, color: C.primary, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
          If you eat the planned dinner
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 6 }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: C.t, fontFamily: MONO, letterSpacing: "-.03em" }}>{proj.cal}</div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>kcal · {proj.p}g protein · {Math.round(proj.c)}g carbs · {proj.f}g fat</div>
        </div>
        <div style={{ fontSize: 11, color: C.t2, marginTop: 8, lineHeight: 1.5 }}>
          You'd still be <span style={{ color: C.warn, fontWeight: 700 }}>{proteinGap}g short on protein</span>.
          One Oikos (30g protein · 170 kcal) gets you over your 180g goal.
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 6 }}>
          <Btn C={C} primary small onClick={() => onLogMeal("Oikos")}>+ Add Oikos</Btn>
          <Btn C={C} small onClick={() => onLogMeal("Protein bar")}>+ Protein bar</Btn>
        </div>
      </Panel>

      {/* Today's meals */}
      <SectionHead C={C} kicker="Logged" title="Today's meals" right={
        <Chip C={C}>{MEALS_TODAY.length} items</Chip>
      } />
      <Panel C={C} style={{ padding: 6 }}>
        {MEALS_TODAY.map((m, i) => (
          <MealRow key={m.id} C={C} m={m} last={i === MEALS_TODAY.length - 1} />
        ))}
      </Panel>
      <Panel C={C} style={{ padding: 6, opacity: 0.7, borderStyle: "dashed", borderColor: C.s3 }}>
        <MealRow C={C} m={MEAL_PLANNED} last planned />
      </Panel>

      {/* 7-day protein */}
      <SectionHead C={C} kicker="Trend" title="7-day protein" right={
        <Chip C={C} color={C.primary}>target {T.p}g</Chip>
      } />
      <Panel C={C}>
        <BarRow C={C} items={PROTEIN_WEEK} accessor="p" height={56}
          colorFn={(it, v) => v >= T.p ? C.primary : v >= 100 ? C.yellow : C.danger}
          valueFn={(it) => it.p + "g"} />
        <div style={{ marginTop: 10, padding: 10, background: C.s2, borderRadius: 10, fontSize: 11, color: C.t2, lineHeight: 1.5 }}>
          <span style={{ color: C.danger, fontWeight: 700 }}>3 days under 100g</span> last week (Fri–Sun).
          Then Monday you overshot to 242g, which your recovery score didn't like. Consistent beats heroic.
        </div>
      </Panel>

      {/* Supplements */}
      <SectionHead C={C} kicker="Stack" title="Supplements" />
      <Panel C={C} style={{ padding: 8 }}>
        {SUPPLEMENTS.map((s, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "9px 8px",
            borderBottom: i === SUPPLEMENTS.length - 1 ? "none" : `1px solid ${C.border}`,
          }}>
            <div style={{
              width: 20, height: 20, borderRadius: 6, flexShrink: 0,
              background: s.taken ? C.primary : "transparent",
              border: s.taken ? "none" : `1.5px solid ${C.s4}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: C.bg, fontSize: 11, fontWeight: 800,
            }}>{s.taken ? "✓" : ""}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: C.t, fontWeight: 600 }}>{s.name}</div>
              <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO }}>{s.dose} · {s.timing}</div>
            </div>
          </div>
        ))}
      </Panel>

      <div style={{ margin: "4px 0 8px" }}>
        <Btn C={C} primary full onClick={() => onLogMeal()}>+ Log meal</Btn>
      </div>
    </div>
  );
}

function MacroLine({ C, label, val, goal, color, unit }) {
  const pct = Math.min(100, val / goal * 100);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 3 }}>
        <span style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>{label}</span>
        <span style={{ fontSize: 11, fontFamily: MONO, fontWeight: 700, color, whiteSpace: "nowrap" }}>
          {val}{unit} <span style={{ color: C.t4, fontWeight: 500 }}>/ {goal}{unit}</span>
        </span>
      </div>
      <ProgressBar C={C} val={val} max={goal} color={color} height={4} />
    </div>
  );
}

function MealRow({ C, m, last, planned }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, padding: "10px 10px",
      borderBottom: last ? "none" : `1px solid ${C.border}`,
    }}>
      <div style={{ width: 42 }}>
        <div style={{ fontSize: 10, color: planned ? C.t4 : C.t3, fontFamily: MONO, fontWeight: 600 }}>{m.time}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, color: planned ? C.t3 : C.t, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {m.name}{planned && " · planned"}
        </div>
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{m.portion}</div>
      </div>
      <div style={{ textAlign: "right", minWidth: 50 }}>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: MONO, color: planned ? C.t3 : C.t }}>{m.cal}</div>
        <div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO }}>P{m.p} C{m.c} F{m.f}</div>
      </div>
    </div>
  );
}

// ─── BODY ───────────────────────────────────────────────────────
function BodyScreen({ C }) {
  const avgWt = (WEIGHT_14D.reduce((a, b) => a + b, 0) / WEIGHT_14D.length).toFixed(1);
  const steps = STEPS_WEEK.reduce((a, s) => a + s.v, 0);
  const stepsAvg = Math.round(steps / 7);

  return (
    <div>
      <SectionHead C={C} kicker="Synced from Withings + Apple Health" title="Body & movement" />

      {/* Weight card */}
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>Weight · last 14 days</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 4 }}>
              <div style={{ fontSize: 32, fontWeight: 800, color: C.t, fontFamily: MONO, letterSpacing: "-.04em" }}>{MATEO.weight}</div>
              <div style={{ fontSize: 12, color: C.t3, fontFamily: MONO }}>lbs</div>
              <div style={{ fontSize: 10, color: C.primary, fontFamily: MONO, fontWeight: 700, marginLeft: 6 }}>14-day avg {avgWt}</div>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>Body fat</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: C.cyan, fontFamily: MONO, letterSpacing: "-.04em", marginTop: 3 }}>{MATEO.bodyFat}%</div>
            <div style={{ fontSize: 9, color: C.t4, fontFamily: MONO }}>goal &lt;12%</div>
          </div>
        </div>
        <Sparkline data={WEIGHT_14D} color={C.cyan} h={52} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 10 }}>
          <Stat C={C} label="Muscle" value={MATEO.leanMass} unit="lbs" valueC={C.primary} sub="lean mass" />
          <Stat C={C} label="Height" value="5'8&quot;" sub="173 cm" />
          <Stat C={C} label="BMI" value="25.7" sub="athletic range" />
        </div>
      </Panel>

      {/* Recomp tracker */}
      <Panel C={C} title="Weight change · this year" right={<Chip C={C} color={C.primary}>Jan → Apr</Chip>}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
          {[
            { m: "Jan", w: BODY_HISTORY.jan, bf: "~14%" },
            { m: "Feb", w: BODY_HISTORY.feb, bf: "~13.9%" },
            { m: "Mar", w: BODY_HISTORY.mar, bf: "~13.7%" },
            { m: "Apr", w: BODY_HISTORY.apr, bf: "13.6%", now: true },
          ].map((x, i) => (
            <div key={i} style={{
              background: x.now ? C.primaryDim : C.s2, borderRadius: 10, padding: "9px 6px",
              textAlign: "center", border: x.now ? `1px solid ${C.primary}40` : "1px solid transparent",
            }}>
              <div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO, fontWeight: 700 }}>{x.m.toUpperCase()}</div>
              <div style={{ fontSize: 15, fontWeight: 800, fontFamily: MONO, color: x.now ? C.primary : C.t, letterSpacing: "-.03em", marginTop: 3 }}>{x.w}</div>
              <div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO, marginTop: 2 }}>{x.bf}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10, padding: 10, background: C.s2, borderRadius: 10, fontSize: 11, color: C.t2, lineHeight: 1.5 }}>
          Weight's been 168–170 since February. <span style={{ color: C.primary, fontWeight: 700 }}>Losing 0.5–1 lb a week is healthy.</span> If you drop faster than 1.5 lb/week we'll bump calories — that pace burns muscle, not just fat.
        </div>
      </Panel>

      {/* Steps */}
      <SectionHead C={C} kicker="Movement" title="Steps · 7 days" right={
        <Chip C={C} color={C.cyan}>avg {stepsAvg.toLocaleString()}</Chip>
      } />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 10 }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: C.t, fontFamily: MONO, letterSpacing: "-.04em" }}>{TODAY.steps.toLocaleString()}</div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>of {TODAY.stepsGoal.toLocaleString()} today</div>
        </div>
        <BarRow C={C} items={STEPS_WEEK} accessor="v" height={48}
          colorFn={(it, v) => v >= 10000 ? C.primary : v >= 7000 ? C.yellow : C.t4}
          valueFn={(it) => (it.v/1000).toFixed(0) + "k"} />
      </Panel>

      {/* Sleep detail */}
      <SectionHead C={C} kicker="Last night" title="Sleep stages" />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: C.cyan, fontFamily: MONO, letterSpacing: "-.04em" }}>
            {TODAY.sleep.hours}<span style={{ fontSize: 18 }}>h</span> {TODAY.sleep.minutes}<span style={{ fontSize: 18 }}>m</span>
          </div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO, marginLeft: 4 }}>{TODAY.sleep.efficiency}% of time in bed was asleep</div>
        </div>
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, margin: "6px 0 10px" }}>
          Your body cycles through stages. <span style={{ color: "#6a84ff", fontWeight: 600 }}>Deep</span> rebuilds the body,
          <span style={{ color: C.purple, fontWeight: 600 }}> REM</span> is for memory + mood,
          <span style={{ color: C.cyan, fontWeight: 600 }}> Light</span> is the in-between.
        </div>
        {/* Stage bar */}
        <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 10 }}>
          <div style={{ flex: TODAY.sleep.deep, background: "#3b5cff" }} />
          <div style={{ flex: TODAY.sleep.rem, background: C.purple }} />
          <div style={{ flex: TODAY.sleep.core, background: C.cyan, opacity: 0.6 }} />
          <div style={{ flex: TODAY.sleep.awake, background: C.t4 }} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
          <SleepStage C={C} label="Deep" min={TODAY.sleep.deep} col="#3b5cff" />
          <SleepStage C={C} label="REM" min={TODAY.sleep.rem} col={C.purple} />
          <SleepStage C={C} label="Light" min={TODAY.sleep.core} col={C.cyan} />
          <SleepStage C={C} label="Awake" min={TODAY.sleep.awake} col={C.t4} />
        </div>
      </Panel>
    </div>
  );
}

function SleepStage({ C, label, min, col }) {
  const h = Math.floor(min / 60), m = min % 60;
  return (
    <div style={{ background: C.s2, borderRadius: 10, padding: "8px 6px", textAlign: "center" }}>
      <div style={{ width: 6, height: 6, borderRadius: 3, background: col, margin: "0 auto 4px" }} />
      <div style={{ fontSize: 9, color: C.t3, textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: MONO, color: C.t, marginTop: 2, letterSpacing: "-.02em" }}>
        {h > 0 && h + "h"}{m}m
      </div>
    </div>
  );
}

// ─── COACH ──────────────────────────────────────────────────────
function CoachScreen({ C, onOpenChat }) {
  return (
    <div>
      <SectionHead C={C} kicker="AI briefings" title="Coach" />

      {/* Insights */}
      {COACH_INSIGHTS.map((ins, i) => {
        const col = ins.tag === "green" ? C.primary : ins.tag === "yellow" ? C.yellow : ins.tag === "blue" ? C.cyan : C.warn;
        return (
          <Panel key={i} C={C}>
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{
                width: 32, height: 32, borderRadius: 10, flexShrink: 0,
                background: col + "20", border: `1px solid ${col}40`,
                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16,
              }}>{ins.icon}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: C.t }}>{ins.title}</div>
                <div style={{ fontSize: 11.5, color: C.t2, marginTop: 5, lineHeight: 1.5 }}>{ins.body}</div>
              </div>
            </div>
          </Panel>
        );
      })}

      {/* CTA to open chat */}
      <button onClick={onOpenChat} style={{
        width: "100%", background: C.primary, border: "none", color: "#0a0a0a",
        borderRadius: 18, padding: "14px 16px", marginTop: 4, fontFamily: FONT,
        fontSize: 14, fontWeight: 800, cursor: "pointer", letterSpacing: ".01em",
        display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
      }}>💬 Ask Coach anything</button>

      {/* Quick prompts */}
      <SectionHead C={C} kicker="Try asking" title="Daily commands" />
      <Panel C={C} style={{ padding: 10 }}>
        {[
          "Morning briefing",
          "End of day report",
          "Weekly review",
          "What should I eat next?",
          "Am I cleared to train?",
          "What's my protein gap?",
        ].map((q, i) => (
          <button key={i} onClick={onOpenChat} style={{
            width: "100%", textAlign: "left", background: C.s2, border: "none",
            padding: "10px 12px", borderRadius: 10, color: C.t2, fontSize: 12,
            fontFamily: FONT, fontWeight: 600, cursor: "pointer", marginBottom: 6,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span>"{q}"</span>
            <span style={{ color: C.t4, fontSize: 11 }}>→</span>
          </button>
        ))}
      </Panel>
    </div>
  );
}

Object.assign(window, { FuelScreen, MacroLine, MealRow, BodyScreen, SleepStage, CoachScreen });
