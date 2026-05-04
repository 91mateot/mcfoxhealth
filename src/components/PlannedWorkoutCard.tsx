import { useEffect, useState, type ReactNode } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { PlannedWorkout } from "../types";
import { Panel } from "../components/Panel";
import { Btn } from "../components/Btn";
import { markRestDay, refreshPlannedWorkout, submitFeedback, todayISO } from "../api";

interface Props {
  C: Palette;
  planned: PlannedWorkout | null | undefined;
  onSwap: (prefill: string) => void;
}

const TYPE_LABELS: Record<string, string> = {
  push: "Push",
  pull: "Pull",
  legs: "Legs",
  run: "Run",
  hiit: "HIIT",
  pilates: "Pilates",
  pickleball: "Pickleball",
  walk: "Walk",
  mobility: "Mobility",
  sport_prep: "Sport prep",
  rest: "Active recovery",
};

const INTENSITY_LABELS: Record<string, string> = {
  light: "light",
  moderate: "moderate",
  hard: "hard",
};

interface ThumbButtonProps {
  C: Palette;
  active: boolean;
  dim?: boolean;
  label: string;
  onClick: () => void;
  children: ReactNode;
}

function ThumbButton({ C, active, dim, label, onClick, children }: ThumbButtonProps) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      style={{
        background: active ? C.s2 : "transparent",
        border: `1px solid ${active ? C.primary : C.border}`,
        borderRadius: 14,
        width: 28,
        height: 24,
        padding: 0,
        fontSize: 12,
        lineHeight: 1,
        cursor: "pointer",
        opacity: dim ? 0.4 : 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {children}
    </button>
  );
}

export function PlannedWorkoutCard({ C, planned, onSwap }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [resting, setResting] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState("");

  const targetId = planned ? `${todayISO()}#${planned.generatedAt}` : "";

  // Reset local thumbs state whenever the proposal identity changes (Refresh
  // or nightly regeneration) so the user can rate the new plan.
  useEffect(() => {
    setFeedback(null);
    setNoteOpen(false);
    setNoteText("");
  }, [targetId]);

  if (!planned) return null;

  const { main, activation, matched } = planned;
  const typeLabel = TYPE_LABELS[main.type] || main.type;
  const intensityLabel = INTENSITY_LABELS[main.intensity] || main.intensity;
  const isRestDay = planned.restOverride || main.type === "rest";

  const accent = matched
    ? C.primary
    : main.type === "rest"
    ? C.cyan
    : C.primary;
  const accentDim = matched ? C.primaryDim : main.type === "rest" ? C.cyanDim : C.primaryDim;

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await refreshPlannedWorkout();
    } catch (err) {
      console.error("refreshPlannedWorkout failed", err);
    } finally {
      setRefreshing(false);
    }
  };

  const handleRestDay = async () => {
    if (resting || isRestDay) return;
    setResting(true);
    try {
      await markRestDay();
    } catch (err) {
      console.error("markRestDay failed", err);
    } finally {
      setResting(false);
    }
  };

  const handleSwap = () => {
    onSwap(`I'd rather not do ${typeLabel.toLowerCase()} today — what else works?`);
  };

  const handleThumb = async (signal: "up" | "down") => {
    const cleared = feedback === signal;
    const next = cleared ? null : signal;
    const prev = feedback;
    setFeedback(next);

    if (signal === "down" && !cleared) {
      setNoteOpen(true);
      setNoteText("");
    } else if (noteOpen) {
      setNoteOpen(false);
      setNoteText("");
    }

    if (cleared) return;
    try {
      await submitFeedback(signal, "proposal", targetId);
    } catch {
      setFeedback(prev);
    }
  };

  const sendNote = async () => {
    const note = noteText.trim();
    setNoteOpen(false);
    setNoteText("");
    if (!note) return;
    try {
      await submitFeedback("down", "proposal", targetId, note);
    } catch {
      // Thumbs-down signal already landed in handleThumb; swallow note failure.
    }
  };

  return (
    <Panel
      C={C}
      style={{
        background: matched ? C.s : `linear-gradient(180deg, ${C.s}, ${accentDim} 260%)`,
        borderColor: matched ? C.border : accent + "30",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 11, color: accent, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
            {matched ? "Today · trained ✓" : "Today's workout"}
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.t, marginTop: 3, letterSpacing: "-.01em" }}>
            {matched ? "Nice — logged" : `${typeLabel} · ${main.durationMin}m · ${intensityLabel}`}
          </div>
        </div>
        {planned.phase && !matched && (
          <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>
            PHASE {planned.phase}
          </div>
        )}
      </div>

      {!matched && main.reason && (
        <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.5, marginBottom: 10 }}>
          {main.reason}
        </div>
      )}

      {!matched && main.focusLifts && main.focusLifts.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>
            Focus lifts
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {main.focusLifts.map((fl, i) => {
              const tagColor = fl.tag === "stalled" ? C.warn : fl.tag === "volume behind" ? C.cyan : C.t3;
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 10px",
                    background: C.s2,
                    border: `1px solid ${C.border}`,
                    borderRadius: 10,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: C.t, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {fl.name}
                    </div>
                    <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 1 }}>
                      {fl.muscleGroup}
                    </div>
                  </div>
                  <div
                    style={{
                      fontSize: 10,
                      color: tagColor,
                      background: tagColor + "15",
                      border: `1px solid ${tagColor}30`,
                      padding: "3px 7px",
                      borderRadius: 10,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: ".04em",
                      whiteSpace: "nowrap",
                      flexShrink: 0,
                    }}
                  >
                    {fl.tag}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!matched && activation && (
        <div
          style={{
            background: C.s2,
            border: `1px solid ${C.border}`,
            borderRadius: 14,
            padding: "10px 12px",
            marginBottom: 10,
          }}
        >
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "transparent",
              border: "none",
              padding: 0,
              color: C.t,
              cursor: "pointer",
              fontFamily: FONT,
              textAlign: "left",
            }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>
                Activation · {activation.durationMin}m · {activation.location}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.t, marginTop: 2 }}>
                {activation.name}
              </div>
            </div>
            <div style={{ fontSize: 12, color: C.t3, marginLeft: 10, fontFamily: MONO, flexShrink: 0 }}>
              {expanded ? "−" : `+${activation.exercises.length}`}
            </div>
          </button>
          {expanded && (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              {activation.exercises.map((e, i) => (
                <div key={i} style={{ fontSize: 12, color: C.t2, lineHeight: 1.45 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ color: C.t, fontWeight: 600, flex: 1 }}>{e.name}</span>
                    <span style={{ color: C.t3, fontFamily: MONO, flexShrink: 0 }}>
                      {e.sets ? `${e.sets}×` : ""}{e.reps || ""}
                    </span>
                  </div>
                  {e.cue && <div style={{ fontSize: 11, color: C.t3, marginTop: 2 }}>{e.cue}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {!matched && (
        <div style={{ display: "flex", gap: 6 }}>
          {!isRestDay && (
            <Btn C={C} onClick={handleSwap} style={{ flex: 1 }}>
              Swap
            </Btn>
          )}
          <Btn C={C} onClick={handleRefresh} disabled={refreshing} style={{ flex: 1 }}>
            {refreshing ? "Refreshing…" : isRestDay ? "Train instead" : "Refresh"}
          </Btn>
          {!isRestDay && (
            <Btn C={C} onClick={handleRestDay} disabled={resting} style={{ flex: 1 }}>
              {resting ? "…" : "Rest day"}
            </Btn>
          )}
        </div>
      )}

      {!matched && !isRestDay && (
        <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 10, fontFamily: MONO, color: C.t4, letterSpacing: ".1em" }}>
            PLAN FIT
          </span>
          <ThumbButton
            C={C}
            active={feedback === "up"}
            dim={feedback !== null && feedback !== "up"}
            label="Good fit"
            onClick={() => handleThumb("up")}
          >
            👍
          </ThumbButton>
          <ThumbButton
            C={C}
            active={feedback === "down"}
            dim={feedback !== null && feedback !== "down"}
            label="Not a fit"
            onClick={() => handleThumb("down")}
          >
            👎
          </ThumbButton>
          {feedback && (
            <span style={{ fontSize: 10, fontFamily: MONO, color: C.t4 }}>
              {feedback === "up" ? "thanks" : "noted"}
            </span>
          )}
        </div>
      )}

      {noteOpen && (
        <div
          style={{
            marginTop: 8,
            background: C.s2,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            padding: "8px 10px",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <label style={{ fontSize: 11, fontFamily: MONO, color: C.t3 }}>
            What was off? (optional)
          </label>
          <input
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") sendNote();
              if (e.key === "Escape") {
                setNoteOpen(false);
                setNoteText("");
              }
            }}
            placeholder="Too intense, wrong muscle group, bad timing…"
            autoFocus
            style={{
              background: "transparent",
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              padding: "6px 8px",
              color: C.t,
              fontFamily: FONT,
              fontSize: 12,
              outline: "none",
            }}
          />
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button
              onClick={() => {
                setNoteOpen(false);
                setNoteText("");
              }}
              style={{
                background: "transparent",
                border: `1px solid ${C.border}`,
                color: C.t2,
                padding: "4px 10px",
                borderRadius: 10,
                fontFamily: FONT,
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Skip
            </button>
            <button
              onClick={sendNote}
              style={{
                background: C.primary,
                border: "none",
                color: "#0a0a0a",
                padding: "4px 12px",
                borderRadius: 10,
                fontFamily: FONT,
                fontSize: 11,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Send
            </button>
          </div>
        </div>
      )}

      {matched && (
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>
          Log captured · planned was {typeLabel.toLowerCase()} {main.durationMin}m
        </div>
      )}
    </Panel>
  );
}
