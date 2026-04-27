import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { MealInput } from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";
import { VoiceInput } from "../components/VoiceInput";

interface LogMealModalProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  onAdd: (meal: MealInput) => void;
  prefill?: string;
}

const QUICK: MealInput[] = [
  { name: "Oikos Vanilla Shake", cal: 170, p: 30, c: 8, f: 3.5, tag: "snack" },
  { name: "Kirkland PB Protein Bar", cal: 190, p: 21, c: 22, f: 7, tag: "snack" },
  { name: "Costco chicken bake (half)", cal: 385, p: 31, c: 39, f: 13, tag: "lunch" },
  { name: "Morning shake (half)", cal: 356, p: 26.5, c: 51, f: 8.5, tag: "breakfast" },
  { name: "Rotisserie chicken, 4 oz", cal: 224, p: 26, c: 0, f: 13, tag: "lunch" },
  { name: "Gochujang broth bowl", cal: 380, p: 36, c: 40, f: 5, tag: "dinner" },
];

export function LogMealModal({ C, open, onClose, onAdd, prefill }: LogMealModalProps) {
  const [custom, setCustom] = useState("");

  useEffect(() => {
    if (open && prefill) setCustom(prefill);
    if (!open) setCustom("");
  }, [open, prefill]);

  const handleQuickAdd = (q: MealInput) => {
    onAdd(q);
    onClose();
  };

  const handleCustomSend = () => {
    if (custom.trim()) {
      onAdd({ name: custom, cal: 300, p: 25, c: 30, f: 8, tag: "snack" });
    }
    onClose();
    setCustom("");
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Log a meal" height="78%">
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8 }}>
        Quick add
      </div>
      {QUICK.map((q, i) => (
        <button
          key={i}
          onClick={() => handleQuickAdd(q)}
          style={{
            width: "100%",
            background: C.s,
            border: `1px solid ${C.border}`,
            borderRadius: 14,
            padding: 12,
            marginBottom: 6,
            textAlign: "left",
            cursor: "pointer",
            fontFamily: FONT,
            color: C.t,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              background: C.primaryDim,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.primary,
              fontSize: 16,
              fontWeight: 800,
            }}
          >
            +
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{q.name}</div>
            <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>
              {q.cal} kcal · P{q.p} C{q.c} F{q.f}
            </div>
          </div>
        </button>
      ))}
      <div
        style={{
          fontSize: 11,
          color: C.t3,
          textTransform: "uppercase",
          letterSpacing: ".1em",
          fontWeight: 700,
          marginTop: 14,
          marginBottom: 8,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span style={{ whiteSpace: "nowrap" }}>Describe a meal</span>
        <span style={{ fontSize: 11, color: C.primary, fontFamily: MONO, letterSpacing: ".06em", whiteSpace: "nowrap" }}>
          ● TAP MIC
        </span>
      </div>
      <VoiceInput C={C} value={custom} onChange={setCustom} placeholder='"8 oz chicken, 1/3 cup mashed potatoes…"' minHeight={80} />
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <Btn C={C} full onClick={onClose}>
          Cancel
        </Btn>
        <Btn C={C} primary full onClick={handleCustomSend}>
          Send to coach →
        </Btn>
      </div>
    </Sheet>
  );
}
