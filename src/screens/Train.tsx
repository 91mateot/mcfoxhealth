import { MONO, type Palette } from "../theme";
import type { TodayResponse, Workout, WorkoutsResponse } from "../types";
import { Ring } from "../components/Ring";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { BarRow } from "../components/BarRow";
import { Stat } from "../components/Stat";
import { SectionHead } from "../components/SectionHead";
import { Btn } from "../components/Btn";

interface TrainScreenProps {
  C: Palette;
  today: TodayResponse;
  workouts: WorkoutsResponse;
  onLogWorkout: () => void;
  onOpenWorkout: (w: Workout) => void;
  onOpenWorkoutHistory: () => void;
  week: number;
  setWeek: (n: number) => void;
}

export function TrainScreen({ C, today, workouts, onLogWorkout, onOpenWorkout, onOpenWorkoutHistory, week, setWeek }: TrainScreenProps) {
  const list = workouts.workouts ?? [];
  const weekStrain = today.recoveryWeek.reduce((a, d) => a + (d.strain ?? 0), 0);
  const recent = list.slice(0, 5);
  const weekCal = recent.reduce((a, x) => a + (x.cal ?? 0), 0);
  const weekMin = recent.reduce((a, x) => a + (x.dur ?? 0), 0);
  const last = list[0];

  return (
    <div>
      <SectionHead C={C} kicker="This week" title="Training" right={<WeekScrubber C={C} week={week} setWeek={setWeek} />} />

      <Panel C={C}>
        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          <div style={{ position: "relative", width: 88, height: 88 }}>
            <Ring val={Math.min(weekStrain, 105)} max={105} color={C.warn} trackColor={C.s3} size={88} stroke={6} />
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.warn, fontFamily: MONO, letterSpacing: "-.04em" }}>
                {weekStrain.toFixed(0)}
              </div>
              <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>weekly</div>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>Week strain</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 6 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, fontFamily: MONO, color: C.t }}>{list.length}</div>
                <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>sessions</div>
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, fontFamily: MONO, color: C.t }}>{weekMin}</div>
                <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>min</div>
              </div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, fontFamily: MONO, color: C.t }}>{(weekCal / 1000).toFixed(1)}k</div>
                <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>kcal</div>
              </div>
            </div>
          </div>
        </div>
      </Panel>

      <Panel C={C} title="Strain by day" right={<Chip C={C} color={C.warn}>{weekStrain.toFixed(0)} / 105</Chip>}>
        <BarRow
          C={C}
          items={today.recoveryWeek}
          accessor="strain"
          colorFn={(_it, v) => (v >= 14 ? C.warn : v >= 10 ? C.yellow : C.primary)}
          valueFn={(it) => (it.strain ?? 0).toFixed(0)}
        />
      </Panel>

      {last && (
        <>
          <SectionHead C={C} kicker={last.day} title={`${last.title} recap`} />
          <Panel C={C}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.t, letterSpacing: "-.02em" }}>{last.title}</div>
              <Chip C={C} color={C.warn}>strain {last.strain}</Chip>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6 }}>
              <Stat C={C} label="Duration" value={last.dur} unit="min" />
              <Stat C={C} label="Avg HR" value={last.avgHR} unit="bpm" valueC={C.warn} />
              <Stat C={C} label="Max HR" value={last.maxHR} unit="bpm" />
              <Stat C={C} label="Active kcal" value={last.cal} valueC={C.primary} />
            </div>
            {last.notes && (
              <div style={{ fontSize: 11, color: C.t2, marginTop: 10, lineHeight: 1.5 }}>{last.notes}</div>
            )}
          </Panel>
        </>
      )}

      <SectionHead
        C={C}
        kicker="Log"
        title="Recent sessions"
        right={
          <button
            onClick={onOpenWorkoutHistory}
            style={{
              background: "transparent",
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              padding: "4px 8px",
              fontSize: 11,
              color: C.t2,
              fontFamily: MONO,
              fontWeight: 700,
              cursor: "pointer",
              letterSpacing: ".05em",
            }}
          >
            7d
          </button>
        }
      />
      {list.length === 0 ? (
        <Panel C={C}>
          <div style={{ fontSize: 12, color: C.t3, textAlign: "center", padding: "12px 0" }}>
            No workouts yet. Connect Strava or log one manually.
          </div>
        </Panel>
      ) : (
        <Panel C={C} style={{ padding: 6 }}>
          {list.slice(0, 6).map((x, i) => (
            <WorkoutRow key={i} C={C} w={x} last={i === Math.min(list.length, 6) - 1} onTap={() => onOpenWorkout(x)} />
          ))}
        </Panel>
      )}

      <div style={{ marginTop: 4, marginBottom: 8 }}>
        <Btn C={C} primary full onClick={onLogWorkout}>
          + Log workout
        </Btn>
      </div>
    </div>
  );
}

function WorkoutRow({ C, w, last, onTap }: { C: Palette; w: Workout; last: boolean; onTap: () => void }) {
  const typeCol = (
    {
      Push: C.primary,
      Pull: C.cyan,
      Legs: C.purple,
      Walk: C.t3,
      HIIT: C.warn,
    } as Record<string, string>
  )[w.type] ?? C.t2;
  const liftCount = w.exercises?.length ?? 0;
  return (
    <button
      onClick={onTap}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 10px",
        borderBottom: last ? "none" : `1px solid ${C.border}`,
        width: "100%",
        background: "transparent",
        border: "none",
        borderRadius: 10,
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "inherit",
        color: "inherit",
      }}
    >
      <div style={{ width: 40, textAlign: "center" }}>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, fontWeight: 700 }}>{w.day.toUpperCase()}</div>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>{w.date}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{w.title}</span>
          {liftCount > 0 && (
            <span style={{ fontSize: 10, color: C.primary, fontFamily: MONO, fontWeight: 700, background: C.primary + "20", padding: "2px 6px", borderRadius: 4 }}>
              {liftCount} lift{liftCount === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 1 }}>
          {w.dur}m · avg {w.avgHR} · {w.cal} kcal
        </div>
      </div>
      <div
        style={{
          fontSize: 11,
          color: typeCol,
          fontWeight: 700,
          letterSpacing: ".08em",
          padding: "3px 8px",
          borderRadius: 6,
          background: typeCol + "18",
        }}
      >
        {w.type.toUpperCase()}
      </div>
      <div style={{ textAlign: "right", minWidth: 36 }}>
        <div style={{ fontSize: 14, fontWeight: 700, fontFamily: MONO, color: C.warn, letterSpacing: "-.03em" }}>
          {w.strain}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>strain</div>
      </div>
    </button>
  );
}

function WeekScrubber({ C, week, setWeek }: { C: Palette; week: number; setWeek: (n: number) => void }) {
  const label = week === 0 ? "This week" : week === -1 ? "Last week" : `${Math.abs(week)} wks ago`;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, background: C.s2, borderRadius: 12, padding: 3 }}>
      <button
        onClick={() => setWeek(week - 1)}
        aria-label="Previous week"
        style={{ width: 26, height: 26, borderRadius: 9, background: "none", border: "none", color: C.t2, cursor: "pointer", fontSize: 14 }}
      >
        ‹
      </button>
      <div style={{ fontSize: 11, color: C.t2, fontFamily: MONO, fontWeight: 700, minWidth: 72, textAlign: "center" }}>
        {label}
      </div>
      <button
        onClick={() => week < 0 && setWeek(week + 1)}
        disabled={week >= 0}
        aria-label="Next week"
        style={{
          width: 26,
          height: 26,
          borderRadius: 9,
          background: "none",
          border: "none",
          color: week < 0 ? C.t2 : C.t4,
          cursor: week < 0 ? "pointer" : "default",
          fontSize: 14,
        }}
      >
        ›
      </button>
    </div>
  );
}
