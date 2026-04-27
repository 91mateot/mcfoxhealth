// Journal check-in card + Journal modal

// ─── TODAY CARD — Morning check-in ──────────────────────────────
function JournalCard({ C, onOpen }) {
  const { submitted, tags } = JOURNAL_TODAY;
  const lastTags = JOURNAL_LAST_NIGHT.tags.map(id => JOURNAL_TAGS.find(t => t.id === id)).filter(Boolean);

  return (
    <Panel C={C} style={{ background: submitted ? C.s : `linear-gradient(180deg, ${C.s}, ${C.primaryDim} 200%)`, borderColor: submitted ? C.border : C.primary + "30" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 10, color: C.primary, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, whiteSpace: "nowrap" }}>
            {submitted ? "Last night · logged" : "Morning check-in"}
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.t, marginTop: 3, letterSpacing: "-.01em" }}>
            {submitted ? "Nice — tags saved" : "Tag last night"}
          </div>
        </div>
        {!submitted && (
          <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>~20 sec</div>
        )}
      </div>

      {!submitted ? (
        <>
          <div style={{ fontSize: 11, color: C.t2, lineHeight: 1.5, marginBottom: 10 }}>
            Quick tags → after 2 weeks we'll show what actually moves your HRV.
          </div>
          {/* Preview chips */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            {["🍷 Alcohol", "☕ Late caffeine", "📱 Screens", "🧘 Meditated", "🔥 Sauna"].map((t, i) => (
              <div key={i} style={{
                fontSize: 10.5, color: C.t2, background: C.s2, border: `1px solid ${C.border}`,
                padding: "6px 10px", borderRadius: 18, fontWeight: 600,
              }}>{t}</div>
            ))}
            <div style={{
              fontSize: 10.5, color: C.t4, padding: "6px 10px", fontWeight: 600,
            }}>+{JOURNAL_TAGS.length - 5} more</div>
          </div>
          <Btn C={C} primary full onClick={onOpen}>Log last night</Btn>
        </>
      ) : (
        <>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {lastTags.map(t => (
              <div key={t.id} style={{
                fontSize: 10.5, color: t.negative ? C.warn : C.primary,
                background: (t.negative ? C.warn : C.primary) + "15",
                padding: "5px 9px", borderRadius: 14, fontWeight: 600,
                border: `1px solid ${(t.negative ? C.warn : C.primary)}30`,
              }}>{t.icon} {t.label}</div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: C.t4, marginTop: 10, fontFamily: MONO }}>
            Tap to edit → {JOURNAL_LAST_NIGHT.date}
          </div>
        </>
      )}
    </Panel>
  );
}

// ─── MORNING JOURNAL MODAL ──────────────────────────────────────
function JournalSheet({ C, open, onClose }) {
  const [sel, setSel] = useState(new Set());
  const [mood, setMood] = useState(null);
  const [stress, setStress] = useState(null);
  const [soreness, setSoreness] = useState(null);

  const toggle = (id) => {
    const next = new Set(sel);
    next.has(id) ? next.delete(id) : next.add(id);
    setSel(next);
  };

  const cats = [
    { id: "intake",  label: "Intake" },
    { id: "sleep",   label: "Sleep behavior" },
    { id: "body",    label: "Body" },
    { id: "mind",    label: "Mind" },
    { id: "context", label: "Context" },
  ];

  const save = () => {
    JOURNAL_TODAY.submitted = true;
    JOURNAL_TODAY.tags = [...sel];
    JOURNAL_TODAY.mood = mood;
    JOURNAL_TODAY.stress = stress;
    JOURNAL_TODAY.soreness = soreness;
    onClose();
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Journal · last night" height="88%">
      <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, marginBottom: 14 }}>
        Tap anything that applied to last night. Data gets better after 14 days of logging.
      </div>

      {/* Scales */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 16 }}>
        <Scale5 C={C} label="Mood" val={mood} set={setMood} good="high" />
        <Scale5 C={C} label="Stress" val={stress} set={setStress} good="low" />
        <Scale5 C={C} label="Soreness" val={soreness} set={setSoreness} good="low" />
      </div>

      {/* Tag categories */}
      {cats.map(cat => {
        const tagsInCat = JOURNAL_TAGS.filter(t => t.cat === cat.id);
        return (
          <div key={cat.id} style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, marginBottom: 8 }}>
              {cat.label}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {tagsInCat.map(t => {
                const active = sel.has(t.id);
                const col = t.negative ? C.warn : C.primary;
                return (
                  <button key={t.id} onClick={() => toggle(t.id)} style={{
                    fontSize: 11.5, color: active ? col : C.t2,
                    background: active ? col + "18" : C.s2,
                    border: `1px solid ${active ? col + "60" : C.border}`,
                    padding: "7px 11px", borderRadius: 18, fontWeight: 600,
                    cursor: "pointer", fontFamily: FONT,
                    transition: "all .15s ease",
                    display: "flex", alignItems: "center", gap: 4,
                  }}>
                    <span>{t.icon}</span>
                    <span>{t.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}

      <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
        <Btn C={C} onClick={onClose} full>Skip</Btn>
        <Btn C={C} primary full onClick={save}>Save · {sel.size} tag{sel.size === 1 ? "" : "s"}</Btn>
      </div>
    </Sheet>
  );
}

function Scale5({ C, label, val, set, good }) {
  // good=high means 5 is green, 1 is red. good=low means 1 is green, 5 is red.
  return (
    <div style={{ background: C.s2, borderRadius: 12, padding: "10px 10px" }}>
      <div style={{ fontSize: 9.5, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>{label}</div>
      <div style={{ display: "flex", gap: 3, justifyContent: "space-between" }}>
        {[1,2,3,4,5].map(n => {
          const active = val === n;
          const isGood = good === "high" ? n >= 4 : n <= 2;
          const isBad  = good === "high" ? n <= 2 : n >= 4;
          const col = active ? (isGood ? C.primary : isBad ? C.warn : C.yellow) : C.s4;
          return (
            <button key={n} onClick={() => set(n)} style={{
              flex: 1, height: 26, border: "none", borderRadius: 6,
              background: col, color: active ? C.bg : C.t3,
              fontSize: 11, fontWeight: 800, fontFamily: MONO, cursor: "pointer",
              transition: "all .15s ease",
            }}>{n}</button>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { JournalCard, JournalSheet });
