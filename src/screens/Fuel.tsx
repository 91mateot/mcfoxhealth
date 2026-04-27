import { MONO, type Palette } from "../theme";
import type { Meal, NutritionResponse, TodayResponse } from "../types";
import { Ring } from "../components/Ring";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { BarRow } from "../components/BarRow";
import { ProgressBar } from "../components/ProgressBar";
import { SectionHead } from "../components/SectionHead";
import { Btn } from "../components/Btn";
import { HydrationPanel } from "../components/HydrationPanel";

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

      {/* Hydration */}
      <HydrationPanel C={C} water={today.water} waterGoal={today.waterGoal} />

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
        <>
          <SectionHead C={C} kicker="Stack" title="Supplements" />
          <Panel C={C} style={{ padding: 8 }}>
            {supplements.map((s, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "9px 8px",
                  borderBottom: i === supplements.length - 1 ? "none" : `1px solid ${C.border}`,
                }}
              >
                <div
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: 6,
                    flexShrink: 0,
                    background: s.taken ? C.primary : "transparent",
                    border: s.taken ? "none" : `1.5px solid ${C.s4}`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: C.bg,
                    fontSize: 12,
                    fontWeight: 800,
                  }}
                >
                  {s.taken ? "✓" : ""}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: C.t, fontWeight: 600 }}>{s.name}</div>
                  <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>{s.dose} · {s.timing}</div>
                </div>
              </div>
            ))}
          </Panel>
        </>
      )}

      <div style={{ margin: "4px 0 8px" }}>
        <Btn C={C} primary full onClick={() => onLogMeal()}>
          + Log meal
        </Btn>
      </div>
    </div>
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
      <div style={{ width: 42 }}>
        <div style={{ fontSize: 11, color: planned ? C.t4 : C.t3, fontFamily: MONO, fontWeight: 600 }}>{m.time}</div>
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
