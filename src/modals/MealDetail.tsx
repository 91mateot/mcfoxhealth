import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { EstimateConfidence, Meal, MealPatch, NutritionTargets } from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";
import { Chip } from "../components/Chip";
import { ProgressBar } from "../components/ProgressBar";
import { VoiceInput } from "../components/VoiceInput";
import { addFavorite, deleteMeal, estimateMeal, patchMeal } from "../api";

interface MealDetailProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  meal: Meal | null;
  date: string;
  targets: NutritionTargets;
}

type Mode = "view" | "edit" | "reestimate";

function confidenceColor(C: Palette, conf?: EstimateConfidence): string {
  if (conf === "high") return C.primary;
  if (conf === "medium") return C.yellow;
  return C.warn;
}

export function MealDetailModal({ C, open, onClose, meal, date, targets }: MealDetailProps) {
  const [mode, setMode] = useState<Mode>("view");
  const [edited, setEdited] = useState<{ name: string; cal: number; p: number; c: number; f: number; tag: string } | null>(null);
  const [reestimateText, setReestimateText] = useState("");
  const [busy, setBusy] = useState<"save" | "delete" | "reestimate" | "favorite" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assumptionsOpen, setAssumptionsOpen] = useState(false);
  const [savedFavorite, setSavedFavorite] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMode("view");
    setError(null);
    setBusy(null);
    setAssumptionsOpen(false);
    setSavedFavorite(false);
    if (meal) {
      setEdited({ name: meal.name, cal: meal.cal, p: meal.p, c: meal.c, f: meal.f, tag: meal.tag });
      setReestimateText(meal.originalText ?? meal.name ?? "");
    }
  }, [open, meal]);

  if (!meal || !edited) {
    return <Sheet C={C} open={open} onClose={onClose} />;
  }

  const mealId = String(meal.id);

  const handleSaveEdit = async () => {
    setBusy("save");
    setError(null);
    try {
      const patch: MealPatch = {
        name: edited.name,
        cal: edited.cal,
        p: edited.p,
        c: edited.c,
        f: edited.f,
        tag: edited.tag,
      };
      await patchMeal(date, mealId, patch);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Delete "${meal.name.slice(0, 60)}"?`)) return;
    setBusy("delete");
    setError(null);
    try {
      await deleteMeal(date, mealId);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setBusy(null);
    }
  };

  const handleReestimate = async () => {
    const text = reestimateText.trim();
    if (!text) return;
    setBusy("reestimate");
    setError(null);
    try {
      const est = await estimateMeal(text);
      await patchMeal(date, mealId, {
        name: est.name,
        cal: est.cal,
        p: est.p,
        c: est.c,
        f: est.f,
        tag: est.tag,
        original_text: text,
        assumptions: est.assumptions,
        confidence: est.confidence,
        source_url: est.sourceUrl,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-estimate failed.");
    } finally {
      setBusy(null);
    }
  };

  const handleSaveFavorite = async () => {
    setBusy("favorite");
    setError(null);
    try {
      await addFavorite({
        name: meal.name.slice(0, 80),
        cal: meal.cal,
        p: meal.p,
        c: meal.c,
        f: meal.f,
        tag: meal.tag || "snack",
      });
      setSavedFavorite(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save to favorites failed.");
    } finally {
      setBusy(null);
    }
  };

  const shareOf = (val: number, goal: number) => (goal > 0 ? Math.min(100, (val / goal) * 100) : 0);

  return (
    <Sheet C={C} open={open} onClose={onClose} title={meal.time ? `${meal.time} · ${titleCase(meal.tag) || "Meal"}` : "Meal"} height="88%">
      {mode === "view" && (
        <>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.t, marginBottom: 10, lineHeight: 1.35, whiteSpace: "pre-wrap" }}>
            {meal.name}
          </div>

          {meal.confidence && (
            <div style={{ marginBottom: 10, display: "flex", gap: 6, alignItems: "center" }}>
              <Chip C={C} color={confidenceColor(C, meal.confidence)}>
                {meal.confidence} confidence
              </Chip>
              {meal.source === "known_foods" && <Chip C={C}>known food</Chip>}
              {meal.source === "llm" && <Chip C={C}>AI estimate</Chip>}
            </div>
          )}

          <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
            <MacroRow C={C} label="Calories" val={meal.cal} goal={targets.cal} color={C.primary} unit="kcal" share={shareOf(meal.cal, targets.cal)} />
            <MacroRow C={C} label="Protein" val={meal.p} goal={targets.p} color={C.primary} unit="g" share={shareOf(meal.p, targets.p)} />
            <MacroRow C={C} label="Carbs" val={meal.c} goal={targets.c} color={C.yellow} unit="g" share={shareOf(meal.c, targets.c)} />
            <MacroRow C={C} label="Fat" val={meal.f} goal={targets.f} color={C.purple} unit="g" share={shareOf(meal.f, targets.f)} last />
          </div>

          {meal.waterOz !== undefined && meal.waterOz > 0 && (
            <div style={{ background: C.s, border: `1px solid ${C.cyan}40`, borderRadius: 14, padding: "10px 12px", marginBottom: 10, fontSize: 12, color: C.t2, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: C.cyan, fontSize: 14 }}>💧</span>
              <span>Logged <strong style={{ color: C.cyan }}>{roundUnit(meal.waterOz)} oz</strong> to hydration.</span>
            </div>
          )}

          {meal.caffeineMg !== undefined && meal.caffeineMg > 0 && (
            <div style={{ background: C.s, border: `1px solid ${C.warn}40`, borderRadius: 14, padding: "10px 12px", marginBottom: 10, fontSize: 12, color: C.t2, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: C.warn, fontSize: 14 }}>☕</span>
              <span>Contains <strong style={{ color: C.warn }}>{Math.round(meal.caffeineMg)} mg</strong> caffeine.</span>
            </div>
          )}

          {meal.ingredients && meal.ingredients.length > 0 && (
            <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8 }}>
                Ingredients ({meal.ingredients.length})
              </div>
              {meal.ingredients.map((ing, i) => {
                const totalCal = meal.ingredients!.reduce((s, x) => s + x.cal, 0) || meal.cal || 1;
                const pct = Math.round((ing.cal / totalCal) * 100);
                return (
                  <div key={i} style={{ padding: "8px 0", borderTop: i === 0 ? "none" : `1px solid ${C.border}` }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600 }}>{ing.name}</div>
                        {ing.portion && <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{ing.portion}</div>}
                      </div>
                      <div style={{ textAlign: "right", minWidth: 90 }}>
                        <div style={{ fontSize: 13, fontFamily: MONO, color: C.t, fontWeight: 700 }}>
                          {roundUnit(ing.cal)} <span style={{ color: C.t4, fontWeight: 500, fontSize: 11 }}>· {pct}%</span>
                        </div>
                        <div style={{ fontSize: 11, fontFamily: MONO, color: C.t4, marginTop: 1 }}>
                          P{roundUnit(ing.p)} C{roundUnit(ing.c)} F{roundUnit(ing.f)}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {meal.assumptions && meal.assumptions.length > 0 && (
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
                <span>Assumptions ({meal.assumptions.length})</span>
                <span style={{ color: C.t4 }}>{assumptionsOpen ? "▾" : "▸"}</span>
              </button>
              {assumptionsOpen && (
                <ul style={{ margin: "8px 0 0", padding: "0 0 0 18px", fontSize: 12, color: C.t2, lineHeight: 1.55 }}>
                  {meal.assumptions.map((a, i) => (
                    <li key={i} style={{ marginBottom: 4 }}>{a}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {meal.sourceUrl && (
            <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginBottom: 10, wordBreak: "break-all" }}>
              source: {meal.sourceUrl}
            </div>
          )}

          {error && (
            <div style={{ fontSize: 11, color: C.warn, marginBottom: 8, fontFamily: MONO }}>{error}</div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
            <Btn C={C} onClick={() => setMode("edit")}>Edit macros</Btn>
            <Btn C={C} onClick={() => setMode("reestimate")}>Re-estimate</Btn>
            <Btn C={C} onClick={handleSaveFavorite} disabled={busy === "favorite" || savedFavorite}>
              {savedFavorite ? "Saved ✓" : busy === "favorite" ? "Saving…" : "Save to favorites"}
            </Btn>
            <Btn C={C} onClick={handleDelete} disabled={busy === "delete"}>
              {busy === "delete" ? "Deleting…" : "Delete meal"}
            </Btn>
          </div>
          <Btn C={C} full onClick={onClose}>Close</Btn>
        </>
      )}

      {mode === "edit" && (
        <>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8 }}>
            Edit macros
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
          {error && <div style={{ fontSize: 11, color: C.warn, marginBottom: 8, fontFamily: MONO }}>{error}</div>}
          <div style={{ display: "flex", gap: 8 }}>
            <Btn C={C} full onClick={() => setMode("view")}>← Back</Btn>
            <Btn C={C} primary full onClick={handleSaveEdit} disabled={busy === "save"}>
              {busy === "save" ? "Saving…" : "Save changes"}
            </Btn>
          </div>
        </>
      )}

      {mode === "reestimate" && (
        <>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8 }}>
            Re-estimate with new text
          </div>
          <VoiceInput
            C={C}
            value={reestimateText}
            onChange={setReestimateText}
            placeholder="Edit the description or paste a recipe link"
            minHeight={120}
          />
          {error && <div style={{ fontSize: 11, color: C.warn, marginTop: 8, fontFamily: MONO }}>{error}</div>}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn C={C} full onClick={() => setMode("view")}>← Back</Btn>
            <Btn C={C} primary full onClick={handleReestimate} disabled={busy === "reestimate"}>
              {busy === "reestimate" ? "Re-estimating…" : "Re-estimate →"}
            </Btn>
          </div>
        </>
      )}
    </Sheet>
  );
}

function titleCase(s: string): string {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function MacroRow({ C, label, val, goal, color, unit, share, last }: { C: Palette; label: string; val: number; goal: number; color: string; unit: string; share: number; last?: boolean }) {
  return (
    <div style={{ marginBottom: last ? 0 : 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 3 }}>
        <span style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>{label}</span>
        <span style={{ fontSize: 12, fontFamily: MONO, fontWeight: 700, color, whiteSpace: "nowrap" }}>
          {roundUnit(val)}{unit} <span style={{ color: C.t4, fontWeight: 500 }}>· {share.toFixed(0)}% of {goal}{unit}</span>
        </span>
      </div>
      <ProgressBar C={C} val={val} max={goal} color={color} height={4} />
    </div>
  );
}

function roundUnit(v: number): string {
  if (!Number.isFinite(v)) return "0";
  if (Math.abs(v - Math.round(v)) < 0.05) return String(Math.round(v));
  return v.toFixed(1);
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
