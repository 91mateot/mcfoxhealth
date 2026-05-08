import { useEffect, useRef, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { MealInput, MealEstimate, EstimateConfidence } from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";
import { Chip } from "../components/Chip";
import { VoiceInput } from "../components/VoiceInput";
import { BarcodeScanner } from "../components/BarcodeScanner";
import { estimateFromPhoto, estimateMeal, lookupBarcode, useFavorites } from "../api";
import { compressImage } from "../lib/images";

interface LogMealModalProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  onAdd: (meal: MealInput) => void | Promise<void>;
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

function mealSaveError(e: unknown): string {
  const detail = e instanceof Error && e.message ? ` (${e.message})` : "";
  return `Couldn't save meal${detail}. Try again.`;
}

export function LogMealModal({ C, open, onClose, onAdd, prefill }: LogMealModalProps) {
  const [step, setStep] = useState<Step>("describe");
  const [custom, setCustom] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<MealEstimate | null>(null);
  const [edited, setEdited] = useState<{ name: string; cal: number; p: number; c: number; f: number; tag: string; time: string } | null>(null);
  const [assumptionsOpen, setAssumptionsOpen] = useState(false);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scanLookupBusy, setScanLookupBusy] = useState(false);
  const [scanMissMsg, setScanMissMsg] = useState<string | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const favoritesResp = useFavorites();
  const favorites = favoritesResp.data?.favorites ?? [];

  useEffect(() => {
    if (open) {
      setStep("describe");
      setLoading(false);
      setSaving(false);
      setError(null);
      setEstimate(null);
      setEdited(null);
      setAssumptionsOpen(false);
      setScannerOpen(false);
      setScanLookupBusy(false);
      setScanMissMsg(null);
      setPhotoBusy(false);
      setCustom(prefill ?? "");
    } else {
      setCustom("");
    }
  }, [open, prefill]);

  const saveMeal = async (payload: MealInput) => {
    setSaving(true);
    setError(null);
    try {
      await onAdd(payload);
      onClose();
    } catch (e) {
      setError(mealSaveError(e));
    } finally {
      setSaving(false);
    }
  };

  const handleQuickAdd = async (q: MealInput) => {
    await saveMeal({ ...q, time: clientTime() });
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
        time: est.time ?? clientTime(),
      });
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Estimator unavailable. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleScanDetected = async (code: string) => {
    setScannerOpen(false);
    setScanLookupBusy(true);
    setScanMissMsg(null);
    setError(null);
    try {
      const est = await lookupBarcode(code);
      if (!est) {
        setScanMissMsg(
          `Barcode ${code} wasn't in OpenFoodFacts. Describe it below and I'll estimate.`,
        );
        // Seed the Describe textarea with a helpful placeholder if empty.
        if (!custom.trim()) {
          setCustom(`Scanned ${code} — `);
        }
        return;
      }
      setEstimate(est);
      setEdited({
        name: est.name,
        cal: est.cal,
        p: est.p,
        c: est.c,
        f: est.f,
        tag: est.tag,
        time: est.time ?? clientTime(),
      });
      setStep("review");
    } catch (e) {
      setScanMissMsg(e instanceof Error ? e.message : "Lookup failed.");
    } finally {
      setScanLookupBusy(false);
    }
  };

  const handleLabelPhotoPicked = async (file: File | null) => {
    if (!file) return;
    setPhotoBusy(true);
    setScanMissMsg(null);
    setError(null);
    try {
      // Labels need legibility — use a larger max edge than chat photos.
      const img = await compressImage(file, 1280, 0.75);
      const est = await estimateFromPhoto(img.base64, img.mediaType);
      setEstimate(est);
      setEdited({
        name: est.name,
        cal: est.cal,
        p: est.p,
        c: est.c,
        f: est.f,
        tag: est.tag,
        time: est.time ?? clientTime(),
      });
      setStep("review");
    } catch (e) {
      setScanMissMsg(
        e instanceof Error
          ? `Couldn't read that photo (${e.message}). Try a clearer shot, or describe it below.`
          : "Couldn't read that photo. Try a clearer shot, or describe it below.",
      );
    } finally {
      setPhotoBusy(false);
      // Reset the input so picking the same file twice still fires onChange.
      if (photoInputRef.current) photoInputRef.current.value = "";
    }
  };

  const handleSave = async () => {
    if (!edited) return;
    const payload: MealInput = { ...edited };
    if (estimate) {
      payload.original_text = custom.trim() || estimate.name;
      payload.assumptions = estimate.assumptions;
      payload.confidence = estimate.confidence;
      payload.source = estimate.source;
      payload.sourceUrl = estimate.sourceUrl;
      if (estimate.ingredients && estimate.ingredients.length > 0) {
        payload.ingredients = estimate.ingredients;
      }
      if (estimate.water_oz && estimate.water_oz > 0) {
        payload.water_oz = estimate.water_oz;
      }
      if (estimate.caffeine_mg && estimate.caffeine_mg > 0) {
        payload.caffeine_mg = estimate.caffeine_mg;
      }
    }
    await saveMeal(payload);
  };

  const handleBack = () => {
    setStep("describe");
    setError(null);
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Log a meal" height="82%">
      {step === "describe" && (
        <>
          {/* Describe-a-meal is the primary path — up top so tapping the FAB
              puts the input within thumb reach. Scan/photo/favorites follow. */}
          <div
            style={{
              fontSize: 11,
              color: C.t3,
              textTransform: "uppercase",
              letterSpacing: ".1em",
              fontWeight: 700,
              marginTop: 6,
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
          <div style={{ display: "flex", gap: 8, marginTop: 10, marginBottom: 14 }}>
            <Btn C={C} full onClick={onClose}>
              Cancel
            </Btn>
            <Btn C={C} primary full onClick={handleEstimate} disabled={loading || saving}>
              {loading ? "Estimating…" : "Send to nutrition coach →"}
            </Btn>
          </div>

          <button
            onClick={() => {
              setScanMissMsg(null);
              setScannerOpen(true);
            }}
            disabled={scanLookupBusy}
            style={{
              width: "100%",
              background: C.primaryDim,
              border: `1px solid ${C.primary}55`,
              borderRadius: 14,
              padding: 14,
              marginBottom: 10,
              textAlign: "left",
              cursor: scanLookupBusy ? "default" : "pointer",
              fontFamily: FONT,
              color: C.t,
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: 10,
                background: C.primary,
                color: "#0a0a0a",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 6v12M6 6v12M9 6v12M12 6v12M15 6v12M18 6v12M21 6v12" />
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>
                {scanLookupBusy ? "Looking up…" : "Scan barcode"}
              </div>
              <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, marginTop: 2 }}>
                exact per-serving macros from the label
              </div>
            </div>
          </button>

          {/* Hidden file input — the Photo of label button below triggers it. */}
          <input
            ref={photoInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => handleLabelPhotoPicked(e.target.files?.[0] ?? null)}
            style={{ display: "none" }}
          />
          <button
            onClick={() => photoInputRef.current?.click()}
            disabled={photoBusy}
            style={{
              width: "100%",
              background: C.primaryDim,
              border: `1px solid ${C.primary}55`,
              borderRadius: 14,
              padding: 14,
              marginBottom: 10,
              textAlign: "left",
              cursor: photoBusy ? "default" : "pointer",
              fontFamily: FONT,
              color: C.t,
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: 10,
                background: C.primary,
                color: "#0a0a0a",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>
                {photoBusy ? "Reading label…" : "Photo of label"}
              </div>
              <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, marginTop: 2 }}>
                snap the nutrition panel or product name
              </div>
            </div>
          </button>

          {scanMissMsg && (
            <div
              style={{
                background: C.s,
                border: `1px solid ${C.warn}40`,
                borderRadius: 12,
                padding: "10px 12px",
                marginTop: 4,
                marginBottom: 10,
                fontSize: 11.5,
                color: C.t2,
                lineHeight: 1.5,
              }}
            >
              {scanMissMsg}
            </div>
          )}

          {favorites.length > 0 && (
            <>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
                <span>Your favorites</span>
                <span style={{ color: C.primary, fontSize: 10 }}>★</span>
              </div>
              {favorites.map((f) => (
                <button
                  key={f.id}
                  onClick={() => handleQuickAdd({ name: f.name, cal: f.cal, p: f.p, c: f.c, f: f.f, tag: f.tag })}
                  disabled={saving}
                  style={{
                    width: "100%",
                    background: C.s,
                    border: `1px solid ${C.border}`,
                    borderRadius: 14,
                    padding: 12,
                    marginBottom: 6,
                    textAlign: "left",
                    cursor: saving ? "default" : "pointer",
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
                    ★
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</div>
                    <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>
                      {Math.round(f.cal)} kcal · P{Math.round(f.p)} C{Math.round(f.c)} F{Math.round(f.f)}
                    </div>
                  </div>
                </button>
              ))}
            </>
          )}
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: favorites.length > 0 ? 14 : 6, marginBottom: 8 }}>
            Quick add
          </div>
          {QUICK.map((q, i) => (
            <button
              key={i}
              onClick={() => handleQuickAdd(q)}
              disabled={saving}
              style={{
                width: "100%",
                background: C.s,
                border: `1px solid ${C.border}`,
                borderRadius: 14,
                padding: 12,
                marginBottom: 6,
                textAlign: "left",
                cursor: saving ? "default" : "pointer",
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
        </>
      )}

      {step === "review" && estimate && edited && (
        <>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span>{
              estimate.source === "barcode"
                ? "Scanned product"
                : estimate.source === "label_photo"
                ? "Photo of label"
                : "Nutrition coach estimate"
            }</span>
            <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {estimate.source === "barcode" && <Chip C={C} color={C.primary}>Scanned ✓</Chip>}
              {estimate.source === "label_photo" && <Chip C={C} color={C.primary}>Photo ✓</Chip>}
              <Chip C={C} color={confidenceColor(C, estimate.confidence)}>
                {estimate.confidence}
              </Chip>
            </span>
          </div>

          <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
            <EditField C={C} label="Name" value={edited.name} onChange={(v) => setEdited({ ...edited, name: v })} />
            <div style={{ marginTop: 10 }}>
              <EditTime C={C} label={estimate.time ? "Time (parsed from your text)" : "Time"} value={edited.time} onChange={(v) => setEdited({ ...edited, time: v })} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
              <EditNum C={C} label="Calories" value={edited.cal} onChange={(v) => setEdited({ ...edited, cal: v })} unit="kcal" color={C.primary} />
              <EditNum C={C} label="Protein" value={edited.p} onChange={(v) => setEdited({ ...edited, p: v })} unit="g" color={C.primary} />
              <EditNum C={C} label="Carbs" value={edited.c} onChange={(v) => setEdited({ ...edited, c: v })} unit="g" color={C.yellow} />
              <EditNum C={C} label="Fat" value={edited.f} onChange={(v) => setEdited({ ...edited, f: v })} unit="g" color={C.purple} />
            </div>
          </div>

          {estimate.water_oz && estimate.water_oz > 0 && (
            <div style={{ background: C.s, border: `1px solid ${C.cyan}40`, borderRadius: 14, padding: "10px 12px", marginBottom: 10, fontSize: 12, color: C.t2, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: C.cyan, fontSize: 14 }}>💧</span>
              <span>Will also log <strong style={{ color: C.cyan }}>{estimate.water_oz} oz</strong> to today's hydration.</span>
            </div>
          )}

          {estimate.caffeine_mg && estimate.caffeine_mg > 0 && (
            <div style={{ background: C.s, border: `1px solid ${C.warn}40`, borderRadius: 14, padding: "10px 12px", marginBottom: 10, fontSize: 12, color: C.t2, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: C.warn, fontSize: 14 }}>☕</span>
              <span>Contains <strong style={{ color: C.warn }}>{Math.round(estimate.caffeine_mg)} mg</strong> caffeine.</span>
            </div>
          )}

          {estimate.ingredients && estimate.ingredients.length > 1 && (
            <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>
                Ingredients ({estimate.ingredients.length})
              </div>
              {estimate.ingredients.map((ing, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "4px 0", borderTop: i === 0 ? "none" : `1px solid ${C.border}` }}>
                  <div style={{ flex: 1, minWidth: 0, marginRight: 8 }}>
                    <div style={{ fontSize: 12, color: C.t, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ing.name}</div>
                    {ing.portion && <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO }}>{ing.portion}</div>}
                  </div>
                  <div style={{ fontSize: 11, fontFamily: MONO, color: C.t3, whiteSpace: "nowrap" }}>
                    {Math.round(ing.cal)} · P{Math.round(ing.p)} C{Math.round(ing.c)} F{Math.round(ing.f)}
                  </div>
                </div>
              ))}
            </div>
          )}

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

          {error && (
            <div style={{ fontSize: 11, color: C.warn, marginTop: 8, fontFamily: MONO }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Btn C={C} full onClick={handleBack}>
              ← Back
            </Btn>
            <Btn C={C} primary full onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "Save meal"}
            </Btn>
          </div>
        </>
      )}

      <BarcodeScanner
        C={C}
        open={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onDetected={handleScanDetected}
      />
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

function EditTime({ C, label, value, onChange }: { C: Palette; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: C.t4, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 4 }}>
        {label}
      </div>
      <input
        type="time"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%",
          background: C.bg,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: "8px 10px",
          color: C.t,
          fontFamily: MONO,
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
