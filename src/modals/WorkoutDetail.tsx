import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { MuscleGroup, Workout, WorkoutExercise } from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";
import { Chip } from "../components/Chip";
import { VoiceInput } from "../components/VoiceInput";
import { annotateWorkout, regenerateWorkoutFeedback } from "../api";

interface WorkoutDetailProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  workout: Workout | null;
}

type Mode = "view" | "annotate";

const MUSCLE_COLORS: Record<MuscleGroup, string | undefined> = {
  chest: undefined,
  back: undefined,
  shoulders: undefined,
  arms: undefined,
  legs: undefined,
  glutes: undefined,
  core: undefined,
  cardio: undefined,
  mobility: undefined,
  other: undefined,
};

export function WorkoutDetailModal({ C, open, onClose, workout }: WorkoutDetailProps) {
  const [mode, setMode] = useState<Mode>("view");
  const [annotateText, setAnnotateText] = useState("");
  const [busy, setBusy] = useState(false);
  const [regenBusy, setRegenBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode("view");
    setError(null);
    setBusy(false);
    setRegenBusy(false);
    setAnnotateText(workout?.originalText ?? "");
  }, [open, workout]);

  if (!workout) return <Sheet C={C} open={open} onClose={onClose} />;

  const exercises = workout.exercises ?? [];
  const cardio = workout.cardioIntervals ?? [];
  const hasStructure = exercises.length > 0 || cardio.length > 0;

  const handleAnnotate = async () => {
    const text = annotateText.trim();
    if (!text) return;
    const workoutId = workout.strava_id;
    if (!workoutId) {
      setError("No workout id available.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await annotateWorkout(workout.date, workoutId, text);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Annotate failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleRegenerateFeedback = async () => {
    const workoutId = workout.strava_id;
    if (!workoutId) return;
    setRegenBusy(true);
    setError(null);
    try {
      await regenerateWorkoutFeedback(workout.date, workoutId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Regenerate failed.");
    } finally {
      setRegenBusy(false);
    }
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title={`${workout.day} · ${workout.title}`} height="90%">
      {mode === "view" && (
        <>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            <Chip C={C} color={C.warn}>
              strain {workout.strain}
            </Chip>
            <Chip C={C}>
              {workout.dur}m
            </Chip>
            {workout.avgHR > 0 && <Chip C={C}>avg HR {workout.avgHR}</Chip>}
            {workout.cal > 0 && <Chip C={C}>{workout.cal} kcal</Chip>}
            {workout.source === "manual" && <Chip C={C} color={C.cyan}>manual</Chip>}
            {workout.annotatedAt && <Chip C={C} color={C.primary}>annotated</Chip>}
          </div>

          {workout.coachFeedback && (
            <div
              style={{
                background: `linear-gradient(180deg, ${C.primary}12 0%, ${C.s} 60%)`,
                border: `1px solid ${C.primary}40`,
                borderRadius: 14,
                padding: 14,
                marginBottom: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
                <div style={{ fontSize: 11, color: C.primary, textTransform: "uppercase", letterSpacing: ".14em", fontWeight: 800 }}>
                  Coach debrief
                </div>
                <button
                  onClick={handleRegenerateFeedback}
                  disabled={regenBusy}
                  style={{
                    background: "transparent",
                    border: `1px solid ${C.border}`,
                    borderRadius: 8,
                    color: C.t3,
                    fontSize: 10,
                    fontFamily: MONO,
                    fontWeight: 700,
                    padding: "3px 8px",
                    cursor: regenBusy ? "default" : "pointer",
                    letterSpacing: ".06em",
                  }}
                  title="Regenerate with the latest history + readiness"
                >
                  {regenBusy ? "…" : "↻ regenerate"}
                </button>
              </div>
              <div style={{ fontSize: 13, color: C.t, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
                {workout.coachFeedback}
              </div>
              {workout.coachFeedbackAt && (
                <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginTop: 8 }}>
                  generated {formatTs(workout.coachFeedbackAt)}
                </div>
              )}
            </div>
          )}

          {exercises.length > 0 && (
            <>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 6 }}>
                Exercises ({exercises.length})
              </div>
              <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 4, marginBottom: 10 }}>
                {exercises.map((ex, i) => (
                  <ExerciseRow key={i} C={C} ex={ex} last={i === exercises.length - 1} />
                ))}
              </div>
            </>
          )}

          {cardio.length > 0 && (
            <>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>
                Cardio intervals ({cardio.length})
              </div>
              <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 10, marginBottom: 10 }}>
                {cardio.map((c, i) => (
                  <div key={i} style={{ padding: "6px 0", borderTop: i === 0 ? "none" : `1px solid ${C.border}` }}>
                    <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600 }}>
                      {c.name}
                      {c.duration_min && <span style={{ color: C.t4, fontFamily: MONO, fontWeight: 500, marginLeft: 6 }}>{c.duration_min}m</span>}
                    </div>
                    {Object.keys(c.params || {}).length > 0 && (
                      <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2 }}>
                        {Object.entries(c.params).map(([k, v]) => `${k}=${v}`).join(" · ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {workout.sessionNotes && (
            <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>
                Session notes
              </div>
              <div style={{ fontSize: 12.5, color: C.t2, lineHeight: 1.5 }}>{workout.sessionNotes}</div>
            </div>
          )}

          {!hasStructure && (
            <div style={{ background: C.s, border: `1px dashed ${C.border}`, borderRadius: 14, padding: 16, marginBottom: 10, textAlign: "center" }}>
              <div style={{ fontSize: 12.5, color: C.t2, lineHeight: 1.5 }}>
                No lift details for this session yet.
              </div>
              <div style={{ fontSize: 11, color: C.t4, marginTop: 4, lineHeight: 1.5 }}>
                Tap Annotate to paste your notes — sets, reps, weight, supersets, cardio.
              </div>
            </div>
          )}

          {error && <div style={{ fontSize: 11, color: C.warn, marginBottom: 8, fontFamily: MONO }}>{error}</div>}

          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <Btn C={C} primary full onClick={() => setMode("annotate")}>
              {hasStructure ? "Re-annotate" : "Annotate"}
            </Btn>
          </div>
          <Btn C={C} full onClick={onClose}>Close</Btn>
        </>
      )}

      {mode === "annotate" && (
        <>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8 }}>
            Paste your workout notes
          </div>
          <div style={{ fontSize: 11, color: C.t4, lineHeight: 1.55, marginBottom: 10 }}>
            Free-form. The AI handles progressive sets ("90, 140, 140"), ramps ("80 to 100 by 10"),
            supersets (indented lines), cardio circuits, and notes about soreness or how you felt.
          </div>
          <VoiceInput
            C={C}
            value={annotateText}
            onChange={setAnnotateText}
            placeholder="- Seated row: 90x10, 140x10 twice&#10;   - superset with plank for 30s&#10;- Lat pulldown: 90, 140, 190&#10;..."
            minHeight={220}
          />
          {error && <div style={{ fontSize: 11, color: C.warn, marginTop: 8, fontFamily: MONO }}>{error}</div>}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn C={C} full onClick={() => setMode("view")}>← Back</Btn>
            <Btn C={C} primary full onClick={handleAnnotate} disabled={busy || !annotateText.trim()}>
              {busy ? "Parsing…" : "Annotate →"}
            </Btn>
          </div>
        </>
      )}
    </Sheet>
  );
}

function ExerciseRow({ C, ex, last }: { C: Palette; ex: WorkoutExercise; last: boolean }) {
  const topWeight = ex.top_weight ?? Math.max(0, ...ex.sets.filter((s) => !s.warmup).map((s) => s.weight));
  const prKinds = ex.pr
    ? Object.entries(ex.pr)
        .filter(([, v]) => !!v)
        .map(([k]) => k)
    : [];

  return (
    <div style={{ padding: "10px 8px", borderTop: last ? "none" : `1px solid ${C.border}` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, color: C.t, fontWeight: 700, flex: 1, minWidth: 0 }}>
          {ex.name}
        </div>
        {ex.muscle_group && (
          <Chip C={C} color={MUSCLE_COLORS[ex.muscle_group] ?? undefined}>
            {ex.muscle_group}
          </Chip>
        )}
        {prKinds.length > 0 && (
          <Chip C={C} color={C.primary}>
            PR: {prKinds.join(" · ")}
          </Chip>
        )}
      </div>
      {ex.superset_with && (
        <div style={{ fontSize: 10, color: C.cyan, fontFamily: MONO, fontWeight: 700, letterSpacing: ".05em", marginBottom: 4 }}>
          ↔ superset: {ex.superset_with.replace(/_/g, " ")}
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(70px, 1fr))", gap: 4, marginBottom: ex.note ? 4 : 0 }}>
        {ex.sets.map((s, i) => (
          <div
            key={i}
            style={{
              background: s.warmup ? C.bg : C.s2,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              padding: "5px 6px",
              textAlign: "center",
              fontFamily: MONO,
            }}
            title={s.warmup ? "warmup" : undefined}
          >
            <div style={{ fontSize: 12, color: s.warmup ? C.t4 : C.t, fontWeight: 700, lineHeight: 1.1 }}>
              {s.weight > 0 ? `${s.weight}` : "–"}
              {s.weight > 0 && <span style={{ fontSize: 9, color: C.t4, marginLeft: 1 }}>lb</span>}
            </div>
            <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.1 }}>
              {s.duration_sec ? `${s.duration_sec}s` : `× ${s.reps}`}
            </div>
          </div>
        ))}
      </div>
      {ex.e1rm && ex.e1rm > 0 && (
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginTop: 4 }}>
          e1RM ≈ {ex.e1rm}lb (top set: {topWeight})
        </div>
      )}
      {ex.note && (
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.4, marginTop: 4, fontStyle: "italic" }}>{ex.note}</div>
      )}
    </div>
  );
}

// Silence unused-var lint (color map kept as future hook for per-MG theming).
void MUSCLE_COLORS;

void FONT;

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMin = Math.round((now.getTime() - d.getTime()) / 60000);
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return d.toLocaleDateString();
  } catch {
    return iso;
  }
}
