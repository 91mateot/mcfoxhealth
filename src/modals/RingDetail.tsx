import { MONO, type Palette } from "../theme";
import type { TodayResponse } from "../types";
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
        { k: "Sleep last night", v: `${today.sleep.score}%`, sub: `${today.sleep.hours}h ${today.sleep.minutes}m`, w: "supporting", col: C.primary },
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
        title: `Recovered · ${today.recovery}%`,
        color: C.primary,
        hero: String(today.recovery),
        heroUnit: "%",
        what: "How ready your body is, on a 0–100 scale.",
        blurb:
          "Built mostly from how much your heart-rate varies (HRV), how hard your heart's working at rest, and how well you slept. Higher = more recovered.",
        rows,
      };
    })(),
    strain: {
      title: "Strain today",
      color: C.warn,
      hero: (today.strain ?? 0).toFixed(1),
      heroUnit: "/21",
      what: "How hard you've pushed your heart today.",
      blurb: `A 0–21 score of total cardiovascular work — time at elevated heart rate. Target today: ${today.strainTarget.low}–${today.strainTarget.high} (${today.strainTarget.reason}).`,
      rows: [
        { k: "Calories burned", v: `${today.calories.active} kcal`, sub: "day so far", w: "", col: C.warn },
        { k: "Target low", v: String(today.strainTarget.low), sub: "bottom of band", w: "", col: C.warn },
        { k: "Target high", v: String(today.strainTarget.high), sub: "top of band", w: "", col: C.warn },
        { k: "Optimal", v: String(today.strainTarget.optimal), sub: "midpoint", w: "", col: C.warn },
      ],
    },
    sleep: {
      title: "Sleep last night",
      color: C.cyan,
      hero: `${today.sleep.hours}:${String(today.sleep.minutes).padStart(2, "0")}`,
      heroUnit: "",
      what: "How much and how well you slept.",
      blurb: `You slept ${today.sleep.hours}h ${today.sleep.minutes}m. ${today.sleep.efficiency}% of that was actually asleep.`,
      rows: [
        { k: "Total time asleep", v: `${today.sleep.hours}h ${today.sleep.minutes}m`, sub: "needed 7h 30m", w: "", col: C.cyan },
        { k: "Sleep efficiency", v: `${today.sleep.efficiency}%`, sub: "how still you were", w: "good >90%", col: C.cyan },
        {
          k: "Deep sleep",
          v: `${Math.floor(today.sleep.deep / 60)}h ${today.sleep.deep % 60}m`,
          sub: "physical recovery",
          w: "healthy",
          col: "#3b5cff",
        },
        {
          k: "Dream sleep (REM)",
          v: `${Math.floor(today.sleep.rem / 60)}h ${today.sleep.rem % 60}m`,
          sub: "memory & mood",
          w: "healthy",
          col: C.purple,
        },
      ],
    },
  };
  const cfg = configs[which];

  return (
    <Sheet C={C} open={open} onClose={onClose} title={cfg.title} height="78%">
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
