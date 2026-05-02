import { MONO, type Palette } from "../theme";
import type { Workout } from "../types";
import { Sheet } from "../components/Sheet";
import { useWorkouts } from "../api";

interface Props {
  C: Palette;
  open: boolean;
  onClose: () => void;
  onOpenWorkout: (w: Workout) => void;
}

export function WorkoutHistorySheet({ C, open, onClose, onOpenWorkout }: Props) {
  const { data, error, isLoading } = useWorkouts();
  const list = data?.workouts ?? [];

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 6);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const recent = list.filter((w) => w.date >= cutoffStr);

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Workouts · past 7 days" height="92%">
      {error && (
        <div style={{ fontSize: 12, color: C.warn, marginBottom: 12 }}>Couldn't load history.</div>
      )}
      {isLoading && recent.length === 0 && (
        <div
          style={{
            fontSize: 11,
            color: C.t4,
            fontFamily: MONO,
            letterSpacing: ".1em",
            padding: "40px 0",
            textAlign: "center",
          }}
        >
          LOADING…
        </div>
      )}
      {!isLoading && recent.length === 0 && !error && (
        <div style={{ fontSize: 12, color: C.t3, lineHeight: 1.5, padding: "20px 0" }}>
          No workouts logged in the last week. Connect Strava or log one from Train.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {recent.map((w) => (
          <WorkoutRow
            key={(w.strava_id ?? "") + w.date}
            C={C}
            w={w}
            onTap={() => {
              onClose();
              onOpenWorkout(w);
            }}
          />
        ))}
      </div>
    </Sheet>
  );
}

function WorkoutRow({ C, w, onTap }: { C: Palette; w: Workout; onTap: () => void }) {
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
        padding: "10px 12px",
        background: C.s,
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "inherit",
        color: "inherit",
        width: "100%",
      }}
    >
      <div style={{ width: 44, textAlign: "center" }}>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, fontWeight: 700 }}>
          {w.day.toUpperCase()}
        </div>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
          {shortDate(w.date)}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12.5,
            color: C.t,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {w.title}
          </span>
          {liftCount > 0 && (
            <span
              style={{
                fontSize: 10,
                color: C.primary,
                fontFamily: MONO,
                fontWeight: 700,
                background: C.primary + "20",
                padding: "2px 6px",
                borderRadius: 4,
              }}
            >
              {liftCount} lift{liftCount === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2 }}>
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
        <div
          style={{
            fontSize: 14,
            fontWeight: 700,
            fontFamily: MONO,
            color: C.warn,
            letterSpacing: "-.03em",
          }}
        >
          {w.strain}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>strain</div>
      </div>
    </button>
  );
}

function shortDate(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  const [, m, d] = parts.map((p) => parseInt(p, 10));
  return `${m}/${d}`;
}
