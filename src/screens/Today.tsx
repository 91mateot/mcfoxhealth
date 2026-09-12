import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import {
  JOURNAL_TAGS,
  type EveningEntry,
  type JournalNote,
  type MorningEntry,
  type NutritionResponse,
  type TodayResponse,
} from "../types";
import { BigRing } from "../components/BigRing";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { Sparkline } from "../components/Sparkline";
import { ProgressBar } from "../components/ProgressBar";
import { Btn } from "../components/Btn";
import { HydrationPanel } from "../components/HydrationPanel";
import { CaffeinePanel } from "../components/CaffeinePanel";
import { PlannedWorkoutCard } from "../components/PlannedWorkoutCard";
import { NoteComposer, type NoteDraft } from "../components/NoteComposer";
import { HydrationDetail } from "../modals/HydrationDetail";
import { refreshAppData, submitJournal, todayISO } from "../api";

interface TodayScreenProps {
  C: Palette;
  data: TodayResponse;
  nutrition?: NutritionResponse;
  onRingTap: (which: "recovery" | "strain" | "sleep" | "primer") => void;
  onOpenChat: (prompt?: string) => void;
  onLogMeal: () => void;
  onLogWorkout: () => void;
  onOpenJournal: () => void;
  onOpenJournalHistory: () => void;
}

export function TodayScreen({ C, data, nutrition, onRingTap, onOpenChat, onLogMeal, onLogWorkout, onOpenJournal, onOpenJournalHistory }: TodayScreenProps) {
  const [hydrationOpen, setHydrationOpen] = useState(false);
  const need = data.sleepNeedTonight;
  const recoveryAvailable = data.recovery != null && data.recoveryZone != null;
  const sleepAvailable = data.sleep.score != null && data.sleep.qualityFlag !== "truncated";
  const zone = recoveryAvailable ? data.recoveryZone : null;
  const zoneColor = zone === "green" ? C.primary : zone === "yellow" ? C.yellow : zone === "red" ? C.danger : C.t3;
  const zoneLabel = zone === "green" ? "Recovered" : zone === "yellow" ? "Moderate" : zone === "red" ? "Depleted" : "Data pending";
  const zoneHeadline =
    zone === "green"
      ? "Train today."
      : zone === "yellow"
      ? "Train smart."
      : zone === "red"
      ? "Active recovery."
      : "Recovery unavailable.";
  const hour = new Date().getHours();
  const greeting =
    hour < 5 ? "Late night" : hour < 12 ? "Morning" : hour < 17 ? "Afternoon" : "Evening";

  return (
    <div>
      {/* Greeting */}
      <div style={{ padding: "8px 4px 14px" }}>
        <div style={{ fontSize: 12, color: C.t3, fontFamily: MONO, letterSpacing: ".04em" }}>
          {data.dateFull.toUpperCase()} · PACIFIC BEACH
        </div>
        <div style={{ fontSize: 26, fontWeight: 700, color: C.t, letterSpacing: "-.02em", marginTop: 4, lineHeight: 1.15 }}>
          {greeting}, Mateo.
          <br />
          <span style={{ color: zoneColor }}>{zoneLabel}.</span> {zoneHeadline}
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <Chip C={C} color={zoneColor}>● {zone?.toUpperCase() ?? "NO DATA"}</Chip>
          <Chip C={C} color={C.t3}>RECOMP</Chip>
          <FreshnessIndicator C={C} updatedAt={data.updatedAt} />
        </div>
      </div>

      {/* Journal check-in — pending prompt OR logged summary */}
      <JournalCard C={C} data={data} onOpen={onOpenJournal} onOpenHistory={onOpenJournalHistory} />


      {/* Hero rings */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 7, marginBottom: 10 }}>
        <BigRing
          C={C}
          val={data.recovery ?? 0}
          max={100}
          color={zoneColor}
          label="Recovery"
          display={data.recovery ?? "—"}
          unit={recoveryAvailable ? "%" : "unavailable"}
          tag={zone === "green" ? "Ready" : zone === "yellow" ? "Mod" : zone === "red" ? "Rest" : "No data"}
          tagC={zoneColor}
          pending={!recoveryAvailable}
          onClick={() => onRingTap("recovery")}
        />
        <StrainRing C={C} data={data} onClick={() => onRingTap("strain")} />
        <BigRing
          C={C}
          val={sleepAvailable ? data.sleep.score ?? 0 : 0}
          max={100}
          color={data.sleep.qualityFlag === "truncated" ? C.t3 : C.cyan}
          label="Sleep"
          display={sleepAvailable ? data.sleep.score ?? "—" : "—"}
          unit={data.sleep.qualityFlag === "truncated" ? "incomplete" : sleepAvailable ? `${data.sleep.hours}h ${data.sleep.minutes}m` : "unavailable"}
          tag={
            data.sleep.qualityFlag === "truncated"
              ? "Data"
              : !sleepAvailable
              ? "No data"
              : data.sleep.score != null && data.sleep.score >= 80
              ? "Solid"
              : data.sleep.score != null && data.sleep.score >= 60
              ? "Ok"
              : "Low"
          }
          tagC={data.sleep.qualityFlag === "truncated" ? C.t3 : C.cyan}
          pending={!sleepAvailable}
          onClick={() => onRingTap("sleep")}
        />
      </div>

      {/* Sleep Bank — rolling 7-night surplus/deficit. Advisory only. */}
      {data.sleepBank && <SleepBankCard C={C} bank={data.sleepBank} bedtimeBy={need?.bedtimeBy} />}

      {/* Today's workout card */}
      {data.plannedWorkout && (
        <PlannedWorkoutCard C={C} planned={data.plannedWorkout} onSwap={onOpenChat} />
      )}

      {/* Plain-English summary */}
      <Panel C={C} style={{ background: C.s, padding: "12px 14px" }}>
        <div style={{ fontSize: 11, color: zoneColor, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
          In plain English
        </div>
        <div style={{ fontSize: 13, color: C.t, marginTop: 6, lineHeight: 1.5, fontWeight: 500 }}>
          {recoveryAvailable ? <>Recovery is <span style={{ color: zoneColor, fontWeight: 700 }}>{data.recovery}%</span>. </> : <>Recovery data is <span style={{ color: C.t3, fontWeight: 700 }}>unavailable</span>. </>}
          Strain target <span style={{ color: C.warn, fontWeight: 700 }}>{data.strainTarget.low}–{data.strainTarget.high}</span>,
          {need?.bedtimeBy ? <> then in bed by <span style={{ color: C.cyan, fontWeight: 700 }}>{need.bedtimeBy}</span>.</> : <> with sleep need pending.</>}
        </div>
        <button
          onClick={() => onRingTap("primer")}
          style={{
            marginTop: 10,
            background: "none",
            border: "none",
            padding: 0,
            color: C.t3,
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: FONT,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <span
            style={{
              width: 14,
              height: 14,
              borderRadius: 7,
              background: C.s3,
              color: C.t2,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              fontWeight: 800,
            }}
          >
            ?
          </span>
          What do these numbers actually mean?
        </button>
      </Panel>

      {/* Today's target strip */}
      <Panel C={C} style={{ background: C.s, padding: "12px 14px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              Aim for today
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 3, whiteSpace: "nowrap" }}>
              <div style={{ fontSize: 20, fontWeight: 800, fontFamily: MONO, color: C.warn, letterSpacing: "-.04em" }}>
                {data.strainTarget.low}–{data.strainTarget.high}
              </div>
              <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>strain</div>
            </div>
            <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {data.strainTarget.reason}
            </div>
          </div>
          <div style={{ width: 1, height: 38, background: C.border, flexShrink: 0 }} />
          <StrainSoFar C={C} current={data.strain} low={data.strainTarget.low} high={data.strainTarget.high} />
        </div>
      </Panel>

      {/* Coach banner */}
      {data.coachInsights.length > 0 && (
        <button
          onClick={() => onOpenChat()}
          style={{
            width: "100%",
            background: C.s,
            border: `1px solid ${C.border}`,
            borderRadius: 18,
            padding: 14,
            marginBottom: 10,
            textAlign: "left",
            cursor: "pointer",
            fontFamily: FONT,
            color: C.t,
            display: "flex",
            gap: 12,
            alignItems: "flex-start",
          }}
        >
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              flexShrink: 0,
              background: `linear-gradient(135deg, ${C.primary}, ${C.cyan})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.bg,
              fontWeight: 800,
              fontSize: 13,
            }}
          >
            AI
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
              Coach · {data.coachInsights[0].title}
            </div>
            <div style={{ fontSize: 13, color: C.t, marginTop: 4, lineHeight: 1.45, fontWeight: 500 }}>
              {data.coachInsights[0].body}
            </div>
            <div style={{ fontSize: 11, color: C.primary, marginTop: 6, fontWeight: 700, display: "flex", alignItems: "center", gap: 4 }}>
              Tap to ask coach →
            </div>
          </div>
        </button>
      )}

      {/* HRV trend */}
      <Panel
        C={C}
        title="HRV · nervous system freshness"
        right={
          data.hrv != null && data.base.hrv != null ? (
            <Chip C={C} color={data.hrv >= data.base.hrv ? C.primary : C.warn}>
              {data.hrv >= data.base.hrv ? "fresh today" : "below baseline"}
            </Chip>
          ) : (
            <Chip C={C} color={C.t3}>no data yet</Chip>
          )
        }
      >
        <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, marginBottom: 10 }}>
          <span style={{ color: C.t2, fontWeight: 700 }}>Heart Rate Variability</span> — how much the gaps between heartbeats vary.
          <span style={{ color: C.t2, fontWeight: 600 }}> Higher = more rested.</span> Drops mean stress, poor sleep, alcohol, or hard training the day before.
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 6 }}>
          <div style={{ fontSize: 24, fontWeight: 700, fontFamily: MONO, color: C.primary, letterSpacing: "-.04em" }}>
            {data.hrv ?? "—"}
            {data.hrv != null && <span style={{ fontSize: 12, color: C.t3, marginLeft: 3 }}>ms</span>}
          </div>
          {data.hrv != null && data.base.hrv != null && (
            <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
              today · {data.hrv >= data.base.hrv ? "above" : "below"} your {data.base.hrv} avg
            </div>
          )}
          <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
            30d avg {(() => {
              const vals = data.hrv30d.filter((v): v is number => v != null);
              return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : "—";
            })()}
          </div>
        </div>
        <Sparkline data={data.hrv30d} color={C.primary} h={44} baseline={data.base.hrv} />
      </Panel>

      {/* Week recovery at a glance */}
      <Panel C={C} title="7-day recovery" right={<Chip C={C}>tap a day</Chip>}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 4 }}>
          {data.recoveryWeek.map((d, i) => {
            const col = d.tag === "green" ? C.primary : d.tag === "yellow" ? C.yellow : d.tag === "red" ? C.danger : C.t4;
            return (
              <div
                key={i}
                style={{
                  background: d.today ? col + "18" : C.s2,
                  borderRadius: 10,
                  padding: "7px 2px 8px",
                  textAlign: "center",
                  border: d.today ? `1px solid ${col}` : "1px solid transparent",
                }}
              >
                <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, fontWeight: 700, letterSpacing: ".05em" }}>
                  {d.d.toUpperCase()}
                </div>
                <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{d.date}</div>
                <div style={{ fontSize: 14, fontWeight: 800, fontFamily: MONO, color: col, letterSpacing: "-.03em", marginTop: 4 }}>
                  {d.rec ?? "·"}
                </div>
                <div style={{ height: 2.5, borderRadius: 2, background: C.s4, margin: "4px 4px 0", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${d.rec ?? 0}%`, background: col }} />
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      {/* Hydration + Caffeine */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <HydrationPanel C={C} water={data.water} waterGoal={data.waterGoal} onOpenDetail={nutrition ? () => setHydrationOpen(true) : undefined} />
        <CaffeinePanel C={C} mg={data.caffeineMg ?? null} goal={data.caffeineGoal ?? 400} />
      </div>
      {nutrition && (
        <HydrationDetail
          C={C}
          open={hydrationOpen}
          onClose={() => setHydrationOpen(false)}
          date={nutrition.date || todayISO()}
          water={data.water}
          waterGoal={data.waterGoal}
          waterLogs={nutrition.waterLogs ?? []}
          meals={nutrition.meals}
        />
      )}

      {/* Quick actions */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, margin: "4px 0 8px" }}>
        <Btn C={C} primary full onClick={onLogMeal}>
          + Log meal
        </Btn>
        <Btn C={C} full onClick={onLogWorkout}>
          + Log workout
        </Btn>
      </div>
    </div>
  );
}

function formatAge(updatedAt: string | null | undefined, now: number): string {
  if (!updatedAt) return "no data yet";
  const then = new Date(updatedAt).getTime();
  if (Number.isNaN(then)) return "no data yet";
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const d = new Date(updatedAt);
  return `at ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()}`;
}

function FreshnessIndicator({ C, updatedAt }: { C: Palette; updatedAt: string | null | undefined }) {
  const [now, setNow] = useState(() => Date.now());
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);

  // Tick every 30s so the relative time doesn't drift while the tab is open.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshFailed(false);
    try {
      await refreshAppData();
      setNow(Date.now());
    } catch {
      setRefreshFailed(true);
    } finally {
      setRefreshing(false);
    }
  };

  const label = refreshing
    ? "refreshing app data…"
    : refreshFailed
    ? "refresh failed · retry"
    : `updated ${formatAge(updatedAt, now)}`;

  return (
    <button
      onClick={handleRefresh}
      aria-label="Refresh data"
      aria-live="polite"
      disabled={refreshing}
      style={{
        background: C.s2,
        border: `1px solid ${C.border}`,
        color: C.t3,
        padding: "4px 10px",
        borderRadius: 14,
        fontFamily: MONO,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: ".02em",
        cursor: refreshing ? "wait" : "pointer",
        opacity: refreshing ? 0.6 : 1,
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
      }}
    >
      <span
        style={{
          display: "inline-block",
          width: 9,
          height: 9,
          borderRadius: 5,
          border: `1.5px solid ${C.t3}`,
          borderTopColor: "transparent",
          animation: refreshing ? "spin 0.8s linear infinite" : "none",
        }}
      />
      {label}
    </button>
  );
}

// Strain hero ring with target band overlay
function StrainSoFar({ C, current, low, high }: { C: Palette; current: number | null; low: number; high: number }) {
  if (current == null) {
    return (
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>Strain so far</div>
        <div style={{ fontSize: 20, fontWeight: 800, fontFamily: MONO, color: C.t3, marginTop: 3 }}>—</div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2 }}>data unavailable</div>
      </div>
    );
  }
  // Progress within the target band. Above the band we're "over",
  // below we're "to go", inside we're "on pace".
  const status: "under" | "in" | "over" = current < low ? "under" : current > high ? "over" : "in";
  const color = status === "in" ? C.primary : status === "over" ? C.danger : C.warn;
  const subline =
    status === "in"
      ? "on pace"
      : status === "over"
      ? `over ${high} target`
      : `${Math.max(0, +(low - current).toFixed(1))} to target`;

  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, whiteSpace: "nowrap" }}>
        Strain so far
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 3, whiteSpace: "nowrap" }}>
        <div style={{ fontSize: 20, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.04em" }}>
          {current.toFixed(1)}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>
          of {low}–{high}
        </div>
      </div>
      <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {subline}
      </div>
    </div>
  );
}

function SleepBankCard({
  C,
  bank,
  bedtimeBy,
}: {
  C: Palette;
  bank: NonNullable<TodayResponse["sleepBank"]>;
  bedtimeBy?: string;
}) {
  const color =
    bank.trend === "surplus" ? C.primary : bank.trend === "deficit" ? C.danger : C.t3;
  const signed = bank.minutes >= 0 ? `+${bank.minutes}m` : `${bank.minutes}m`;
  const hrs = Math.floor(Math.abs(bank.minutes) / 60);
  const mins = Math.abs(bank.minutes) % 60;
  const pretty = hrs > 0 ? `${bank.minutes < 0 ? "−" : "+"}${hrs}h ${mins}m` : signed;
  const message =
    bank.trend === "surplus"
      ? "Ahead of your baseline — stay consistent."
      : bank.trend === "deficit"
      ? `Behind by ${pretty.replace(/^[−+]/, "")}. Aim for ${bedtimeBy ?? "an earlier bedtime"}.`
      : "On pace with your baseline.";
  return (
    <Panel C={C} style={{ background: C.s, padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>
            Sleep bank · last 7 nights
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 3 }}>
            <div style={{ fontSize: 22, fontWeight: 800, fontFamily: MONO, color, letterSpacing: "-.04em" }}>
              {pretty}
            </div>
          </div>
          <div style={{ fontSize: 11, color: C.t4, marginTop: 2 }}>{message}</div>
        </div>
      </div>
    </Panel>
  );
}

function StrainRing({ C, data, onClick }: { C: Palette; data: TodayResponse; onClick: () => void }) {
  const max = 21;
  const val = data.strain;
  const available = val != null;
  const tgt = data.strainTarget;
  const lowPct = tgt.low / max;
  const highPct = tgt.high / max;

  const size = 82;
  const stroke = 5.5;
  const r = 50 - stroke / 2 - 1;
  const ci = 2 * Math.PI * r;
  const bandLen = (highPct - lowPct) * ci;
  const bandDash = `${bandLen} ${ci - bandLen}`;
  const bandOff = ci - lowPct * ci;

  return (
    <button
      onClick={onClick}
      aria-label={available ? `Strain ${val.toFixed(1)} of 21, target ${tgt.low} to ${tgt.high}` : `Strain unavailable, target ${tgt.low} to ${tgt.high}`}
      style={{
        background: C.s,
        borderRadius: 22,
        padding: "16px 8px 14px",
        textAlign: "center",
        border: `1px solid ${C.border}`,
        cursor: "pointer",
        fontFamily: FONT,
        color: C.t,
        transition: "transform .12s ease",
      }}
    >
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".16em", color: C.t3, fontWeight: 700, marginBottom: 12 }}>
        Strain
      </div>
      <div style={{ position: "relative", width: 82, height: 82, margin: "0 auto 10px" }}>
        <svg viewBox="0 0 100 100" style={{ width: size, height: size, transform: "rotate(-90deg)", position: "absolute", inset: 0 }}>
          <circle cx="50" cy="50" r={r} stroke={C.s3} strokeWidth={stroke} fill="none" />
          <circle
            cx="50"
            cy="50"
            r={r}
            stroke={C.warn}
            strokeOpacity="0.25"
            strokeWidth={stroke + 1.5}
            fill="none"
            strokeDasharray={bandDash}
            strokeDashoffset={bandOff}
          />
          <circle
            cx="50"
            cy="50"
            r={r}
            stroke={C.warn}
            strokeWidth={stroke}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={ci}
            strokeDashoffset={ci - ((val ?? 0) / max) * ci}
            style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)" }}
          />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: MONO, letterSpacing: "-.05em", lineHeight: 1, color: C.warn }}>
            {available ? val.toFixed(1) : "—"}
          </div>
          <div style={{ fontSize: 11, fontWeight: 500, color: C.t3, marginTop: 2, fontFamily: MONO }}>
            {available ? `aim ${tgt.low}–${tgt.high}` : "unavailable"}
          </div>
        </div>
      </div>
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          padding: "4px 10px",
          borderRadius: 20,
          color: C.warn,
          background: C.warnDim,
          textTransform: "uppercase",
          letterSpacing: ".08em",
        }}
      >
        {available ? "In progress" : "No data"}
      </span>
    </button>
  );
}

function JournalCard({
  C,
  data,
  onOpen,
  onOpenHistory,
}: {
  C: Palette;
  data: TodayResponse;
  onOpen: () => void;
  onOpenHistory: () => void;
}) {
  const [composerOpen, setComposerOpen] = useState(false);
  const morning = data.journal?.morning ?? null;
  const evening = data.journal?.evening ?? null;
  const notes = data.journal?.notes ?? [];
  const isEveningTime = new Date().getHours() >= 18;
  const todayStr = todayISO();

  const handleAddNote = async (draft: NoteDraft) => {
    await submitJournal({ slot: "note", date: todayStr, ...draft });
    setComposerOpen(false);
  };

  // State machine:
  //   pending-morning = no morning entry AND before 6pm
  //   pending-evening = has morning (or past 6pm) AND no evening entry
  //   logged          = has both OR morning pending is stale (e.g., past 6pm with morning already)
  let state: "pending-morning" | "pending-evening" | "logged";
  if (!morning && !isEveningTime) state = "pending-morning";
  else if (!evening && isEveningTime) state = "pending-evening";
  else if (morning && evening) state = "logged";
  else if (morning && !isEveningTime) state = "logged";
  else state = "pending-morning";

  const pending = state !== "logged";
  const heading =
    state === "pending-morning"
      ? "Morning check-in"
      : state === "pending-evening"
      ? "Evening reflection"
      : "Journal · today";
  const subhead =
    state === "pending-morning"
      ? "Tag last night"
      : state === "pending-evening"
      ? "Close out the day"
      : evening
      ? "Morning + evening saved"
      : "Morning saved";
  const cta =
    state === "pending-morning"
      ? "Log last night"
      : state === "pending-evening"
      ? "Write reflection"
      : null;

  return (
    <Panel
      C={C}
      style={{
        background: pending
          ? `linear-gradient(180deg, ${C.s}, ${C.primaryDim} 200%)`
          : C.s,
        borderColor: pending ? C.primary + "30" : C.border,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 10,
          gap: 8,
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 11,
              color: C.primary,
              textTransform: "uppercase",
              letterSpacing: ".12em",
              fontWeight: 700,
              whiteSpace: "nowrap",
            }}
          >
            {heading}
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.t, marginTop: 3, letterSpacing: "-.01em" }}>
            {subhead}
          </div>
        </div>
        {pending && (
          <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>
            ~30 sec
          </div>
        )}
      </div>

      {state === "pending-morning" && <PendingPreviewTags C={C} />}
      {state === "pending-evening" && (
        <div style={{ fontSize: 11, color: C.t2, lineHeight: 1.5, marginBottom: 10 }}>
          {morning
            ? "Morning's saved. Add how the day actually went."
            : "Jump straight to the evening reflection."}
        </div>
      )}
      {state === "logged" && <LoggedSummary C={C} morning={morning} evening={evening} />}

      {cta && (
        <Btn C={C} primary full onClick={onOpen}>
          {cta}
        </Btn>
      )}

      {notes.length > 0 && <NotesStrip C={C} notes={notes} />}

      {composerOpen && (
        <div style={{ marginTop: 10 }}>
          <NoteComposer
            C={C}
            date={todayStr}
            dateMode="today"
            onSubmit={handleAddNote}
            onCancel={() => setComposerOpen(false)}
          />
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10, gap: 8 }}>
        <button
          onClick={onOpenHistory}
          style={{
            all: "unset",
            cursor: "pointer",
            fontSize: 11,
            color: C.t4,
            fontFamily: MONO,
            letterSpacing: ".06em",
          }}
        >
          {state === "logged" ? "Tap to edit · " : ""}View past entries →
        </button>
        <button
          onClick={() => setComposerOpen((v) => !v)}
          style={{
            all: "unset",
            cursor: "pointer",
            fontSize: 11,
            color: composerOpen ? C.t4 : C.primary,
            fontFamily: MONO,
            letterSpacing: ".06em",
            fontWeight: 700,
          }}
        >
          {composerOpen ? "× close" : "+ quick note"}
        </button>
      </div>
    </Panel>
  );
}

function NotesStrip({ C, notes }: { C: Palette; notes: JournalNote[] }) {
  const sorted = [...notes].sort((a, b) => (a.at || "").localeCompare(b.at || ""));
  const recent = sorted.slice(-2);
  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
      {sorted.length > 2 && (
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, letterSpacing: ".08em" }}>
          {sorted.length - 2} EARLIER NOTES · TAP "VIEW PAST" TO SEE ALL
        </div>
      )}
      {recent.map((n) => {
        const dt = n.at ? new Date(n.at) : null;
        const hhmm = dt && !Number.isNaN(dt.getTime())
          ? `${dt.getHours().toString().padStart(2, "0")}:${dt.getMinutes().toString().padStart(2, "0")}`
          : "";
        return (
          <div
            key={n.id}
            style={{
              background: C.s2,
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              padding: "6px 10px",
              fontSize: 12,
              color: C.t2,
              lineHeight: 1.4,
            }}
          >
            <span style={{ fontSize: 10, color: C.t4, fontFamily: MONO, marginRight: 6 }}>{hhmm}</span>
            "{n.text}"
          </div>
        );
      })}
    </div>
  );
}

function PendingPreviewTags({ C }: { C: Palette }) {
  return (
    <>
      <div style={{ fontSize: 11, color: C.t2, lineHeight: 1.5, marginBottom: 10 }}>
        Quick tags + 2 prompts → after 2 weeks we'll show what actually moves your HRV.
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {["🍷 Alcohol", "☕ Late caffeine", "📱 Screens", "🧘 Meditated", "🔥 Sauna"].map((t, i) => (
          <div
            key={i}
            style={{
              fontSize: 11,
              color: C.t2,
              background: C.s2,
              border: `1px solid ${C.border}`,
              padding: "6px 10px",
              borderRadius: 18,
              fontWeight: 600,
            }}
          >
            {t}
          </div>
        ))}
        <div style={{ fontSize: 11, color: C.t4, padding: "6px 10px", fontWeight: 600 }}>
          +{JOURNAL_TAGS.length - 5} more
        </div>
      </div>
    </>
  );
}

function LoggedSummary({
  C,
  morning,
  evening,
}: {
  C: Palette;
  morning: MorningEntry | null;
  evening: EveningEntry | null;
}) {
  const morningTags = (morning?.tags ?? [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean);
  const eveningTags = (evening?.tags ?? [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean);

  return (
    <>
      {morning && (
        <div style={{ marginBottom: evening ? 10 : 4 }}>
          <div
            style={{
              fontSize: 10,
              color: C.t4,
              textTransform: "uppercase",
              letterSpacing: ".12em",
              fontWeight: 700,
              marginBottom: 5,
            }}
          >
            Morning
          </div>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {morningTags.map((t) =>
              t ? (
                <div
                  key={t.id}
                  style={{
                    fontSize: 11,
                    color: t.negative ? C.warn : C.primary,
                    background: (t.negative ? C.warn : C.primary) + "15",
                    padding: "4px 8px",
                    borderRadius: 12,
                    fontWeight: 600,
                  }}
                >
                  {t.icon} {t.label}
                </div>
              ) : null,
            )}
          </div>
          {morning.text && (
            <div
              style={{
                fontSize: 12,
                color: C.t2,
                lineHeight: 1.4,
                marginTop: 6,
                overflow: "hidden",
                textOverflow: "ellipsis",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              "{morning.text}"
            </div>
          )}
        </div>
      )}
      {evening && (
        <div style={{ marginBottom: 4 }}>
          <div
            style={{
              fontSize: 10,
              color: C.t4,
              textTransform: "uppercase",
              letterSpacing: ".12em",
              fontWeight: 700,
              marginBottom: 5,
            }}
          >
            Evening
          </div>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {eveningTags.map((t) =>
              t ? (
                <div
                  key={t.id}
                  style={{
                    fontSize: 11,
                    color: t.negative ? C.warn : C.primary,
                    background: (t.negative ? C.warn : C.primary) + "15",
                    padding: "4px 8px",
                    borderRadius: 12,
                    fontWeight: 600,
                  }}
                >
                  {t.icon} {t.label}
                </div>
              ) : null,
            )}
          </div>
          {evening.text && (
            <div
              style={{
                fontSize: 12,
                color: C.t2,
                lineHeight: 1.4,
                marginTop: 6,
                overflow: "hidden",
                textOverflow: "ellipsis",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              "{evening.text}"
            </div>
          )}
        </div>
      )}
    </>
  );
}
