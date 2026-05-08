import { useMemo, useState } from "react";
import { MONO, type Palette } from "../theme";
import type { TodayResponse, Workout, WorkoutsResponse } from "../types";
import { Ring } from "../components/Ring";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { BarRow } from "../components/BarRow";
import { Stat } from "../components/Stat";
import { SectionHead } from "../components/SectionHead";
import { Btn } from "../components/Btn";
import { todayISO, track } from "../api";

interface TrainScreenProps {
  C: Palette;
  today: TodayResponse;
  workouts: WorkoutsResponse;
  onLogWorkout: () => void;
  onOpenWorkout: (w: Workout) => void;
  onOpenWorkoutHistory: () => void;
}

export function TrainScreen({ C, today, workouts, onLogWorkout, onOpenWorkout, onOpenWorkoutHistory }: TrainScreenProps) {
  const list = workouts.workouts ?? [];
  const weekStrain = today.recoveryWeek.reduce((a, d) => a + (d.strain ?? 0), 0);
  const recent = list.slice(0, 5);
  const weekCal = recent.reduce((a, x) => a + (x.cal ?? 0), 0);
  const weekMin = recent.reduce((a, x) => a + (x.dur ?? 0), 0);
  const last = list[0];

  return (
    <div>
      <SectionHead C={C} kicker="This week" title="Training" right={<Chip C={C}>Live week</Chip>} />

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
        <RecentSessions C={C} list={list} onOpenWorkout={onOpenWorkout} />
      )}

      <div style={{ marginTop: 4, marginBottom: 8 }}>
        <Btn C={C} primary full onClick={onLogWorkout}>
          + Log workout
        </Btn>
      </div>
    </div>
  );
}

function RecentSessions({
  C,
  list,
  onOpenWorkout,
}: {
  C: Palette;
  list: Workout[];
  onOpenWorkout: (w: Workout) => void;
}) {
  const today = todayISO();
  // Group by ISO date, preserving the API's date-desc order. Multi-session
  // days get a single header row; today is always expanded, prior days
  // collapse by default so the tab doesn't fill with weeks of walks.
  const groups = useMemo(() => {
    const byDate = new Map<string, Workout[]>();
    for (const w of list) {
      const arr = byDate.get(w.date) ?? [];
      arr.push(w);
      byDate.set(w.date, arr);
    }
    return Array.from(byDate.entries()).slice(0, 7); // last 7 days max
  }, [list]);

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([today]));
  const toggle = (date: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      track("workout.day.toggle", { date, opened: !prev.has(date) });
      return next;
    });
  };

  return (
    <Panel C={C} style={{ padding: 6 }}>
      {groups.map(([date, items], gi) => {
        const isToday = date === today;
        const open = expanded.has(date);
        const totalMin = items.reduce((a, x) => a + (x.dur ?? 0), 0);
        const totalStrain = items.reduce((a, x) => a + (x.strain ?? 0), 0);
        const headerLabel = isToday ? "Today" : `${items[0].day} ${date.slice(5)}`;
        return (
          <div key={date} style={{ borderBottom: gi === groups.length - 1 ? "none" : `1px solid ${C.border}` }}>
            <button
              onClick={() => toggle(date)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                width: "100%",
                padding: "8px 10px",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                fontFamily: "inherit",
                color: "inherit",
              }}
              aria-expanded={open}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  fontFamily: MONO,
                  fontSize: 10,
                  color: C.t3,
                  transform: open ? "rotate(90deg)" : "none",
                  transition: "transform .12s",
                }}
              >
                ▸
              </span>
              <span style={{ fontSize: 12, fontWeight: 700, color: isToday ? C.t : C.t2, letterSpacing: ".02em" }}>
                {headerLabel}
              </span>
              <span style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>
                · {items.length} {items.length === 1 ? "session" : "sessions"}
              </span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>{totalMin}m</span>
              <span style={{ fontSize: 11, color: C.warn, fontFamily: MONO, fontWeight: 700, minWidth: 30, textAlign: "right" }}>
                {totalStrain.toFixed(1)}
              </span>
            </button>
            {open && (
              <div>
                {items.map((x, i) => (
                  <WorkoutRow
                    key={x.strava_id || `${date}-${i}`}
                    C={C}
                    w={x}
                    last={i === items.length - 1}
                    onTap={() => onOpenWorkout(x)}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </Panel>
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
