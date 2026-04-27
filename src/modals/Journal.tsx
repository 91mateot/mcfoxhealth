import { useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import { JOURNAL_TAGS, type JournalTag } from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";

interface JournalSheetProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  onSave: (data: { tags: string[]; mood: number | null; stress: number | null; soreness: number | null }) => void;
}

const CATS: { id: JournalTag["cat"]; label: string }[] = [
  { id: "intake", label: "Intake" },
  { id: "sleep", label: "Sleep behavior" },
  { id: "body", label: "Body" },
  { id: "mind", label: "Mind" },
  { id: "context", label: "Context" },
];

export function JournalSheet({ C, open, onClose, onSave }: JournalSheetProps) {
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [mood, setMood] = useState<number | null>(null);
  const [stress, setStress] = useState<number | null>(null);
  const [soreness, setSoreness] = useState<number | null>(null);

  const toggle = (id: string) => {
    const next = new Set(sel);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSel(next);
  };

  const save = () => {
    onSave({ tags: Array.from(sel), mood, stress, soreness });
    setSel(new Set());
    setMood(null);
    setStress(null);
    setSoreness(null);
    onClose();
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Journal · last night" height="88%">
      <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, marginBottom: 14 }}>
        Tap anything that applied to last night. Data gets better after 14 days of logging.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 16 }}>
        <Scale5 C={C} label="Mood" val={mood} set={setMood} good="high" />
        <Scale5 C={C} label="Stress" val={stress} set={setStress} good="low" />
        <Scale5 C={C} label="Soreness" val={soreness} set={setSoreness} good="low" />
      </div>

      {CATS.map((cat) => {
        const tagsInCat = JOURNAL_TAGS.filter((t) => t.cat === cat.id);
        return (
          <div key={cat.id} style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".12em", fontWeight: 700, marginBottom: 8 }}>
              {cat.label}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {tagsInCat.map((t) => {
                const active = sel.has(t.id);
                const col = t.negative ? C.warn : C.primary;
                return (
                  <button
                    key={t.id}
                    onClick={() => toggle(t.id)}
                    aria-pressed={active}
                    style={{
                      fontSize: 11.5,
                      color: active ? col : C.t2,
                      background: active ? col + "18" : C.s2,
                      border: `1px solid ${active ? col + "60" : C.border}`,
                      padding: "7px 11px",
                      borderRadius: 18,
                      fontWeight: 600,
                      cursor: "pointer",
                      fontFamily: FONT,
                      transition: "all .15s ease",
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
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
        <Btn C={C} onClick={onClose} full>
          Skip
        </Btn>
        <Btn C={C} primary full onClick={save}>
          Save · {sel.size} tag{sel.size === 1 ? "" : "s"}
        </Btn>
      </div>
    </Sheet>
  );
}

function Scale5({
  C,
  label,
  val,
  set,
  good,
}: {
  C: Palette;
  label: string;
  val: number | null;
  set: (n: number) => void;
  good: "high" | "low";
}) {
  return (
    <div style={{ background: C.s2, borderRadius: 12, padding: "10px 10px" }}>
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700, marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: "flex", gap: 3, justifyContent: "space-between" }}>
        {[1, 2, 3, 4, 5].map((n) => {
          const active = val === n;
          const isGood = good === "high" ? n >= 4 : n <= 2;
          const isBad = good === "high" ? n <= 2 : n >= 4;
          const col = active ? (isGood ? C.primary : isBad ? C.warn : C.yellow) : C.s4;
          return (
            <button
              key={n}
              onClick={() => set(n)}
              aria-pressed={active}
              style={{
                flex: 1,
                height: 26,
                border: "none",
                borderRadius: 6,
                background: col,
                color: active ? C.bg : C.t3,
                fontSize: 11,
                fontWeight: 800,
                fontFamily: MONO,
                cursor: "pointer",
                transition: "all .15s ease",
              }}
            >
              {n}
            </button>
          );
        })}
      </div>
    </div>
  );
}
