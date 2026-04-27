import { useEffect, useState } from "react";
import { mutate } from "swr";
import { FONT, MONO, type Palette } from "../theme";
import { JOURNAL_TAGS, type TodayResponse } from "../types";
import { BigRing } from "../components/BigRing";
import { Panel } from "../components/Panel";
import { Chip } from "../components/Chip";
import { Sparkline } from "../components/Sparkline";
import { ProgressBar } from "../components/ProgressBar";
import { Btn } from "../components/Btn";

interface TodayScreenProps {
  C: Palette;
  data: TodayResponse;
  onRingTap: (which: "recovery" | "strain" | "sleep" | "primer") => void;
  onOpenChat: () => void;
  onLogMeal: () => void;
  onLogWorkout: () => void;
  onOpenJournal: () => void;
}

export function TodayScreen({ C, data, onRingTap, onOpenChat, onLogMeal, onLogWorkout, onOpenJournal }: TodayScreenProps) {
  const need = data.sleepNeedTonight;
  const needH = Math.floor(need.totalMin / 60);
  const needM = need.totalMin % 60;
  const zone = data.recoveryZone ?? (data.recovery >= 67 ? "green" : data.recovery >= 34 ? "yellow" : "red");
  const zoneColor = zone === "green" ? C.primary : zone === "yellow" ? C.yellow : C.danger;
  const zoneLabel = zone === "green" ? "Recovered" : zone === "yellow" ? "Moderate" : "Depleted";
  const zoneHeadline =
    zone === "green"
      ? "Train today."
      : zone === "yellow"
      ? "Train smart."
      : "Active recovery.";

  return (
    <div>
      {/* Greeting */}
      <div style={{ padding: "8px 4px 14px" }}>
        <div style={{ fontSize: 12, color: C.t3, fontFamily: MONO, letterSpacing: ".04em" }}>
          {data.dateFull.toUpperCase()} · PACIFIC BEACH
        </div>
        <div style={{ fontSize: 26, fontWeight: 700, color: C.t, letterSpacing: "-.02em", marginTop: 4, lineHeight: 1.15 }}>
          Morning, Mateo.
          <br />
          <span style={{ color: zoneColor }}>{zoneLabel}.</span> {zoneHeadline}
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <Chip C={C} color={zoneColor}>● {zone.toUpperCase()}</Chip>
          <Chip C={C} color={C.t3}>RECOMP</Chip>
          <FreshnessIndicator C={C} updatedAt={data.updatedAt} />
        </div>
      </div>

      {/* Journal check-in — shown first if pending */}
      {data.journal && !data.journal.submitted && <JournalCard C={C} data={data} onOpen={onOpenJournal} />}

      {/* Hero rings */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 7, marginBottom: 10 }}>
        <BigRing
          C={C}
          val={data.recovery}
          max={100}
          color={zoneColor}
          label="Recovered"
          display={data.recovery}
          unit="%"
          tag={zone === "green" ? "Ready" : zone === "yellow" ? "Mod" : "Rest"}
          tagC={zoneColor}
          onClick={() => onRingTap("recovery")}
        />
        <StrainRing C={C} data={data} onClick={() => onRingTap("strain")} />
        <BigRing
          C={C}
          val={data.sleep.score}
          max={100}
          color={C.cyan}
          label="Slept"
          display={data.sleep.score}
          unit={`${data.sleep.hours}h ${data.sleep.minutes}m`}
          tag={data.sleep.score >= 80 ? "Solid" : data.sleep.score >= 60 ? "Ok" : "Low"}
          tagC={C.cyan}
          onClick={() => onRingTap("sleep")}
        />
      </div>

      {/* Plain-English summary */}
      <Panel C={C} style={{ background: C.s, padding: "12px 14px" }}>
        <div style={{ fontSize: 11, color: zoneColor, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700 }}>
          In plain English
        </div>
        <div style={{ fontSize: 13, color: C.t, marginTop: 6, lineHeight: 1.5, fontWeight: 500 }}>
          Recovery is <span style={{ color: zoneColor, fontWeight: 700 }}>{data.recovery}%</span>.
          Effort target <span style={{ color: C.warn, fontWeight: 700 }}>{data.strainTarget.low}–{data.strainTarget.high}</span>,
          then in bed by <span style={{ color: C.cyan, fontWeight: 700 }}>{need.bedtimeBy}</span>.
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
              <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>effort</div>
            </div>
            <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {data.strainTarget.reason}
            </div>
          </div>
          <div style={{ width: 1, height: 38, background: C.border, flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, whiteSpace: "nowrap" }}>
              Sleep tonight
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 3 }}>
              <div style={{ fontSize: 20, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>
                {needH}h {needM < 10 ? "0" : ""}{needM}m
              </div>
            </div>
            <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              bed by {need.bedtimeBy}
            </div>
          </div>
        </div>
      </Panel>

      {/* Coach banner */}
      {data.coachInsights.length > 0 && (
        <button
          onClick={onOpenChat}
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
          data.hrv != null ? (
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
            <span style={{ fontSize: 12, color: C.t3, marginLeft: 3 }}>ms</span>
          </div>
          {data.hrv != null && (
            <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
              today · {data.hrv >= data.base.hrv ? "above" : "below"} your {data.base.hrv} avg
            </div>
          )}
          <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
            30d avg {(() => {
              const vals = data.hrv30d.filter((v) => v > 0);
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
            const col = d.tag === "green" ? C.primary : d.tag === "yellow" ? C.yellow : C.danger;
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
                  {d.rec || "·"}
                </div>
                <div style={{ height: 2.5, borderRadius: 2, background: C.s4, margin: "4px 4px 0", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${d.rec}%`, background: col }} />
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      {/* Hydration */}
      <Panel
        C={C}
        title="Hydration"
        right={<Chip C={C} color={C.cyan}>{data.water} / {data.waterGoal} oz</Chip>}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
          <div style={{ fontSize: 24, fontWeight: 800, fontFamily: MONO, color: C.cyan, letterSpacing: "-.04em" }}>
            {data.water}
          </div>
          <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO }}>
            oz · {Math.round((data.water / data.waterGoal) * 100)}% of daily
          </div>
          <div style={{ marginLeft: "auto", fontSize: 11, color: C.t4, fontFamily: MONO }}>
            {Math.max(0, data.waterGoal - data.water)} oz left
          </div>
        </div>
        <ProgressBar C={C} val={data.water} max={data.waterGoal} color={C.cyan} height={6} />
      </Panel>

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

  // Tick every 30s so the relative time doesn't drift while the tab is open.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await mutate("/api/today");
      setNow(Date.now());
    } finally {
      setRefreshing(false);
    }
  };

  const label = refreshing ? "refreshing…" : `updated ${formatAge(updatedAt, now)}`;

  return (
    <button
      onClick={handleRefresh}
      aria-label="Refresh data"
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
function StrainRing({ C, data, onClick }: { C: Palette; data: TodayResponse; onClick: () => void }) {
  const max = 21;
  const val = data.strain;
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
      aria-label={`Effort ${val.toFixed(1)} of 21, target ${tgt.low} to ${tgt.high}`}
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
        Effort
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
            strokeDashoffset={ci - (val / max) * ci}
            style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)" }}
          />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: MONO, letterSpacing: "-.05em", lineHeight: 1, color: C.warn }}>
            {val.toFixed(1)}
          </div>
          <div style={{ fontSize: 11, fontWeight: 500, color: C.t3, marginTop: 2, fontFamily: MONO }}>
            aim {tgt.low}–{tgt.high}
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
        In progress
      </span>
    </button>
  );
}

function JournalCard({ C, data, onOpen }: { C: Palette; data: TodayResponse; onOpen: () => void }) {
  const submitted = data.journal?.submitted ?? false;
  const lastTags = (data.journalLastNight?.tags ?? [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean);

  return (
    <Panel
      C={C}
      style={{
        background: submitted ? C.s : `linear-gradient(180deg, ${C.s}, ${C.primaryDim} 200%)`,
        borderColor: submitted ? C.border : C.primary + "30",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 11, color: C.primary, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, whiteSpace: "nowrap" }}>
            {submitted ? "Last night · logged" : "Morning check-in"}
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.t, marginTop: 3, letterSpacing: "-.01em" }}>
            {submitted ? "Nice — tags saved" : "Tag last night"}
          </div>
        </div>
        {!submitted && <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>~20 sec</div>}
      </div>

      {!submitted ? (
        <>
          <div style={{ fontSize: 11, color: C.t2, lineHeight: 1.5, marginBottom: 10 }}>
            Quick tags → after 2 weeks we'll show what actually moves your HRV.
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
          <Btn C={C} primary full onClick={onOpen}>
            Log last night
          </Btn>
        </>
      ) : (
        <>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {lastTags.map((t) =>
              t ? (
                <div
                  key={t.id}
                  style={{
                    fontSize: 11,
                    color: t.negative ? C.warn : C.primary,
                    background: (t.negative ? C.warn : C.primary) + "15",
                    padding: "5px 9px",
                    borderRadius: 14,
                    fontWeight: 600,
                    border: `1px solid ${(t.negative ? C.warn : C.primary)}30`,
                  }}
                >
                  {t.icon} {t.label}
                </div>
              ) : null
            )}
          </div>
          <div style={{ fontSize: 11, color: C.t4, marginTop: 10, fontFamily: MONO }}>
            Tap to edit → {data.journalLastNight?.date}
          </div>
        </>
      )}
    </Panel>
  );
}
