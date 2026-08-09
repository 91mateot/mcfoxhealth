import { MONO, type Palette } from "../theme";
import type {
  SleepComponentLabel,
  SleepComponentScores,
  SleepQualityFlag,
  SleepSegment,
  TodayResponse,
} from "../types";
import { Sheet } from "../components/Sheet";

export type RingKey = "recovery" | "strain" | "sleep" | "primer";

interface RingDetailSheetProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  which: RingKey | null;
  today: TodayResponse | null;
}

export function RingDetailSheet({ C, open, onClose, which, today }: RingDetailSheetProps) {
  if (!which || !today) return <Sheet C={C} open={open} onClose={onClose} />;
  if (which === "primer") return <PrimerSheet C={C} open={open} onClose={onClose} />;

  const configs: Record<Exclude<RingKey, "primer">, {
    title: string;
    color: string;
    hero: string;
    heroUnit: string;
    what: string;
    blurb: string;
    rows: { k: string; v: string; sub: string; w: string; col: string }[];
  }> = {
    recovery: (() => {
      const rows: { k: string; v: string; sub: string; w: string; col: string }[] = [
        { k: "HRV · nervous system", v: today.hrv != null ? `${today.hrv} ms` : "—", sub: "higher = more rested", w: "main driver", col: C.primary },
        { k: "Resting pulse", v: today.rhr != null ? `${today.rhr} bpm` : "—", sub: "lower than usual = good", w: "supporting", col: C.primary },
        { k: "Sleep last night", v: today.sleep.score != null ? `${today.sleep.score}%` : "—", sub: today.sleep.hours != null ? `${today.sleep.hours}h ${today.sleep.minutes ?? 0}m` : "unavailable", w: "supporting", col: C.primary },
      ];
      if (today.resp != null) {
        rows.push({ k: "Breathing rate", v: `${today.resp} /min`, sub: "while asleep · low and steady is ideal", w: "minor", col: C.primary });
      }
      if (today.spo2 != null) {
        rows.push({ k: "Blood oxygen", v: `${today.spo2}%`, sub: "overnight · 95%+ is normal", w: "minor", col: C.primary });
      }
      if (today.wristTemp != null) {
        rows.push({ k: "Skin temperature", v: `${today.wristTemp}°`, sub: "early signal for illness or inflammation", w: "minor", col: C.primary });
      }
      return {
        title: today.recovery != null ? `Recovered · ${today.recovery}%` : "Recovery unavailable",
        color: C.primary,
        hero: today.recovery != null ? String(today.recovery) : "—",
        heroUnit: today.recovery != null ? "%" : "",
        what: "How ready your body is, on a 0–100 scale.",
        blurb:
          "Built mostly from how much your heart-rate varies (HRV), how hard your heart's working at rest, and how well you slept. Higher = more recovered.",
        rows,
      };
    })(),
    strain: {
      title: "Strain today",
      color: C.warn,
      hero: today.strain != null ? today.strain.toFixed(1) : "—",
      heroUnit: "/21",
      what: "How hard you've pushed your heart today.",
      blurb: `A 0–21 score of total cardiovascular work — time at elevated heart rate. Target today: ${today.strainTarget.low}–${today.strainTarget.high} (${today.strainTarget.reason}).`,
      rows: [
        { k: "Calories burned", v: today.calories.active != null ? `${today.calories.active} kcal` : "—", sub: today.calories.active != null ? "day so far" : "unavailable", w: "", col: C.warn },
        { k: "Target low", v: String(today.strainTarget.low), sub: "bottom of band", w: "", col: C.warn },
        { k: "Target high", v: String(today.strainTarget.high), sub: "top of band", w: "", col: C.warn },
        { k: "Optimal", v: String(today.strainTarget.optimal), sub: "midpoint", w: "", col: C.warn },
      ],
    },
    sleep: (() => {
      const s = today.sleep;
      const rows: { k: string; v: string; sub: string; w: string; col: string }[] = [
        { k: "Total time asleep", v: s.hours != null ? `${s.hours}h ${s.minutes ?? 0}m` : "—", sub: s.hours != null ? "needed 7h 30m" : "unavailable", w: "", col: C.cyan },
        { k: "Sleep efficiency", v: s.efficiency != null ? `${s.efficiency}%` : "—", sub: s.efficiency != null ? "how still you were" : "unavailable", w: s.efficiency != null ? "good >90%" : "", col: C.cyan },
        {
          k: "Deep sleep",
          v: s.deep != null ? `${Math.floor(s.deep / 60)}h ${s.deep % 60}m` : "—",
          sub: "physical recovery",
          w: "healthy",
          col: "#3b5cff",
        },
        {
          k: "Dream sleep (REM)",
          v: s.rem != null ? `${Math.floor(s.rem / 60)}h ${s.rem % 60}m` : "—",
          sub: "memory & mood",
          w: "healthy",
          col: C.purple,
        },
      ];
      if (typeof s.arousalCount === "number") {
        rows.push({
          k: "Wake-ups",
          v: String(s.arousalCount),
          sub: "brief stirs ignored",
          w: "fewer = deeper",
          col: C.cyan,
        });
      }
      if (typeof s.onsetMin === "number") {
        rows.push({
          k: "Time to fall asleep",
          v: `${Math.round(s.onsetMin)}m`,
          sub: "from getting in bed",
          w: "15m is typical",
          col: C.cyan,
        });
      }
      if (typeof s.avgHrSleep === "number") {
        const low = typeof s.minHrSleep === "number" ? ` · low ${s.minHrSleep}` : "";
        rows.push({
          k: "Sleeping heart rate",
          v: `${s.avgHrSleep} bpm`,
          sub: `average while asleep${low}`,
          w: "lower = restful",
          col: C.cyan,
        });
      }
      return {
        title: "Sleep last night",
        color: C.cyan,
        hero: s.hours != null ? `${s.hours}:${String(s.minutes ?? 0).padStart(2, "0")}` : "—",
        heroUnit: "",
        what: "How much and how well you slept.",
        blurb: s.hours != null
          ? `You slept ${s.hours}h ${s.minutes ?? 0}m. ${s.efficiency != null ? `${s.efficiency}% of that was actually asleep.` : "Efficiency is unavailable."}`
          : "No sleep observation is available for last night.",
        rows,
      };
    })(),
  };
  const cfg = configs[which];
  const sleepQuality = which === "sleep" ? today.sleep.qualityFlag : undefined;

  return (
    <Sheet C={C} open={open} onClose={onClose} title={cfg.title} height="78%">
      {sleepQuality && sleepQuality !== "ok" && (
        <SleepQualityBadge C={C} flag={sleepQuality} reasons={today.sleep.qualityReasons ?? []} />
      )}
      <div style={{ textAlign: "center", padding: "12px 0 10px" }}>
        <div style={{ fontSize: 56, fontWeight: 800, color: cfg.color, fontFamily: MONO, letterSpacing: "-.05em", lineHeight: 1 }}>
          {cfg.hero}
          <span style={{ fontSize: 20, color: C.t3 }}>{cfg.heroUnit}</span>
        </div>
      </div>
      <div
        style={{
          fontSize: 11,
          color: cfg.color,
          textAlign: "center",
          textTransform: "uppercase",
          letterSpacing: ".12em",
          fontWeight: 700,
          marginBottom: 8,
        }}
      >
        {cfg.what}
      </div>
      <div style={{ fontSize: 12.5, color: C.t2, lineHeight: 1.6, padding: "0 4px 16px", textAlign: "center" }}>{cfg.blurb}</div>
      {which === "sleep" && today.sleep.segments && today.sleep.segments.length > 0 && (
        <Hypnogram C={C} segments={today.sleep.segments} />
      )}
      {which === "sleep" && today.sleep.componentScores && (
        <SleepComponentGrid
          C={C}
          scores={today.sleep.componentScores}
          deepMin={today.sleep.deep ?? 0}
          remMin={today.sleep.rem ?? 0}
          hours={today.sleep.hours ?? 0}
          minutes={today.sleep.minutes ?? 0}
          efficiency={today.sleep.efficiency ?? 0}
          arousalCount={today.sleep.arousalCount}
          hrDipPct={today.sleep.hrDipPct ?? null}
        />
      )}
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, padding: "0 4px 8px" }}>
        What it's made of
      </div>
      {cfg.rows.map((r, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 4px",
            borderBottom: i === cfg.rows.length - 1 ? "none" : `1px solid ${C.border}`,
          }}
        >
          <div style={{ width: 6, height: 6, borderRadius: 3, background: r.col, flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600 }}>{r.k}</div>
            <div style={{ fontSize: 11, color: C.t4, marginTop: 2 }}>{r.sub}</div>
          </div>
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 800, fontFamily: MONO, color: r.col, letterSpacing: "-.03em", whiteSpace: "nowrap" }}>
              {r.v}
            </div>
            {r.w && <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{r.w}</div>}
          </div>
        </div>
      ))}
    </Sheet>
  );
}

function SleepQualityBadge({
  C,
  flag,
  reasons,
}: {
  C: Palette;
  flag: SleepQualityFlag;
  reasons: string[];
}) {
  const label =
    flag === "truncated"
      ? "Incomplete night"
      : flag === "partial"
      ? "Partial data"
      : flag === "missing"
      ? "No sleep data"
      : "Quality flag";
  const why = reasons.includes("no_wrist_temp")
    ? "Watch wasn't detected on your wrist — sleep totals may be missing."
    : reasons.includes("stages_dont_sum")
    ? "Sleep stages don't add up to the time in bed — HealthKit returned a partial window."
    : reasons.includes("segments_short_span")
    ? "Sleep segments cover less time than the reported total."
    : "Sleep data looks incomplete. Score uses only HRV and resting pulse tonight.";
  return (
    <div
      style={{
        background: `${C.warn}18`,
        border: `1px solid ${C.warn}55`,
        borderRadius: 10,
        padding: "8px 12px",
        margin: "0 4px 10px",
        fontSize: 11.5,
        color: C.t2,
        lineHeight: 1.4,
      }}
    >
      <span style={{ color: C.warn, fontWeight: 700, marginRight: 6 }}>{label}</span>
      {why}
    </div>
  );
}

function Hypnogram({ C, segments }: { C: Palette; segments: SleepSegment[] }) {
  const sorted = [...segments].sort((a, b) => a.start.localeCompare(b.start));
  if (sorted.length === 0) return null;
  const total = sorted.reduce((sum, s) => sum + s.dur_min, 0);
  if (total <= 0) return null;
  const stageColor = (stage: SleepSegment["stage"]): string => {
    switch (stage) {
      case "deep":
        return "#3b5cff";
      case "rem":
        return C.purple;
      case "core":
        return C.cyan;
      case "awake":
        return C.warn;
      case "in_bed":
        return C.t4;
      default:
        return C.t4;
    }
  };
  return (
    <div style={{ padding: "0 4px 14px" }}>
      <div
        style={{
          fontSize: 11,
          color: C.t3,
          textTransform: "uppercase",
          letterSpacing: ".12em",
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        Sleep stages through the night
      </div>
      <div style={{ display: "flex", height: 26, borderRadius: 6, overflow: "hidden" }}>
        {sorted.map((seg, i) => (
          <div
            key={i}
            title={`${seg.stage} · ${Math.round(seg.dur_min)}m`}
            style={{
              width: `${(seg.dur_min / total) * 100}%`,
              background: stageColor(seg.stage),
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 6, flexWrap: "wrap", fontSize: 10, color: C.t4 }}>
        {[
          { label: "Deep", color: "#3b5cff" },
          { label: "REM", color: C.purple },
          { label: "Core", color: C.cyan },
          { label: "Awake", color: C.warn },
        ].map(({ label, color }) => (
          <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

function SleepComponentGrid({
  C,
  scores,
  deepMin,
  remMin,
  hours,
  minutes,
  efficiency,
  arousalCount,
  hrDipPct,
}: {
  C: Palette;
  scores: SleepComponentScores;
  deepMin: number;
  remMin: number;
  hours: number;
  minutes: number;
  efficiency: number;
  arousalCount?: number;
  hrDipPct: number | null;
}) {
  const labelColor = (label: SleepComponentLabel | null): string => {
    switch (label) {
      case "Excellent":
        return C.primary;
      case "Good":
        return C.cyan;
      case "Fair":
        return C.warn;
      case "Poor":
        return C.danger;
      default:
        return C.t4;
    }
  };
  const fmtHrMin = (min: number) =>
    min <= 0 ? "—" : `${Math.floor(min / 60)}h ${min % 60}m`;
  const cards: {
    title: string;
    value: string;
    label: SleepComponentLabel | null;
  }[] = [
    {
      title: "Duration",
      value: hours > 0 || minutes > 0 ? `${hours}h ${minutes}m` : "—",
      label: scores.duration.label,
    },
    {
      title: "Efficiency",
      value: efficiency > 0 ? `${Math.round(efficiency)}%` : "—",
      label: scores.efficiency.label,
    },
    { title: "Deep", value: fmtHrMin(deepMin), label: scores.deep.label },
    { title: "REM", value: fmtHrMin(remMin), label: scores.rem.label },
    {
      title: "Continuity",
      value:
        scores.continuity.score == null
          ? "—"
          : typeof arousalCount === "number"
          ? `${arousalCount} wake-up${arousalCount === 1 ? "" : "s"}`
          : `${Math.round(scores.continuity.score)}/100`,
      label: scores.continuity.label,
    },
    {
      title: "HR dip",
      value:
        hrDipPct == null
          ? "—"
          : `${Math.round(hrDipPct)}%`,
      label: scores.hrDip.label,
    },
  ];
  return (
    <div style={{ padding: "0 4px 14px" }}>
      <div
        style={{
          fontSize: 11,
          color: C.t3,
          textTransform: "uppercase",
          letterSpacing: ".12em",
          fontWeight: 700,
          marginBottom: 8,
        }}
      >
        Score breakdown
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
        {cards.map((card) => {
          const col = labelColor(card.label);
          return (
            <div
              key={card.title}
              style={{
                background: C.s,
                border: `1px solid ${C.border}`,
                borderRadius: 10,
                padding: "10px 8px",
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 10.5, color: C.t4, fontWeight: 600, letterSpacing: ".02em" }}>
                {card.title}
              </div>
              <div
                style={{
                  fontSize: 14,
                  color: C.t,
                  fontWeight: 800,
                  fontFamily: MONO,
                  marginTop: 4,
                  whiteSpace: "nowrap",
                }}
              >
                {card.value}
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: col,
                  fontWeight: 700,
                  marginTop: 4,
                  textTransform: "uppercase",
                  letterSpacing: ".08em",
                }}
              >
                {card.label ?? "—"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PrimerSheet({ C, open, onClose }: { C: Palette; open: boolean; onClose: () => void }) {
  const items = [
    {
      color: C.primary,
      icon: "●",
      term: "Recovery",
      plain: "How ready you are today. Think of it like a phone battery.",
      details: "High = train hard if you want. Low = take it easy, do mobility or a walk.",
    },
    {
      color: C.primary,
      icon: "♡",
      term: "HRV — your #1 metric",
      plain: "Heart Rate Variability. How much the time between heartbeats varies. More variation = more rested.",
      details:
        "When you're stressed, tired, or hungover, your heart beats more like a metronome. When you're fresh, the spacing jitters — that's good.",
    },
    {
      color: C.primary,
      icon: "♥",
      term: "Resting heart rate",
      plain: "How hard your heart works when you're lying still. Lower is better.",
      details: "",
    },
    {
      color: C.warn,
      icon: "◆",
      term: "Strain (0–21)",
      plain: "A score of how hard you pushed your heart today. Logarithmic — 10 is moderate, 15 is hard, 18+ is very hard.",
      details: "Green day → push (14–17). Yellow → keep it chill (8–12). Red → rest (<8).",
    },
    {
      color: C.cyan,
      icon: "☾",
      term: "Sleep quality",
      plain: "Not just hours in bed — how still you were, plus how much deep + dream sleep you got.",
      details: "Deep sleep rebuilds the body; dream sleep (REM) consolidates memory + mood.",
    },
    {
      color: C.cyan,
      icon: "⌚",
      term: "Sleep need",
      plain: "How much sleep your body needs tonight, given recent debt and today's strain.",
      details: "More debt + harder day = a bigger number.",
    },
  ];

  return (
    <Sheet C={C} open={open} onClose={onClose} title="The numbers, explained" height="88%">
      <div style={{ fontSize: 12, color: C.t3, lineHeight: 1.55, marginBottom: 16 }}>
        No jargon. Here's what each one actually means and why you'd care.
      </div>
      {items.map((it, i) => (
        <div key={i} style={{ marginBottom: 10, background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: 9,
                background: it.color + "18",
                color: it.color,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 15,
                fontWeight: 800,
                flexShrink: 0,
              }}
            >
              {it.icon}
            </div>
            <div style={{ fontSize: 14, color: C.t, fontWeight: 700, letterSpacing: "-.01em" }}>{it.term}</div>
          </div>
          <div style={{ fontSize: 12.5, color: C.t, lineHeight: 1.55, fontWeight: 500 }}>{it.plain}</div>
          {it.details && <div style={{ fontSize: 11.5, color: C.t3, lineHeight: 1.55, marginTop: 6 }}>{it.details}</div>}
        </div>
      ))}
      <div style={{ marginTop: 6, padding: 12, background: C.s2, borderRadius: 12, fontSize: 11.5, color: C.t2, lineHeight: 1.55 }}>
        <span style={{ fontWeight: 700, color: C.t }}>Rule of thumb:</span> if all three rings are green-ish, it's a push day. If any is red, that's your hint to rest.
      </div>
    </Sheet>
  );
}
