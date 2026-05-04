import { useEffect, useState } from "react";
import { FONT, PALETTES, type PaletteKey } from "./theme";
import { TabBar, type Tab } from "./components/TabBar";
import { TodayScreen } from "./screens/Today";
import { TrainScreen } from "./screens/Train";
import { FuelScreen } from "./screens/Fuel";
import { ProgressScreen } from "./screens/Progress";
import { RingDetailSheet, type RingKey } from "./modals/RingDetail";
import { LogMealModal } from "./modals/LogMeal";
import { LogWorkoutModal } from "./modals/LogWorkout";
import { ChatModal } from "./modals/Chat";
import { JournalSheet } from "./modals/Journal";
import { JournalHistorySheet } from "./modals/JournalHistorySheet";
import { MealDetailModal } from "./modals/MealDetail";
import { MealHistorySheet } from "./modals/MealHistorySheet";
import { WorkoutDetailModal } from "./modals/WorkoutDetail";
import { WorkoutHistorySheet } from "./modals/WorkoutHistorySheet";
import { InsightsModal } from "./modals/Insights";
import type { Meal, Workout } from "./types";
import { useToday, useWorkouts, useProgress, useNutrition, logMeal, logWorkout, submitJournal, todayISO, track } from "./api";

type TabId = "today" | "train" | "fuel" | "progress";

const VALID_TABS: readonly TabId[] = ["today", "train", "fuel", "progress"];

export default function App() {
  const [palette, setPalette] = useState<PaletteKey>(() => {
    const saved = localStorage.getItem("mateo-palette") as PaletteKey | null;
    return saved && saved in PALETTES ? saved : "zine";
  });
  const [tab, setTab] = useState<TabId>(() => {
    const saved = localStorage.getItem("mateo-tab");
    return saved && VALID_TABS.includes(saved as TabId) ? (saved as TabId) : "today";
  });
  const [week, setWeek] = useState(0);
  const [sheetRing, setSheetRing] = useState<RingKey | null>(null);
  const [mealOpen, setMealOpen] = useState(false);
  const [mealPrefill, setMealPrefill] = useState("");
  const [workoutOpen, setWorkoutOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatPrefill, setChatPrefill] = useState<string | undefined>();
  const [journalOpen, setJournalOpen] = useState(false);
  const [journalHistoryOpen, setJournalHistoryOpen] = useState(false);
  const [mealDetail, setMealDetail] = useState<Meal | null>(null);
  const [mealHistoryOpen, setMealHistoryOpen] = useState(false);
  const [workoutDetail, setWorkoutDetail] = useState<Workout | null>(null);
  const [workoutHistoryOpen, setWorkoutHistoryOpen] = useState(false);
  const [insightsOpen, setInsightsOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem("mateo-tab", tab);
    track("tab.view", { tab });
  }, [tab]);
  useEffect(() => {
    localStorage.setItem("mateo-palette", palette);
  }, [palette]);
  useEffect(() => {
    track("session.start");
  }, []);

  const C = PALETTES[palette];

  const today = useToday();
  const workouts = useWorkouts();
  const progress = useProgress();
  const nutrition = useNutrition(todayISO());

  const tabs: Tab[] = [
    { id: "today", label: "Today" },
    { id: "train", label: "Train" },
    { id: "fuel", label: "Fuel" },
    { id: "progress", label: "Progress" },
  ];

  const openLogMeal = (prefill?: string) => {
    setMealPrefill(typeof prefill === "string" ? prefill : "");
    setMealOpen(true);
    track("meal.log.open", { prefilled: typeof prefill === "string" && prefill.length > 0 });
  };

  const openChat = (prompt?: string) => {
    setChatPrefill(prompt);
    setChatOpen(true);
    track("chat.open", { prefilled: typeof prompt === "string" && prompt.length > 0 });
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: C.bg,
        color: C.t,
        fontFamily: FONT,
        paddingTop: "calc(12px + env(safe-area-inset-top, 0px))",
        paddingLeft: "max(14px, env(safe-area-inset-left, 0px))",
        paddingRight: "max(14px, env(safe-area-inset-right, 0px))",
        // TabBar is fixed at bottom (~50px), FAB juts 18px above it, plus the
        // home-indicator safe area on newer iPhones (~26px). Add headroom so
        // the last panel on any tab clears the FAB without content clipping.
        paddingBottom: "calc(140px + env(safe-area-inset-bottom, 0px))",
        maxWidth: 520,
        margin: "0 auto",
        position: "relative",
      }}
    >
      {today.error && (
        <ErrorBanner C={C} message="Couldn't load today's data." onRetry={() => today.mutate()} />
      )}

      {today.data && tab === "today" && (
        <TodayScreen
          C={C}
          data={today.data}
          nutrition={nutrition.data}
          onRingTap={(k) => { setSheetRing(k); track("ring.open", { which: k }); }}
          onOpenChat={openChat}
          onLogMeal={() => openLogMeal()}
          onLogWorkout={() => { setWorkoutOpen(true); track("workout.log.open", { source: "today" }); }}
          onOpenJournal={() => { setJournalOpen(true); track("journal.open"); }}
          onOpenJournalHistory={() => { setJournalHistoryOpen(true); track("journal.history.open"); }}
        />
      )}

      {today.data && workouts.data && tab === "train" && (
        <TrainScreen
          C={C}
          today={today.data}
          workouts={workouts.data}
          onLogWorkout={() => { setWorkoutOpen(true); track("workout.log.open", { source: "train" }); }}
          onOpenWorkout={(w) => { setWorkoutDetail(w); track("workout.detail.open"); }}
          onOpenWorkoutHistory={() => { setWorkoutHistoryOpen(true); track("workout.history.open"); }}
          week={week}
          setWeek={setWeek}
        />
      )}

      {today.data && nutrition.data && tab === "fuel" && (
        <FuelScreen
          C={C}
          today={today.data}
          nutrition={nutrition.data}
          onLogMeal={openLogMeal}
          onOpenMeal={(m) => { setMealDetail(m); track("meal.detail.open"); }}
          onOpenMealHistory={() => { setMealHistoryOpen(true); track("meal.history.open"); }}
        />
      )}

      {today.data && progress.data && tab === "progress" && (
        <ProgressScreen
          C={C}
          today={today.data}
          progress={progress.data}
          onOpenInsights={() => { setInsightsOpen(true); track("insights.open"); }}
        />
      )}

      {(!today.data || isLoadingTab(tab, { today, progress, workouts, nutrition })) && (
        <LoadingSkeleton C={C} />
      )}

      <PaletteSwitcher C={C} palette={palette} setPalette={setPalette} />

      <TabBar C={C} tabs={tabs} active={tab} onChange={(id) => setTab(id as TabId)} onFabClick={() => { track("fab.tap"); openChat(); }} />

      <RingDetailSheet C={C} open={sheetRing !== null} which={sheetRing} onClose={() => setSheetRing(null)} today={today.data ?? null} />
      <LogMealModal
        C={C}
        open={mealOpen}
        prefill={mealPrefill}
        onClose={() => setMealOpen(false)}
        onAdd={async (m) => {
          try {
            await logMeal(m);
          } catch (err) {
            console.error("logMeal failed", err);
          }
        }}
      />
      <LogWorkoutModal
        C={C}
        open={workoutOpen}
        onClose={() => setWorkoutOpen(false)}
        onAdd={async ({ type, notes }) => {
          const text = [type, notes].filter((s) => s && s.trim()).join(" — ");
          if (!text) return;
          try {
            await logWorkout(text);
          } catch (err) {
            console.error("logWorkout failed", err);
          }
        }}
      />
      <ChatModal C={C} open={chatOpen} onClose={() => setChatOpen(false)} initialPrompt={chatPrefill} today={today.data} />
      <JournalSheet
        C={C}
        open={journalOpen}
        onClose={() => setJournalOpen(false)}
        todayEntry={today.data?.journal ?? null}
        tagsToday={today.data?.journalTagsToday ?? []}
        onSave={async (data) => {
          try {
            await submitJournal(data);
          } catch (err) {
            console.error("submitJournal failed", err);
          }
        }}
      />
      <JournalHistorySheet
        C={C}
        open={journalHistoryOpen}
        onClose={() => setJournalHistoryOpen(false)}
      />
      {nutrition.data && (
        <MealDetailModal
          C={C}
          open={mealDetail !== null}
          onClose={() => setMealDetail(null)}
          meal={mealDetail}
          date={todayISO()}
          targets={nutrition.data.targets}
        />
      )}
      <WorkoutDetailModal
        C={C}
        open={workoutDetail !== null}
        onClose={() => setWorkoutDetail(null)}
        workout={workoutDetail}
      />
      <MealHistorySheet
        C={C}
        open={mealHistoryOpen}
        onClose={() => setMealHistoryOpen(false)}
      />
      <WorkoutHistorySheet
        C={C}
        open={workoutHistoryOpen}
        onClose={() => setWorkoutHistoryOpen(false)}
        onOpenWorkout={(w) => setWorkoutDetail(w)}
      />
      <InsightsModal C={C} open={insightsOpen} onClose={() => setInsightsOpen(false)} />
    </div>
  );
}

function isLoadingTab(
  tab: TabId,
  data: { today: { data?: unknown }; progress: { data?: unknown }; workouts: { data?: unknown }; nutrition: { data?: unknown } }
): boolean {
  if (tab === "today") return !data.today.data;
  if (tab === "train") return !data.today.data || !data.workouts.data;
  if (tab === "fuel") return !data.today.data || !data.nutrition.data;
  if (tab === "progress") return !data.today.data || !data.progress.data;
  return false;
}

function ErrorBanner({ C, message, onRetry }: { C: ReturnType<typeof getPalette>; message: string; onRetry: () => void }) {
  return (
    <div
      style={{
        background: C.dangerDim,
        border: `1px solid ${C.danger}40`,
        borderRadius: 14,
        padding: 12,
        marginBottom: 10,
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <div style={{ flex: 1, fontSize: 12, color: C.t2 }}>{message}</div>
      <button
        onClick={onRetry}
        style={{
          background: C.danger,
          color: "#0a0a0a",
          border: "none",
          padding: "6px 12px",
          borderRadius: 10,
          fontFamily: "inherit",
          fontSize: 11,
          fontWeight: 700,
          cursor: "pointer",
        }}
      >
        Retry
      </button>
    </div>
  );
}

function LoadingSkeleton({ C }: { C: ReturnType<typeof getPalette> }) {
  return (
    <div style={{ padding: "40px 4px", textAlign: "center" }}>
      <div style={{ fontSize: 12, color: C.t3, fontFamily: "JetBrains Mono, monospace", letterSpacing: ".1em" }}>LOADING…</div>
    </div>
  );
}

function getPalette() {
  return PALETTES.zine;
}

function PaletteSwitcher({ C, palette, setPalette }: { C: ReturnType<typeof getPalette>; palette: PaletteKey; setPalette: (p: PaletteKey) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "fixed", top: "calc(12px + env(safe-area-inset-top, 0px))", right: 14, zIndex: 30 }}>
      <button
        onClick={() => setOpen(!open)}
        aria-label="Change palette"
        style={{
          background: C.s,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          width: 36,
          height: 36,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: C.t2,
        }}
      >
        <div style={{ display: "flex", gap: 2 }}>
          <div style={{ width: 6, height: 6, borderRadius: 3, background: C.primary }} />
          <div style={{ width: 6, height: 6, borderRadius: 3, background: C.warn }} />
          <div style={{ width: 6, height: 6, borderRadius: 3, background: C.cyan }} />
        </div>
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: 44,
            right: 0,
            background: C.s,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            padding: 6,
            minWidth: 180,
            boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
          }}
        >
          {(Object.keys(PALETTES) as PaletteKey[]).map((k) => {
            const p = PALETTES[k];
            const active = palette === k;
            return (
              <button
                key={k}
                onClick={() => {
                  setPalette(k);
                  setOpen(false);
                }}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 10px",
                  background: active ? C.s3 : "transparent",
                  border: "none",
                  borderRadius: 8,
                  color: active ? C.t : C.t2,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  fontSize: 12,
                  fontWeight: active ? 700 : 500,
                  textAlign: "left",
                }}
              >
                <div style={{ display: "flex", gap: 2 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 4, background: p.primary }} />
                  <div style={{ width: 8, height: 8, borderRadius: 4, background: p.warn }} />
                  <div style={{ width: 8, height: 8, borderRadius: 4, background: p.cyan }} />
                </div>
                {p.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
