import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { MealInput, MealEstimate, EstimateConfidence } from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";
import { Chip } from "../components/Chip";
import { VoiceInput } from "../components/VoiceInput";
import { estimateMeal } from "../api";

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

type Step = "describe" | "review";

function clientTime(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function confidenceColor(C: Palette, conf: EstimateConfidence): string {
  if (conf === "high") return C.primary;
  if (conf === "medium") return C.yellow;
  return C.warn;
}

export function LogMealModal({ C, open, onClose, onAdd, prefill }: LogMealModalProps) {
  const [step, setStep] = useState<Step>("describe");
  const [custom, setCustom] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<MealEstimate | null>(null);
  const [edited, setEdited] = useState<{ name: string; cal: number; p: number; c: number; f: number; tag: string } | null>(null);
  const [assumptionsOpen, setAssumptionsOpen] = useState(false);

  useEffect(() => {
    if (open) {
      setStep("describe");
      setLoading(false);
      setError(null);
      setEstimate(null);
      setEdited(null);
      setAssumptionsOpen(false);
      setCustom(prefill ?? "");
    } else {
      setCustom("");
    }
  }, [open, prefill]);

  const handleQuickAdd = (q: MealInput) => {
    onAdd({ ...q, time: clientTime() });
    onClose();
  };

  const handleEstimate = async () => {
    const text = custom.trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    try {
      const est = await estimateMeal(text);
      setEstimate(est);
      setEdited({
        name: est.name,
        cal: est.cal,
        p: est.p,
        c: est.c,
        f: est.f,
        tag: est.tag,
      });
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Estimator unavailable. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = () => {
    if (!edited) return;
    onAdd({ ...edited, time: clientTime() });
    onClose();
  };

  const handleBack = () => {
    setStep("describe");
    setError(null);
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Log a meal" height="82%">
      {step === "describe" && (
        <>
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
          <VoiceInput
            C={C}
            value={custom}
            onChange={setCustom}
            placeholder='"8 oz chicken, 1/3 cup mashed potatoes… or paste a recipe link"'
            minHeight={80}
          />
          {error && (
            <div style={{ fontSize: 11, color: C.warn, marginTop: 8, fontFamily: MONO }}>
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn C={C} full onClick={onClose}>
              Cancel
            </Btn>
            <Btn C={C} primary full onClick={handleEstimate}>
              {loading ? "Estimating…" : "Send to nutrition coach →"}
            </Btn>
          </div>
        </>
      )}

      {step === "review" && estimate && edited && (
        <>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Nutrition coach estimate</span>
            <Chip C={C} color={confidenceColor(C, estimate.confidence)}>
              {estimate.confidence}
            </Chip>
          </div>

          <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
            <EditField C={C} label="Name" value={edited.name} onChange={(v) => setEdited({ ...edited, name: v })} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
              <EditNum C={C} label="Calories" value={edited.cal} onChange={(v) => setEdited({ ...edited, cal: v })} unit="kcal" color={C.primary} />
              <EditNum C={C} label="Protein" value={edited.p} onChange={(v) => setEdited({ ...edited, p: v })} unit="g" color={C.primary} />
              <EditNum C={C} label="Carbs" value={edited.c} onChange={(v) => setEdited({ ...edited, c: v })} unit="g" color={C.yellow} />
              <EditNum C={C} label="Fat" value={edited.f} onChange={(v) => setEdited({ ...edited, f: v })} unit="g" color={C.purple} />
            </div>
          </div>

          {estimate.assumptions.length > 0 && (
            <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
              <button
                onClick={() => setAssumptionsOpen(!assumptionsOpen)}
                style={{
                  width: "100%",
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  color: C.t3,
                  fontFamily: FONT,
                  fontSize: 11,
                  textTransform: "uppercase",
                  letterSpacing: ".1em",
                  fontWeight: 700,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  cursor: "pointer",
                }}
              >
                <span>Assumptions ({estimate.assumptions.length})</span>
                <span style={{ color: C.t4 }}>{assumptionsOpen ? "▾" : "▸"}</span>
              </button>
              {assumptionsOpen && (
                <ul style={{ margin: "8px 0 0", padding: "0 0 0 18px", fontSize: 12, color: C.t2, lineHeight: 1.55 }}>
                  {estimate.assumptions.map((a, i) => (
                    <li key={i} style={{ marginBottom: 4 }}>{a}</li>
                  ))}
                </ul>
              )}
              {estimate.sourceUrl && (
                <div style={{ marginTop: 8, fontSize: 11, color: C.t4, fontFamily: MONO, wordBreak: "break-all" }}>
                  source: {estimate.sourceUrl}
                </div>
              )}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn C={C} full onClick={handleBack}>
              ← Back
            </Btn>
            <Btn C={C} primary full onClick={handleSave}>
              Save meal
            </Btn>
          </div>
        </>
      )}
    </Sheet>
  );
}

function EditField({ C, label, value, onChange }: { C: Palette; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: C.t4, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 4 }}>
        {label}
      </div>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%",
          background: C.bg,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: "8px 10px",
          color: C.t,
          fontFamily: FONT,
          fontSize: 13,
          fontWeight: 600,
          outline: "none",
          boxSizing: "border-box",
        }}
      />
    </div>
  );
}

function EditNum({ C, label, value, onChange, unit, color }: { C: Palette; label: string; value: number; onChange: (v: number) => void; unit: string; color: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: C.t4, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: "0 10px" }}>
        <input
          type="number"
          inputMode="decimal"
          value={Number.isFinite(value) ? value : 0}
          onChange={(e) => onChange(Number(e.target.value) || 0)}
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            padding: "8px 0",
            color,
            fontFamily: MONO,
            fontSize: 15,
            fontWeight: 700,
            outline: "none",
            minWidth: 0,
          }}
        />
        <span style={{ color: C.t4, fontFamily: MONO, fontSize: 11, marginLeft: 4 }}>{unit}</span>
      </div>
    </div>
  );
}
