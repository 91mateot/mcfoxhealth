import { useState } from "react";
import { type Palette } from "../theme";
import { Sheet } from "../components/Sheet";
import { Chip } from "../components/Chip";
import { Btn } from "../components/Btn";
import { VoiceInput } from "../components/VoiceInput";

interface LogWorkoutModalProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  onAdd: (data: { type: string; notes: string }) => void;
}

const TYPES = ["Push", "Pull", "Legs", "HIIT", "Walk", "Yoga"];

export function LogWorkoutModal({ C, open, onClose, onAdd }: LogWorkoutModalProps) {
  const [type, setType] = useState("Push");
  const [notes, setNotes] = useState("");

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Log a workout" height="72%">
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8 }}>
        Type
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginBottom: 14 }}>
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setType(t)}
            style={{
              background: type === t ? C.primary : C.s,
              color: type === t ? "#0a0a0a" : C.t2,
              border: `1px solid ${type === t ? C.primary : C.border}`,
              borderRadius: 12,
              padding: "11px 8px",
              fontFamily: "inherit",
              fontSize: 12,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8 }}>
        Pulling from Strava
      </div>
      <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.t }}>Most recent activity</div>
          <Chip C={C} color={C.warn}>Strava pending</Chip>
        </div>
        <div style={{ fontSize: 11, color: C.t3, fontFamily: "inherit", marginTop: 6 }}>
          Connect Strava to auto-import recent activities.
        </div>
      </div>
      <div
        style={{
          fontSize: 11,
          color: C.t3,
          textTransform: "uppercase",
          letterSpacing: ".1em",
          fontWeight: 700,
          marginBottom: 8,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span style={{ whiteSpace: "nowrap" }}>Exercises (optional)</span>
        <span style={{ fontSize: 11, color: C.primary, fontFamily: "inherit", letterSpacing: ".06em", whiteSpace: "nowrap" }}>
          ● TAP MIC
        </span>
      </div>
      <VoiceInput
        C={C}
        value={notes}
        onChange={setNotes}
        placeholder='"Bench 4x8 @ 185, OHP 3x8 @ 115, dips 3xBW…"'
        minHeight={90}
      />
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn C={C} full onClick={onClose}>
          Cancel
        </Btn>
        <Btn
          C={C}
          primary
          full
          onClick={() => {
            onAdd({ type, notes });
            onClose();
            setNotes("");
          }}
        >
          Save workout
        </Btn>
      </div>
    </Sheet>
  );
}
