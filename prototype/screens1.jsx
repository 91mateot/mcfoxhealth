// Screens — Today, Train, Fuel, Body, Coach

// ─── TODAY ──────────────────────────────────────────────────────
function TodayScreen({ C, onRingTap, onOpenChat, onLogMeal, onLogWorkout, onOpenJournal }) {
  const hrvDelta = ((TODAY.hrv - BASE.hrv) / BASE.hrv * 100);
  const rhrDelta = ((TODAY.rhr - BASE.rhr) / BASE.rhr * 100);
  const need = TODAY.sleepNeedTonight;
  const needH = Math.floor(need.totalMin / 60), needM = need.totalMin % 60;

  return (
    <div>
      {/* Greeting */}
      <div style={{ padding: "8px 4px 14px" }}>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, letterSpacing: ".04em" }}>
          {TODAY.dateFull.toUpperCase()} · PACIFIC BEACH
        </div>
        <div style={{ fontSize: 26, fontWeight: 700, color: C.t, letterSpacing: "-.02em", marginTop: 4, lineHeight: 1.15 }}>
          Morning, Mateo.<br/>
          <span style={{ color: C.primary }}>Recovered.</span> Train today.
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Chip C={C} color={C.primary}>● GREEN</Chip>
          <Chip C={C} color={C.cyan}>PUSH DAY</Chip>
          <Chip C={C} color={C.t3}>RECOMP</Chip>
        </div>
      </div>

      {/* Journal check-in — shown first if pending */}
      {!JOURNAL_TODAY.submitted && (
        <JournalCard C={C} onOpen={onOpenJournal} />
      )}

      {/* Hero rings */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 7, marginBottom: 10 }}>
        <BigRing C={C} val={TODAY.recovery} max={100} color={C.primary}
          label="Recovered" display={TODAY.recovery} unit="%"
          tag="Ready" tagC={C.primary} onClick={() => onRingTap("recovery")} />
        <StrainRing C={C} onClick={() => onRingTap("strain")} />
        <BigRing C={C} val={TODAY.sleep.score} max={100} color={C.cyan}
          label="Slept" display={`${TODAY.sleep.hours}:${String(TODAY.sleep.minutes).padStart(2,"0")}`} unit={`${TODAY.sleep.score}% quality`}
          tag="Solid" tagC={C.cyan} onClick={() => onRingTap("sleep")} />
      </div>

      {/* Plain-English summary — what the numbers mean today */}
      <Panel C={C} style={{ background: C.s, padding: "12px 14px" }}>
        <div style={{ fontSize: 10, color: C.primary, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>In plain English</div>
        <div style={{ fontSize: 13, color: C.t, marginTop: 6, lineHeight: 1.5, fontWeight: 500 }}>
          Your body <span style={{ color: C.primary, fontWeight: 700 }}>bounced back overnight</span>.
          Nervous system is fresh, heart's relaxed. Good day to <span style={{ color: C.t, fontWeight: 700 }}>push</span> —
          effort target <span style={{ color: C.warn, fontWeight: 700 }}>14–17</span>, then in bed by <span style={{ color: C.cyan, fontWeight: 700 }}>{need.bedtimeBy}</span>.
        </div>
        <button onClick={() => onRingTap("primer")} style={{
          marginTop: 10, background: "none", border: "none", padding: 0,
          color: C.t3, fontSize: 10.5, fontWeight: 600, cursor: "pointer", fontFamily: FONT,
          display: "flex", alignItems: "center", gap: 4,
        }}>
          <span style={{ width: 14, height: 14, borderRadius: 7, background: C.s3, color: C.t2, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800 }}>?</span>
          What do these numbers actually mean?
        </button>
      </Panel>

      {/* Today's target strip — plain language */}
      <Panel C={C} style={{ background: C.s, padding: "12px 14px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 9, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Aim for today</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 3, whiteSpace: "nowrap" }}>
              <div style={{ fontSize: 20, fontWeight: 800, fontFamily: MONO, color: C.warn, letterSpacing: "-.04em", whiteSpace: "nowrap" }}>
                {TODAY.strainTarget.low}–{TODAY.strainTarget.high}
              </div>
              <div style={{ fontSize: 9.5, color: C.t4, fontFamily: MONO }}>effort</div>
            </div>
            <div style={{ fontSize: 9.5, color: C.t4, fontFamily: MONO, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Hard day OK</div>
          </div>
          <div style={{ width: 1, height: 38, background: C.border, flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 9, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Sleep tonight</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 3, whiteSpace: "nowrap" }}>
              <div style={{ fontSize: 20, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em", whiteSpace: "nowrap" }}>
                {needH}h {needM < 10 ? "0" : ""}{needM}m
              </div>
            </div>
            <div style={{ fontSize: 9.5, color: C.t4, fontFamily: MONO, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>bed by {need.bedtimeBy}</div>
          </div>
        </div>
      </Panel>

      {/* Coach banner */}
      {TWEAKS.showCoachInsights && (
        <button onClick={onOpenChat} style={{
          width: "100%", background: C.s, border: `1px solid ${C.border}`,
          borderRadius: 18, padding: 14, marginBottom: 10, textAlign: "left",
          cursor: "pointer", fontFamily: FONT, color: C.t,
          display: "flex", gap: 12, alignItems: "flex-start",
        }}>
          <div style={{
            width: 34, height: 34, borderRadius: 10, flexShrink: 0,
            background: `linear-gradient(135deg, ${C.primary}, ${C.cyan})`,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: C.bg, fontWeight: 800, fontSize: 13,
          }}>AI</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>Coach · Morning briefing</div>
            <div style={{ fontSize: 12.5, color: C.t, marginTop: 4, lineHeight: 1.45, fontWeight: 500 }}>
              Your nervous system is fresh and your resting pulse is the lowest it's been in a month.
              You're cleared for a push session — keep it back-safe (no loaded squats or deadlifts).
            </div>
            <div style={{ fontSize: 10, color: C.primary, marginTop: 6, fontWeight: 700, display: "flex", alignItems: "center", gap: 4 }}>
              Tap to ask coach →
            </div>
          </div>
        </button>
      )}

      {/* HRV trend — keep the term visible, explain in plain language */}
      <Panel C={C} title="HRV · nervous system freshness"
        right={<Chip C={C} color={C.primary}>fresh today</Chip>}>
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, marginBottom: 10 }}>
          <span style={{ color: C.t2, fontWeight: 700 }}>Heart Rate Variability</span> — how much the gaps between heartbeats vary.
          <span style={{ color: C.t2, fontWeight: 600 }}> Higher = more rested.</span>
          Drops mean stress, poor sleep, alcohol, or hard training the day before.
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
          <div style={{ fontSize: 24, fontWeight: 700, fontFamily: MONO, color: C.primary, letterSpacing: "-.04em" }}>49<span style={{ fontSize: 12, color: C.t3, marginLeft: 3 }}>ms</span></div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>today · above your {BASE.hrv} avg</div>
          <div style={{ marginLeft: "auto", fontSize: 9, color: C.t4, fontFamily: MONO }}>30d avg 46</div>
        </div>
        <Sparkline data={HRV_30D} color={C.primary} h={44} baseline={BASE.hrv} />
        <div style={{ marginTop: 8, fontSize: 10, color: C.t3, lineHeight: 1.5 }}>
          <span style={{ color: C.danger, fontWeight: 700 }}>■</span> Apr 19 dip — alcohol + under-eating + hard workout. Took 48h to come back.
        </div>
      </Panel>

      {/* Week recovery at a glance */}
      <Panel C={C} title="7-day recovery" right={<Chip C={C}>tap a day</Chip>}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 4 }}>
          {RECOVERY_WEEK.map((d, i) => {
            const col = d.tag === "green" ? C.primary : d.tag === "yellow" ? C.yellow : C.danger;
            return (
              <div key={i} style={{
                background: d.today ? col + "18" : C.s2, borderRadius: 10, padding: "7px 2px 8px",
                textAlign: "center", border: d.today ? `1px solid ${col}` : "1px solid transparent",
              }}>
                <div style={{ fontSize: 8, color: C.t4, fontFamily: MONO, fontWeight: 700, letterSpacing: ".05em" }}>{d.d.toUpperCase()}</div>
                <div style={{ fontSize: 7.5, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{d.date}</div>
                <div style={{ fontSize: 14, fontWeight: 800, fontFamily: MONO, color: col, letterSpacing: "-.03em", marginTop: 4 }}>{d.rec}</div>
                <div style={{ height: 2.5, borderRadius: 2, background: C.s4, margin: "4px 4px 0", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${d.rec}%`, background: col }} />
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      {/* Hydration */}
      <Panel C={C} title="Hydration" right={<Chip C={C} color={C.cyan}>{TODAY.water} / {TODAY.waterGoal} oz</Chip>}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
          <div style={{ fontSize: 24, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>{TODAY.water}</div>
          <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>oz · {Math.round(TODAY.water/TODAY.waterGoal*100)}% of daily</div>
          <div style={{ marginLeft: "auto", fontSize: 10, color: C.t4, fontFamily: MONO }}>64 oz left</div>
        </div>
        <ProgressBar C={C} val={TODAY.water} max={TODAY.waterGoal} color={C.cyan} height={6} />
        <div style={{ marginTop: 10, fontSize: 10.5, color: C.t3, lineHeight: 1.5 }}>
          Behind pace at 3pm. Push to 64 oz by dinner to stay on target.
        </div>
      </Panel>

      {/* Quick actions */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, margin: "4px 0 8px" }}>
        <Btn C={C} primary full onClick={onLogMeal}>+ Log meal</Btn>
        <Btn C={C} full onClick={onLogWorkout}>+ Log workout</Btn>
      </div>
    </div>
  );
}

// Strain hero ring with target band overlay (shows where optimal zone sits)
function StrainRing({ C, onClick }) {
  const max = 21;
  const val = TODAY.strain;
  const tgt = TODAY.strainTarget;
  const lowPct = tgt.low / max;
  const highPct = tgt.high / max;

  // Compute arc for target band
  const size = 82, stroke = 5.5;
  const r = (50 - stroke / 2 - 1);
  const ci = 2 * Math.PI * r;
  const bandLen = (highPct - lowPct) * ci;
  const bandDash = `${bandLen} ${ci - bandLen}`;
  const bandOff = ci - lowPct * ci;

  return (
    <button onClick={onClick} style={{
      background: C.s, borderRadius: 22, padding: "16px 8px 14px", textAlign: "center",
      border: `1px solid ${C.border}`, cursor: "pointer", fontFamily: FONT, color: C.t,
      transition: "transform .12s ease",
    }}>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".16em", color: C.t3, fontWeight: 700, marginBottom: 12 }}>Effort</div>
      <div style={{ position: "relative", width: 82, height: 82, margin: "0 auto 10px" }}>
        <svg viewBox="0 0 100 100" style={{ width: size, height: size, transform: "rotate(-90deg)", position: "absolute", inset: 0 }}>
          {/* background track */}
          <circle cx="50" cy="50" r={r} stroke={C.s3} strokeWidth={stroke} fill="none" />
          {/* target band (dimmed warn color) */}
          <circle cx="50" cy="50" r={r} stroke={C.warn} strokeOpacity="0.25"
            strokeWidth={stroke + 1.5} fill="none"
            strokeDasharray={bandDash} strokeDashoffset={bandOff} />
          {/* current strain */}
          <circle cx="50" cy="50" r={r} stroke={C.warn} strokeWidth={stroke} fill="none"
            strokeLinecap="round"
            strokeDasharray={ci} strokeDashoffset={ci - (val / max) * ci}
            style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)" }} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: MONO, letterSpacing: "-.05em", lineHeight: 1, color: C.warn }}>{val.toFixed(1)}</div>
          <div style={{ fontSize: 9, fontWeight: 500, color: C.t3, marginTop: 2, fontFamily: MONO }}>aim {tgt.low}–{tgt.high}</div>
        </div>
      </div>
      <span style={{ fontSize: 9.5, fontWeight: 700, padding: "4px 10px", borderRadius: 20, color: C.warn, background: C.warnDim, textTransform: "uppercase", letterSpacing: ".08em" }}>In progress</span>
    </button>
  );
}

// ─── TRAIN ──────────────────────────────────────────────────────
function TrainScreen({ C, onLogWorkout, week, setWeek }) {
  const w = WORKOUTS[0];
  const weekStrain = RECOVERY_WEEK.reduce((a, d) => a + d.strain, 0);
  const weekCal = WORKOUTS.slice(0, 5).reduce((a, x) => a + x.cal, 0);
  const weekMin = WORKOUTS.slice(0, 5).reduce((a, x) => a + x.dur, 0);

  return (
    <div>
      <SectionHead C={C} kicker="This week" title="Training" right={
        <WeekScrubber C={C} week={week} setWeek={setWeek} />
      } />

      {/* Strain ring + summary */}
      <Panel C={C}>
        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          <div style={{ position: "relative", width: 88, height: 88 }}>
            <Ring val={Math.min(weekStrain, 105)} max={105} color={C.warn} trackColor={C.s3} size={88} stroke={6} />
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.warn, fontFamily: MONO, letterSpacing: "-.04em" }}>{weekStrain.toFixed(0)}</div>
              <div style={{ fontSize: 9, color: C.t3, fontFamily: MONO }}>weekly</div>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>Week strain</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 6 }}>
              <div><div style={{ fontSize: 16, fontWeight: 700, fontFamily: MONO, color: C.t }}>5</div><div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO }}>sessions</div></div>
              <div><div style={{ fontSize: 16, fontWeight: 700, fontFamily: MONO, color: C.t }}>{weekMin}</div><div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO }}>min</div></div>
              <div><div style={{ fontSize: 16, fontWeight: 700, fontFamily: MONO, color: C.t }}>{(weekCal/1000).toFixed(1)}k</div><div style={{ fontSize: 8.5, color: C.t4, fontFamily: MONO }}>kcal</div></div>
            </div>
          </div>
        </div>
      </Panel>

      {/* Strain bars */}
      <Panel C={C} title="Strain by day" right={<Chip C={C} color={C.warn}>{weekStrain.toFixed(0)} / 105</Chip>}>
        <BarRow C={C} items={RECOVERY_WEEK} accessor="strain"
          colorFn={(it, v) => v >= 14 ? C.warn : v >= 10 ? C.yellow : C.primary}
          valueFn={(it) => it.strain.toFixed(0)} />
      </Panel>

      {/* Last session */}
      <SectionHead C={C} kicker="Yesterday" title="Push day recap" />
      <Panel C={C}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.t, letterSpacing: "-.02em", whiteSpace: "nowrap" }}>{w.title}</div>
          <Chip C={C} color={C.warn}>strain {w.strain}</Chip>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
          <Stat C={C} label="Duration" value={w.dur} unit="min" />
          <Stat C={C} label="Avg HR" value={w.avgHR} unit="bpm" valueC={C.warn} />
          <Stat C={C} label="Max HR" value={w.maxHR} unit="bpm" />
          <Stat C={C} label="Active kcal" value={w.cal} valueC={C.primary} />
        </div>
        <div style={{ fontSize: 11, color: C.t2, marginTop: 10, lineHeight: 1.5 }}>
          {w.notes}
        </div>
      </Panel>

      {/* History */}
      <SectionHead C={C} kicker="Log" title="Recent sessions" />
      <Panel C={C} style={{ padding: 6 }}>
        {WORKOUTS.slice(0, 6).map((x, i) => (
          <WorkoutRow key={i} C={C} w={x} last={i === 5} />
        ))}
      </Panel>

      <div style={{ marginTop: 4, marginBottom: 8 }}>
        <Btn C={C} primary full onClick={onLogWorkout}>+ Log workout</Btn>
      </div>
    </div>
  );
}

function WorkoutRow({ C, w, last }) {
  const typeCol = {
    Push: C.primary, Pull: C.cyan, Legs: C.purple, Walk: C.t3, HIIT: C.warn,
  }[w.type] || C.t2;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, padding: "10px 10px",
      borderBottom: last ? "none" : `1px solid ${C.border}`,
    }}>
      <div style={{ width: 40, textAlign: "center" }}>
        <div style={{ fontSize: 8, color: C.t4, fontFamily: MONO, fontWeight: 700 }}>{w.day.toUpperCase()}</div>
        <div style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>{w.date}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600 }}>{w.title}</div>
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginTop: 1 }}>
          {w.dur}m · avg {w.avgHR} · {w.cal} kcal
        </div>
      </div>
      <div style={{
        fontSize: 9, color: typeCol, fontWeight: 700, letterSpacing: ".08em",
        padding: "3px 8px", borderRadius: 6, background: typeCol + "18",
      }}>{w.type.toUpperCase()}</div>
      <div style={{ textAlign: "right", minWidth: 36 }}>
        <div style={{ fontSize: 14, fontWeight: 700, fontFamily: MONO, color: C.warn, letterSpacing: "-.03em" }}>{w.strain}</div>
        <div style={{ fontSize: 8, color: C.t4, fontFamily: MONO }}>strain</div>
      </div>
    </div>
  );
}

function WeekScrubber({ C, week, setWeek }) {
  const label = week === 0 ? "This week" : week === -1 ? "Last week" : `${Math.abs(week)} wks ago`;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, background: C.s2, borderRadius: 12, padding: 3 }}>
      <button onClick={() => setWeek(week - 1)} style={{
        width: 26, height: 26, borderRadius: 9, background: "none", border: "none",
        color: C.t2, cursor: "pointer", fontSize: 14,
      }}>‹</button>
      <div style={{ fontSize: 10, color: C.t2, fontFamily: MONO, fontWeight: 700, minWidth: 72, textAlign: "center" }}>{label}</div>
      <button onClick={() => week < 0 && setWeek(week + 1)} style={{
        width: 26, height: 26, borderRadius: 9, background: "none", border: "none",
        color: week < 0 ? C.t2 : C.t4, cursor: week < 0 ? "pointer" : "default", fontSize: 14,
      }}>›</button>
    </div>
  );
}

Object.assign(window, { TodayScreen, TrainScreen, WorkoutRow, WeekScrubber, StrainRing });
