import { useState } from "react";
import { MONO, type Palette } from "../theme";
import type { Correlation, Meal, NutritionResponse, Supplement, TodayResponse } from "../types";
import { Ring } from "../components/Ring";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { BarRow } from "../components/BarRow";
import { ProgressBar } from "../components/ProgressBar";
import { SectionHead } from "../components/SectionHead";
import { Btn } from "../components/Btn";
import { HydrationPanel } from "../components/HydrationPanel";
import { CaffeinePanel } from "../components/CaffeinePanel";
import { HydrationDetail } from "../modals/HydrationDetail";
import { formatMealTime, submitJournal, todayISO, useInsights } from "../api";

interface FuelScreenProps {
  C: Palette;
  today: TodayResponse;
  nutrition: NutritionResponse;
  onLogMeal: (prefill?: string) => void;
  onOpenMeal?: (m: Meal) => void;
}

export function FuelScreen({ C, today, nutrition, onLogMeal, onOpenMeal }: FuelScreenProps) {
  const T = nutrition.targets;
  const eaten = nutrition.totals;
  const planned = nutrition.mealPlanned ?? today.mealPlanned;
  const proj = planned
    ? { cal: eaten.cal + planned.cal, p: eaten.p + planned.p, c: eaten.c + planned.c, f: eaten.f + planned.f }
    : eaten;
  const proteinGap = Math.max(0, T.p - proj.p);
  const supplements = nutrition.supplements ?? today.supplements ?? [];
  const [hydrationOpen, setHydrationOpen] = useState(false);

  return (
    <div>
      <SectionHead C={C} kicker="Today" title="Fuel" right={<Chip C={C} color={C.primary}>{Math.round(eaten.cal)} / {T.cal} kcal</Chip>} />

      {/* Calorie ring + macros */}
      <Panel C={C}>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <div style={{ position: "relative", width: 96, height: 96, flexShrink: 0 }}>
            <Ring val={eaten.cal} max={T.cal} color={C.primary} trackColor={C.s3} size={96} stroke={6.5} />
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: C.primary, fontFamily: MONO, letterSpacing: "-.04em" }}>
                {Math.round((eaten.cal / T.cal) * 100)}%
              </div>
              <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>of {T.cal}</div>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <MacroLine C={C} label="Protein" val={Math.round(eaten.p)} goal={T.p} color={C.primary} unit="g" />
            <MacroLine C={C} label="Carbs" val={Math.round(eaten.c)} goal={T.c} color={C.yellow} unit="g" />
            <MacroLine C={C} label="Fat" val={Math.round(eaten.f)} goal={T.f} color={C.purple} unit="g" />
          </div>
        </div>
      </Panel>

      {/* Quick entry — keep this near the top so logging a meal is a one-tap
          action on Fuel open. A second full-width button lives further down
          for people who've already scrolled past the hydration/timeline. */}
      <div style={{ marginTop: 4, marginBottom: 10 }}>
        <Btn C={C} primary full onClick={() => onLogMeal()}>
          + Log meal
        </Btn>
      </div>

      {/* Projection */}
      {planned && (
        <Panel C={C} style={{ background: C.primaryDim, borderColor: C.primary + "40" }}>
          <div style={{ fontSize: 11, color: C.primary, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
            If you eat the planned dinner
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 6 }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: C.t, fontFamily: MONO, letterSpacing: "-.03em" }}>
              {Math.round(proj.cal)}
            </div>
            <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
              kcal · {Math.round(proj.p)}g P · {Math.round(proj.c)}g C · {Math.round(proj.f)}g F
            </div>
          </div>
          {proteinGap > 0 && (
            <div style={{ fontSize: 11, color: C.t2, marginTop: 8, lineHeight: 1.5 }}>
              You'd still be <span style={{ color: C.warn, fontWeight: 700 }}>{proteinGap}g short on protein</span>. One Oikos (30g protein · 170 kcal) gets you over your {T.p}g goal.
            </div>
          )}
          <div style={{ marginTop: 10, display: "flex", gap: 6 }}>
            <Btn C={C} primary small onClick={() => onLogMeal("Oikos")}>
              + Add Oikos
            </Btn>
            <Btn C={C} small onClick={() => onLogMeal("Protein bar")}>
              + Protein bar
            </Btn>
          </div>
        </Panel>
      )}

      {/* Hydration + Caffeine */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <HydrationPanel C={C} water={today.water} waterGoal={today.waterGoal} onOpenDetail={() => setHydrationOpen(true)} />
        <CaffeinePanel C={C} mg={today.caffeineMg ?? 0} goal={today.caffeineGoal ?? 400} />
      </div>
      <HydrationDetail
        C={C}
        open={hydrationOpen}
        onClose={() => setHydrationOpen(false)}
        date={nutrition.date || todayISO()}
        water={today.water}
        waterGoal={today.waterGoal}
        waterLogs={nutrition.waterLogs ?? []}
        meals={nutrition.meals}
      />

      {/* Today's meals */}
      <SectionHead C={C} kicker="Logged" title="Today's meals" right={<Chip C={C}>{nutrition.meals.length} items</Chip>} />
      {nutrition.meals.length === 0 ? (
        <Panel C={C}>
          <div style={{ fontSize: 12, color: C.t3, textAlign: "center", padding: "12px 0" }}>
            No meals logged yet. Tap below to add one.
          </div>
        </Panel>
      ) : (
        <Panel C={C} style={{ padding: 6 }}>
          {nutrition.meals.map((m, i) => (
            <MealRow
              key={String(m.id)}
              C={C}
              m={m}
              last={i === nutrition.meals.length - 1}
              onClick={onOpenMeal ? () => onOpenMeal(m) : undefined}
            />
          ))}
        </Panel>
      )}
      {planned && (
        <Panel C={C} style={{ padding: 6, opacity: 0.7, borderStyle: "dashed", borderColor: C.s3 }}>
          <MealRow C={C} m={planned} last planned />
        </Panel>
      )}

      {/* 7-day protein */}
      <SectionHead C={C} kicker="Trend" title="7-day protein" right={<Chip C={C} color={C.primary}>target {T.p}g</Chip>} />
      <Panel C={C}>
        <BarRow
          C={C}
          items={today.proteinWeek}
          accessor="p"
          height={56}
          colorFn={(_it, v) => (v >= T.p ? C.primary : v >= 100 ? C.yellow : C.danger)}
          valueFn={(it) => it.p + "g"}
        />
      </Panel>

      {/* Supplements */}
      {supplements.length > 0 && (
        <SupplementsSection C={C} today={today} supplements={supplements} />
      )}

      <div style={{ margin: "4px 0 8px" }}>
        <Btn C={C} primary full onClick={() => onLogMeal()}>
          + Log meal
        </Btn>
      </div>
    </div>
  );
}

function SupplementsSection({
  C,
  today,
  supplements,
}: {
  C: Palette;
  today: TodayResponse;
  supplements: Supplement[];
}) {
  // Tag toggle = slot:"tags_only" write. Updates `tags` on today's journal
  // row WITHOUT setting submitted_at, so the Morning check-in card stays
  // "pending" until Mateo actually does the full entry. journalTagsToday is
  // the raw tag list on today's row, server-authoritative and populated
  // whether or not the morning entry has been submitted.
  const journalTags = today.journalTagsToday ?? [];
  const [pendingTag, setPendingTag] = useState<string | null>(null);
  const insights = useInsights(true);

  const toggle = async (tag: string) => {
    if (pendingTag) return;
    setPendingTag(tag);
    const has = journalTags.includes(tag);
    const next = has ? journalTags.filter((t) => t !== tag) : [...journalTags, tag];
    try {
      await submitJournal({ slot: "tags_only", tags: next });
    } catch (err) {
      console.error("supplement toggle failed", err);
    } finally {
      setPendingTag(null);
    }
  };

  // Inline correlation hints: pick the strongest signal per supplement tag
  // from the learned journal correlations. Uses the "high" confidence bar
  // so we only surface claims the correlation engine is willing to stand
  // behind, matching the Insights modal's filtering.
  const hints: Record<string, { label: string; direction: "positive" | "negative" }> = {};
  const byTag: Record<string, Correlation[]> = {};
  for (const c of insights.data?.journal ?? []) {
    if (c.confidence !== "high") continue;
    (byTag[c.tag] ||= []).push(c);
  }
  for (const [tag, rows] of Object.entries(byTag)) {
    // Rank by absolute effect magnitude, show the biggest.
    rows.sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect));
    const top = rows[0];
    if (!top) continue;
    const arrow = top.direction === "positive" ? "↑" : "↓";
    const magnitude = Math.abs(top.effect).toFixed(1);
    hints[tag] = {
      label: `${arrow} ${top.metric} ${magnitude}${top.unit}`,
      direction: top.direction,
    };
  }

  return (
    <>
      <SectionHead C={C} kicker="Stack" title="Supplements" />
      <Panel C={C} style={{ padding: 10 }}>
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, marginBottom: 8 }}>
          Tap what you took today.
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {supplements.map((s) => {
            const taken = s.taken;
            const isPending = pendingTag === s.tag;
            const hint = hints[s.tag];
            return (
              <button
                key={s.tag || s.name}
                onClick={() => s.tag && toggle(s.tag)}
                disabled={!s.tag || isPending}
                aria-pressed={taken}
                style={{
                  fontSize: 11.5,
                  color: taken ? C.primary : C.t2,
                  background: taken ? C.primary + "18" : C.s2,
                  border: `1px solid ${taken ? C.primary + "60" : C.border}`,
                  padding: "7px 11px",
                  borderRadius: 18,
                  fontWeight: 600,
                  cursor: s.tag ? "pointer" : "default",
                  fontFamily: "inherit",
                  transition: "all .15s ease",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  opacity: isPending ? 0.6 : 1,
                }}
              >
                <span
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 4,
                    background: taken ? C.primary : "transparent",
                    border: taken ? "none" : `1.5px solid ${C.s4}`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: C.bg,
                    fontSize: 10,
                    fontWeight: 800,
                    flexShrink: 0,
                  }}
                >
                  {taken ? "✓" : ""}
                </span>
                <span>{s.name}</span>
                {s.dose && (
                  <span style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginLeft: 2 }}>{s.dose}</span>
                )}
                {hint && (
                  <span
                    style={{
                      fontSize: 9.5,
                      color: hint.direction === "positive" ? C.primary : C.warn,
                      fontFamily: MONO,
                      marginLeft: 4,
                      padding: "1px 5px",
                      borderRadius: 8,
                      background: (hint.direction === "positive" ? C.primary : C.warn) + "15",
                    }}
                  >
                    {hint.label}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </Panel>
    </>
  );
}

function MacroLine({ C, label, val, goal, color, unit }: { C: Palette; label: string; val: number; goal: number; color: string; unit: string }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 3 }}>
        <span style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>{label}</span>
        <span style={{ fontSize: 11, fontFamily: MONO, fontWeight: 700, color, whiteSpace: "nowrap" }}>
          {val}
          {unit} <span style={{ color: C.t4, fontWeight: 500 }}>/ {goal}{unit}</span>
        </span>
      </div>
      <ProgressBar C={C} val={val} max={goal} color={color} height={4} />
    </div>
  );
}

function MealRow({ C, m, last, planned, onClick }: { C: Palette; m: Meal; last: boolean; planned?: boolean; onClick?: () => void }) {
  const tappable = !!onClick && !planned;
  const content = (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 10px",
        borderBottom: last ? "none" : `1px solid ${C.border}`,
      }}
    >
      <div style={{ width: 52 }}>
        <div style={{ fontSize: 11, color: planned ? C.t4 : C.t3, fontFamily: MONO, fontWeight: 600 }}>{formatMealTime(m.time)}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12.5,
            color: planned ? C.t3 : C.t,
            fontWeight: 600,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {m.name}
          {planned && " · planned"}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{m.portion}</div>
      </div>
      <div style={{ textAlign: "right", minWidth: 50 }}>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: MONO, color: planned ? C.t3 : C.t }}>
          {Math.round(m.cal)}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>
          P{Math.round(m.p)} C{Math.round(m.c)} F{Math.round(m.f)}
        </div>
      </div>
      {tappable && <span style={{ color: C.t4, fontSize: 14, marginLeft: 4 }}>›</span>}
    </div>
  );
  if (!tappable) return content;
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        padding: 0,
        background: "transparent",
        border: "none",
        textAlign: "left",
        cursor: "pointer",
        fontFamily: "inherit",
        color: "inherit",
      }}
    >
      {content}
    </button>
  );
}
