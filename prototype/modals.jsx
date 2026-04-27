// Modals — log meal, log workout, chat, ring detail

function LogMealModal({ C, open, onClose, onAdd, prefill }) {
  const quick = [
    { name: "Oikos Vanilla Shake", cal: 170, p: 30, c: 8, f: 3.5 },
    { name: "Kirkland PB Protein Bar", cal: 190, p: 21, c: 22, f: 7 },
    { name: "Costco chicken bake (half)", cal: 385, p: 31, c: 39, f: 13 },
    { name: "Morning shake (half)", cal: 356, p: 26.5, c: 51, f: 8.5 },
    { name: "Rotisserie chicken, 4 oz", cal: 224, p: 26, c: 0, f: 13 },
    { name: "Gochujang broth bowl", cal: 380, p: 36, c: 40, f: 5 },
  ];
  const [custom, setCustom] = useState("");
  useEffect(() => { if (open && prefill) setCustom(prefill); }, [open, prefill]);

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Log a meal" height="78%">
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8 }}>
        Quick add
      </div>
      {quick.map((q, i) => (
        <button key={i} onClick={() => { onAdd(q); onClose(); }} style={{
          width: "100%", background: C.s, border: `1px solid ${C.border}`, borderRadius: 14,
          padding: 12, marginBottom: 6, textAlign: "left", cursor: "pointer",
          fontFamily: FONT, color: C.t, display: "flex", alignItems: "center", gap: 10,
        }}>
          <div style={{
            width: 34, height: 34, borderRadius: 10, background: C.primaryDim,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: C.primary, fontSize: 16, fontWeight: 800,
          }}>+</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{q.name}</div>
            <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO }}>
              {q.cal} kcal · P{q.p} C{q.c} F{q.f}
            </div>
          </div>
        </button>
      ))}
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 14, marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span style={{ whiteSpace: "nowrap" }}>Describe a meal</span>
        <span style={{ fontSize: 9, color: C.primary, fontFamily: MONO, letterSpacing: ".06em", whiteSpace: "nowrap" }}>● TAP MIC</span>
      </div>
      <VoiceInput C={C} value={custom} onChange={setCustom}
        placeholder='"8 oz chicken, 1/3 cup mashed potatoes…"' minHeight={80} />
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <Btn C={C} full onClick={onClose}>Cancel</Btn>
        <Btn C={C} primary full onClick={() => {
          if (custom.trim()) onAdd({ name: custom, cal: 300, p: 25, c: 30, f: 8 });
          onClose(); setCustom("");
        }}>Send to coach →</Btn>
      </div>
    </Sheet>
  );
}

function LogWorkoutModal({ C, open, onClose, onAdd }) {
  const types = ["Push", "Pull", "Legs", "HIIT", "Walk", "Yoga"];
  const [type, setType] = useState("Push");
  const [notes, setNotes] = useState("");

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Log a workout" height="72%">
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginTop: 6, marginBottom: 8 }}>
        Type
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginBottom: 14 }}>
        {types.map(t => (
          <button key={t} onClick={() => setType(t)} style={{
            background: type === t ? C.primary : C.s, color: type === t ? "#0a0a0a" : C.t2,
            border: `1px solid ${type === t ? C.primary : C.border}`, borderRadius: 12,
            padding: "11px 8px", fontFamily: FONT, fontSize: 12, fontWeight: 700, cursor: "pointer",
          }}>{t}</button>
        ))}
      </div>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8 }}>
        Pulling from Strava
      </div>
      <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.t }}>Most recent activity</div>
          <Chip C={C} color={C.warn}>strain 4.2</Chip>
        </div>
        <div style={{ fontSize: 10.5, color: C.t3, fontFamily: MONO, marginTop: 6 }}>
          Today · 34 min · avg 108 bpm · 278 kcal
        </div>
      </div>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span style={{ whiteSpace: "nowrap" }}>Exercises (optional)</span>
        <span style={{ fontSize: 9, color: C.primary, fontFamily: MONO, letterSpacing: ".06em", whiteSpace: "nowrap" }}>● TAP MIC</span>
      </div>
      <VoiceInput C={C} value={notes} onChange={setNotes}
        placeholder='"Bench 4x8 @ 185, OHP 3x8 @ 115, dips 3xBW…"' minHeight={90} />
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn C={C} full onClick={onClose}>Cancel</Btn>
        <Btn C={C} primary full onClick={() => { onAdd({ type, notes }); onClose(); }}>Save workout</Btn>
      </div>
    </Sheet>
  );
}

function ChatModal({ C, open, onClose }) {
  const [msgs, setMsgs] = useState(CHAT_SEED);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, thinking]);

  const send = () => {
    if (!input.trim()) return;
    const t = new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase().replace(" ", "");
    const next = [...msgs, { from: "me", t, text: input.trim() }];
    setMsgs(next);
    setInput("");
    setThinking(true);
    setTimeout(() => {
      const reply = pickReply(input);
      setMsgs([...next, { from: "coach", t, text: reply }]);
      setThinking(false);
    }, 900);
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} height="88%" title={null}>
      <div style={{ position: "sticky", top: 0, background: C.bg, padding: "4px 0 10px", marginTop: -6, zIndex: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 2px" }}>
          <div style={{
            width: 36, height: 36, borderRadius: 12,
            background: `linear-gradient(135deg, ${C.primary}, ${C.cyan})`,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: C.bg, fontWeight: 800, fontSize: 13,
          }}>AI</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.t }}>Coach</div>
            <div style={{ fontSize: 10, color: C.primary, fontFamily: MONO, fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: 3, background: C.primary, display: "inline-block" }} />
              ONLINE · reads all your data
            </div>
          </div>
          <button onClick={onClose} style={{
            background: C.s2, border: "none", color: C.t2, width: 30, height: 30,
            borderRadius: 15, cursor: "pointer", fontSize: 14,
          }}>✕</button>
        </div>
      </div>

      <div ref={scrollRef} style={{ padding: "6px 0 10px" }}>
        {msgs.map((m, i) => (
          <div key={i} style={{
            display: "flex", justifyContent: m.from === "me" ? "flex-end" : "flex-start",
            marginBottom: 8,
          }}>
            <div style={{
              maxWidth: "82%",
              background: m.from === "me" ? C.primary : C.s,
              color: m.from === "me" ? "#0a0a0a" : C.t,
              border: m.from === "me" ? "none" : `1px solid ${C.border}`,
              padding: "9px 13px", borderRadius: m.from === "me" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
              fontSize: 12.5, lineHeight: 1.5, fontWeight: m.from === "me" ? 600 : 500,
            }}>
              {m.text}
              <div style={{
                fontSize: 8.5, fontFamily: MONO,
                color: m.from === "me" ? "#0a0a0aa0" : C.t4,
                marginTop: 4, fontWeight: 500, textAlign: m.from === "me" ? "right" : "left",
              }}>{m.t}</div>
            </div>
          </div>
        ))}
        {thinking && (
          <div style={{ display: "flex", marginBottom: 8 }}>
            <div style={{
              background: C.s, border: `1px solid ${C.border}`, borderRadius: "16px 16px 16px 4px",
              padding: "10px 14px", display: "flex", gap: 4,
            }}>
              {[0,1,2].map(i => (
                <span key={i} style={{
                  width: 6, height: 6, borderRadius: 3, background: C.t3,
                  animation: `dot 1.2s ${i * 0.15}s infinite`,
                }} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Quick chips */}
      <div style={{ display: "flex", gap: 6, overflowX: "auto", padding: "2px 0 8px", marginBottom: 4 }}>
        {["Morning briefing", "What should I eat?", "Back check-in", "Weekly review"].map((q, i) => (
          <button key={i} onClick={() => { setInput(q); }} style={{
            flexShrink: 0, background: C.s2, border: `1px solid ${C.border}`,
            color: C.t2, padding: "6px 11px", borderRadius: 14, fontFamily: FONT,
            fontSize: 11, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
          }}>{q}</button>
        ))}
      </div>

      {/* Input */}
      <div style={{
        display: "flex", gap: 6, background: C.s, border: `1px solid ${C.border}`,
        borderRadius: 20, padding: 5, alignItems: "center",
      }}>
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          placeholder="Ask coach…"
          style={{
            flex: 1, background: "transparent", border: "none", outline: "none",
            padding: "8px 10px", color: C.t, fontFamily: FONT, fontSize: 13,
          }} />
        <MicButton C={C} onTranscript={(t) => setInput(t)} onAutosend={() => setTimeout(send, 80)} />
        <button onClick={send} style={{
          width: 34, height: 34, borderRadius: 16, border: "none",
          background: C.primary, color: "#0a0a0a", cursor: "pointer",
          fontSize: 16, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center",
        }}>↑</button>
      </div>
      <style>{`@keyframes dot { 0%,60%,100% { opacity: 0.3; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-3px); } }`}</style>
    </Sheet>
  );
}

function pickReply(q) {
  const s = q.toLowerCase();
  if (s.includes("morning") || s.includes("briefing")) {
    return "Morning. Recovery 82% green. HRV 49ms (+2%), RHR 60.5 (-5%), sleep 7h42m @ 91% eff. Cleared for moderate training. Target: strain 10–12, protein 180g, water 100oz. Eat on schedule — front-load protein early.";
  }
  if (s.includes("eat") || s.includes("food") || s.includes("meal")) {
    return "At 1,312 kcal and 108g P. With the gochujang bowl (380/36P), you'd hit 1,692 kcal and 144g P. Add one Oikos now (170/30P) = 174g. That still leaves 500 kcal headroom — a protein bar or extra chicken closes the gap comfortably.";
  }
  if (s.includes("back") || s.includes("pain")) {
    return "No flare-ups logged in 5 days. Current plan: avoid loaded squats/deadlifts, cap axial compression. Pull day and push day are safe. I'll flag if HRV drops with no training stimulus — usually means inflammation.";
  }
  if (s.includes("week") || s.includes("review")) {
    return "This week: 5 sessions, 69 total strain, 3h 11m training. Sleep averaged 7h 14m. Protein hit 3/7 days (Fri–Sun gap, Mon 242g rebound). Weight steady at 169. Recommendation next week: 4 quality sessions, 1 mobility, and fix the weekend protein hole.";
  }
  return "Checking your logs… Based on current data: HRV 49, sleep solid, protein short by 72g, water at 36oz. What specifically do you want me to look at?";
}

// ─── RING DETAIL SHEET ──────────────────────────────────────────
function RingDetailSheet({ C, open, onClose, which }) {
  if (!which) return <Sheet C={C} open={open} onClose={onClose} />;
  if (which === "primer") return <PrimerSheet C={C} open={open} onClose={onClose} />;

  const configs = {
    recovery: {
      title: "Recovered · 82%",
      color: C.primary,
      hero: "82",
      heroUnit: "%",
      what: "How ready your body is, on a 0–100 scale.",
      blurb: "Built mostly from how much your heart-rate varies (HRV), how hard your heart's working at rest, and how well you slept. 82% means you bounced back — push day is fair game.",
      rows: [
        { k: "HRV · nervous system", v: "49 ms", sub: "higher = more rested", w: "main driver", col: C.primary },
        { k: "Resting pulse",        v: "60.5 bpm", sub: "lower than usual = good", w: "supporting", col: C.primary },
        { k: "Sleep last night",     v: "88%",   sub: "7h 42m, solid", w: "supporting", col: C.primary },
        { k: "Breath rate",          v: "14 /min", sub: "steady = no strain", w: "minor", col: C.primary },
      ],
    },
    strain: {
      title: "Effort today",
      color: C.warn,
      hero: "4.2",
      heroUnit: "/21",
      what: "How hard you've pushed your heart today.",
      blurb: "A 0–21 score of total cardiovascular work — time at elevated heart rate, basically. 4.2 so far is light. Tonight's planned push should put you around 12.7. Aim for 14–17 on green-recovery days.",
      rows: [
        { k: "Calories burned", v: "312 kcal", sub: "day so far", w: "", col: C.warn },
        { k: "Average heart rate", v: "78 bpm", sub: "over 24h", w: "", col: C.warn },
        { k: "Minutes above 120 bpm", v: "42 min", sub: "counts as real effort", w: "", col: C.warn },
        { k: "Projected end of day", v: "~12.7", sub: "if you hit the planned push", w: "", col: C.warn },
      ],
    },
    sleep: {
      title: "Sleep last night",
      color: C.cyan,
      hero: "7:42",
      heroUnit: "",
      what: "How much and how well you slept.",
      blurb: "You slept 7h 42m — just over what your body needed. 91% of that was actually asleep (not tossing). Deep and dream sleep both hit healthy ranges. One watch-out: you went to bed at 11:48pm — a bit late if you repeat it.",
      rows: [
        { k: "Total time asleep", v: "7h 42m", sub: "needed 7h 30m", w: "", col: C.cyan },
        { k: "Sleep efficiency", v: "91%",  sub: "how still you were", w: "good >90%", col: C.cyan },
        { k: "Deep sleep",        v: "1h 18m", sub: "physical recovery",  w: "healthy", col: "#3b5cff" },
        { k: "Dream sleep (REM)", v: "1h 52m", sub: "memory & mood",      w: "healthy", col: C.purple },
      ],
    },
  };
  const cfg = configs[which];

  return (
    <Sheet C={C} open={open} onClose={onClose} title={cfg.title} height="78%">
      <div style={{ textAlign: "center", padding: "12px 0 10px" }}>
        <div style={{ fontSize: 56, fontWeight: 800, color: cfg.color, fontFamily: MONO, letterSpacing: "-.05em", lineHeight: 1 }}>
          {cfg.hero}<span style={{ fontSize: 20, color: C.t3 }}>{cfg.heroUnit}</span>
        </div>
      </div>
      <div style={{ fontSize: 11, color: cfg.color, textAlign: "center", textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, marginBottom: 8 }}>
        {cfg.what}
      </div>
      <div style={{ fontSize: 12.5, color: C.t2, lineHeight: 1.6, padding: "0 4px 16px", textAlign: "center" }}>
        {cfg.blurb}
      </div>
      <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, padding: "0 4px 8px" }}>
        What it's made of
      </div>
      {cfg.rows.map((r, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 10, padding: "12px 4px",
          borderBottom: i === cfg.rows.length - 1 ? "none" : `1px solid ${C.border}`,
        }}>
          <div style={{ width: 6, height: 6, borderRadius: 3, background: r.col, flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600 }}>{r.k}</div>
            <div style={{ fontSize: 10.5, color: C.t4, marginTop: 2 }}>{r.sub}</div>
          </div>
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 800, fontFamily: MONO, color: r.col, letterSpacing: "-.03em", whiteSpace: "nowrap" }}>{r.v}</div>
            {r.w && <div style={{ fontSize: 9, color: C.t4, fontFamily: MONO, marginTop: 1 }}>{r.w}</div>}
          </div>
        </div>
      ))}
    </Sheet>
  );
}

// ─── PRIMER SHEET — "what do these numbers mean?" ──────────────
function PrimerSheet({ C, open, onClose }) {
  const items = [
    {
      color: C.primary,
      icon: "●",
      term: "Recovery (82%)",
      plain: "How ready you are today. Think of it like a phone battery — 82% means you charged overnight.",
      details: "High = train hard if you want. Low = take it easy, do mobility or a walk.",
    },
    {
      color: C.primary,
      icon: "♡",
      term: "HRV — your #1 metric",
      plain: "Heart Rate Variability. How much the time between heartbeats varies. Sounds weird, but more variation = more rested.",
      details: "When you're stressed, tired, or hungover, your heart beats more like a metronome. When you're fresh, the spacing jitters — that's good. This is the main number driving your recovery score.",
    },
    {
      color: C.primary,
      icon: "♥",
      term: "Resting heart rate",
      plain: "How hard your heart works when you're lying still. Lower is better (means it's efficient).",
      details: "Your usual is ~64 bpm. Today is 60.5 — one of your best.",
    },
    {
      color: C.warn,
      icon: "◆",
      term: "Strain / Effort (0–21)",
      plain: "A score of how hard you pushed your heart today. Logarithmic — 10 is moderate, 15 is hard, 18+ is very hard.",
      details: "We recommend a range based on your recovery. Green day → push (14–17). Yellow → keep it chill (8–12). Red → rest (<8).",
    },
    {
      color: C.cyan,
      icon: "☾",
      term: "Sleep quality",
      plain: "Not just hours in bed — how still you were, plus how much deep + dream sleep you got.",
      details: "88% means most of your time in bed was actually asleep. Deep sleep rebuilds the body; dream sleep (REM) consolidates memory + mood.",
    },
    {
      color: C.cyan,
      icon: "⌚",
      term: "Sleep need",
      plain: "How much sleep your body needs tonight, given recent debt and today's effort.",
      details: "More debt + harder day = a bigger number. Hit it consistently and recovery climbs.",
    },
  ];

  return (
    <Sheet C={C} open={open} onClose={onClose} title="The numbers, explained" height="88%">
      <div style={{ fontSize: 12, color: C.t3, lineHeight: 1.55, marginBottom: 16 }}>
        No jargon. Here's what each one actually means and why you'd care.
      </div>
      {items.map((it, i) => (
        <div key={i} style={{
          marginBottom: 10, background: C.s, border: `1px solid ${C.border}`,
          borderRadius: 14, padding: 14,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{
              width: 30, height: 30, borderRadius: 9, background: it.color + "18",
              color: it.color, display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 15, fontWeight: 800, flexShrink: 0,
            }}>{it.icon}</div>
            <div style={{ fontSize: 14, color: C.t, fontWeight: 700, letterSpacing: "-.01em" }}>{it.term}</div>
          </div>
          <div style={{ fontSize: 12.5, color: C.t, lineHeight: 1.55, fontWeight: 500 }}>
            {it.plain}
          </div>
          <div style={{ fontSize: 11.5, color: C.t3, lineHeight: 1.55, marginTop: 6 }}>
            {it.details}
          </div>
        </div>
      ))}
      <div style={{
        marginTop: 6, padding: 12, background: C.s2, borderRadius: 12,
        fontSize: 11.5, color: C.t2, lineHeight: 1.55,
      }}>
        <span style={{ fontWeight: 700, color: C.t }}>Rule of thumb:</span> if all three rings are green-ish, it's a push day. If any is red, that's your hint to rest.
      </div>
    </Sheet>
  );
}

Object.assign(window, { LogMealModal, LogWorkoutModal, ChatModal, RingDetailSheet });
