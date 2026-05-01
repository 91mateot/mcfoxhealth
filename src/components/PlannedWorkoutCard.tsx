import { useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { PlannedWorkout } from "../types";
import { Panel } from "../components/Panel";
import { Btn } from "../components/Btn";
import { refreshPlannedWorkout } from "../api";

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

export function PlannedWorkoutCard({ C, planned, onSwap }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  if (!planned) return null;

  const { main, activation, matched } = planned;
  const typeLabel = TYPE_LABELS[main.type] || main.type;
  const intensityLabel = INTENSITY_LABELS[main.intensity] || main.intensity;

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

  const handleSwap = () => {
    onSwap(`I'd rather not do ${typeLabel.toLowerCase()} today — what else works?`);
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
          <Btn C={C} onClick={handleSwap} style={{ flex: 1 }}>
            Swap
          </Btn>
          <Btn C={C} onClick={handleRefresh} disabled={refreshing} style={{ flex: 1 }}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </Btn>
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
