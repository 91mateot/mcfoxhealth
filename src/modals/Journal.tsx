import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import {
  JOURNAL_TAGS,
  type JournalEntry,
  type JournalNote,
  type JournalPrompt,
  type JournalSlot,
  type JournalTag,
} from "../types";
import { Sheet } from "../components/Sheet";
import { Btn } from "../components/Btn";
import { Scale5 } from "../components/Scale5";
import { VoiceInput } from "../components/VoiceInput";
import { NoteComposer, type NoteDraft } from "../components/NoteComposer";
import {
  deleteJournalNote,
  fetchJournalPrompts,
  submitJournal,
  todayISO,
  updateJournalNote,
  type JournalSubmission,
} from "../api";

interface JournalSheetProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  onSave: (data: JournalSubmission) => void | Promise<void>;
  /** Today's saved journal (if any) so evening mode can show morning as read-only
   * and re-opens pre-fill saved answers. */
  todayEntry?: JournalEntry | null;
  /** Raw tag list on today's journal row — used to pre-populate supplement
   * chips in the morning sheet even when Mateo hasn't done the full morning
   * check-in yet (he may have toggled supplements live from Fuel). */
  tagsToday?: string[];
}

const CATS: { id: JournalTag["cat"]; label: string }[] = [
  { id: "supplement", label: "Supplements" },
  { id: "intake", label: "Intake" },
  { id: "sleep", label: "Sleep behavior" },
  { id: "body", label: "Body" },
  { id: "mind", label: "Mind" },
  { id: "context", label: "Context" },
];

// Evening tags are a curated subset focused on the day itself, not last night.
const EVENING_TAG_IDS = new Set([
  "alcohol",
  "caffeine_late",
  "ate_late",
  "heavy_meal",
  "hydrated",
  "meditated",
  "stretched",
  "sauna",
  "cold",
  "stress",
  "social",
  "travel",
  "sick",
  "back_flare",
]);

function currentSlot(): JournalSlot {
  const now = new Date();
  return now.getHours() >= 18 ? "evening" : "morning";
}

export function JournalSheet({ C, open, onClose, onSave, todayEntry, tagsToday }: JournalSheetProps) {
  const [slot, setSlot] = useState<JournalSlot>(() => currentSlot());
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [mood, setMood] = useState<number | null>(null);
  const [stress, setStress] = useState<number | null>(null);
  const [soreness, setSoreness] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [prompts, setPrompts] = useState<JournalPrompt[] | null>(null);
  const [promptsLoading, setPromptsLoading] = useState(false);

  // Reset/prefill whenever the sheet opens or slot flips. Pre-fill from the
  // matching saved slot so tapping the card mid-day is editable, not a
  // destructive re-save.
  useEffect(() => {
    if (!open) return;
    const nextSlot = currentSlot();
    setSlot(nextSlot);

    const saved = nextSlot === "evening" ? todayEntry?.evening : todayEntry?.morning;
    // For morning: fall back to the raw tag list on today's row so supplement
    // chips toggled live from Fuel stay selected here. For evening: use the
    // saved evening tags only.
    const seedTags =
      nextSlot === "evening"
        ? saved?.tags ?? []
        : saved?.tags ?? tagsToday ?? [];
    setSel(new Set(seedTags));
    setMood(saved?.mood ?? null);
    setStress(saved?.stress ?? null);
    setSoreness(nextSlot === "morning" ? (todayEntry?.morning?.soreness ?? null) : null);
    setText(saved?.text ?? "");
    setPrompts(saved?.prompts && saved.prompts.length > 0 ? saved.prompts : null);
  }, [open, todayEntry, tagsToday]);

  // Lazy-load coach-generated prompts when the sheet opens without cached ones.
  useEffect(() => {
    if (!open) return;
    if (prompts && prompts.length > 0) return;
    let cancelled = false;
    setPromptsLoading(true);
    fetchJournalPrompts(slot)
      .then((ps) => {
        if (cancelled) return;
        setPrompts(ps.map((p) => ({ q: p.q, a: p.a || "" })));
      })
      .catch(() => {
        if (cancelled) return;
        setPrompts([]);
      })
      .finally(() => {
        if (!cancelled) setPromptsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, slot]);

  const toggle = (id: string) => {
    const next = new Set(sel);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSel(next);
  };

  const save = () => {
    const filledPrompts = (prompts ?? []).filter((p) => (p.q || "").trim());
    const payload: JournalSubmission = {
      slot,
      tags: Array.from(sel),
      mood,
      stress,
      text: text.trim() || undefined,
      prompts: filledPrompts.length ? filledPrompts : undefined,
    };
    if (slot === "morning") {
      payload.soreness = soreness;
    }
    onSave(payload);
    onClose();
  };

  const title = slot === "evening" ? "Evening reflection" : "Journal · last night";
  const primaryCta = slot === "evening" ? "Save reflection" : "Save entry";
  const mood5Label = slot === "evening" ? "Mood · day" : "Mood";
  const stress5Label = slot === "evening" ? "Stress · day" : "Stress";
  const visibleCats = slot === "evening"
    ? CATS.filter((c) => c.id !== "sleep" && c.id !== "supplement")
    : CATS;

  const todayStr = todayISO();
  const notes = todayEntry?.notes ?? [];

  return (
    <Sheet C={C} open={open} onClose={onClose} title={title} height="92%">
      <SlotHeader C={C} slot={slot} todayEntry={todayEntry ?? null} />

      <TodaySoFar
        C={C}
        date={todayStr}
        morning={todayEntry?.morning ?? null}
        evening={todayEntry?.evening ?? null}
        notes={notes}
      />

      <div style={{ fontSize: 11, color: C.t3, lineHeight: 1.5, marginBottom: 14 }}>
        {slot === "evening"
          ? "Close out the day — tag what happened and answer the prompts."
          : "Tap anything that applied to last night. Data gets better after 14 days of logging."}
      </div>

      <PromptsSection
        C={C}
        prompts={prompts}
        loading={promptsLoading}
        onChange={(idx, a) => {
          setPrompts((prev) => {
            if (!prev) return prev;
            const next = prev.slice();
            next[idx] = { ...next[idx], a };
            return next;
          });
        }}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: slot === "morning" ? "repeat(3,1fr)" : "repeat(2,1fr)",
          gap: 8,
          marginBottom: 16,
        }}
      >
        <Scale5 C={C} label={mood5Label} val={mood} set={setMood} good="high" />
        <Scale5 C={C} label={stress5Label} val={stress} set={setStress} good="low" />
        {slot === "morning" && (
          <Scale5 C={C} label="Soreness" val={soreness} set={setSoreness} good="low" />
        )}
      </div>

      {visibleCats.map((cat) => {
        const tagsInCat = JOURNAL_TAGS.filter((t) => t.cat === cat.id).filter((t) =>
          slot === "evening" ? EVENING_TAG_IDS.has(t.id) : true,
        );
        if (tagsInCat.length === 0) return null;
        return (
          <div key={cat.id} style={{ marginBottom: 14 }}>
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

      <div style={{ marginTop: 10, marginBottom: 14 }}>
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
          Anything else?
        </div>
        <VoiceInput
          C={C}
          value={text}
          onChange={setText}
          placeholder={
            slot === "evening"
              ? "How did the day actually feel? Anything on your mind heading into tomorrow?"
              : "How's the body waking up? Anything on your mind?"
          }
          minHeight={80}
        />
      </div>

      <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
        <Btn C={C} onClick={onClose} full>
          Skip
        </Btn>
        <Btn C={C} primary full onClick={save}>
          {primaryCta}
        </Btn>
      </div>
    </Sheet>
  );
}

function SlotHeader({
  C,
  slot,
  todayEntry,
}: {
  C: Palette;
  slot: JournalSlot;
  todayEntry: JournalEntry | null;
}) {
  // In evening mode, show the morning entry read-only so the day's throughline
  // is visible while reflecting. Quiet design — this is reference, not edit.
  if (slot !== "evening") return null;
  const morning = todayEntry?.morning;
  if (!morning) return null;

  const tags = (morning.tags || [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean);

  return (
    <div
      style={{
        background: C.s2,
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "10px 12px",
        marginBottom: 14,
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: C.t4,
          textTransform: "uppercase",
          letterSpacing: ".12em",
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        This morning
      </div>
      {tags.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 6 }}>
          {tags.map((t) =>
            t ? (
              <span
                key={t.id}
                style={{
                  fontSize: 10.5,
                  color: t.negative ? C.warn : C.primary,
                  background: (t.negative ? C.warn : C.primary) + "15",
                  padding: "3px 7px",
                  borderRadius: 10,
                  fontWeight: 600,
                }}
              >
                {t.icon} {t.label}
              </span>
            ) : null,
          )}
        </div>
      )}
      {(morning.mood !== null || morning.stress !== null || morning.soreness !== null) && (
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, marginBottom: 4 }}>
          {morning.mood !== null && `mood ${morning.mood}/5  `}
          {morning.stress !== null && `stress ${morning.stress}/5  `}
          {morning.soreness !== null && `soreness ${morning.soreness}/5`}
        </div>
      )}
      {morning.text && (
        <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.4, marginTop: 4 }}>
          "{morning.text}"
        </div>
      )}
    </div>
  );
}

function PromptsSection({
  C,
  prompts,
  loading,
  onChange,
}: {
  C: Palette;
  prompts: JournalPrompt[] | null;
  loading: boolean;
  onChange: (idx: number, a: string) => void;
}) {
  if (loading && (!prompts || prompts.length === 0)) {
    return (
      <div
        style={{
          background: C.s2,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          padding: 12,
          marginBottom: 14,
          fontSize: 11,
          color: C.t4,
          fontFamily: MONO,
          letterSpacing: ".08em",
        }}
      >
        GENERATING PROMPTS…
      </div>
    );
  }
  if (!prompts || prompts.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
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
        Prompts
      </div>
      {prompts.map((p, i) => (
        <div key={i} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 12, color: C.t, fontWeight: 600, marginBottom: 6, lineHeight: 1.4 }}>
            {p.q}
          </div>
          <VoiceInput
            C={C}
            value={p.a}
            onChange={(v) => onChange(i, v)}
            placeholder="Type or tap the mic"
            minHeight={60}
          />
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Today-so-far timeline: morning → notes (chronological) → evening. Each
// note has an inline edit/delete affordance. A "+ Note" action opens an
// inline NoteComposer — the composer lives INSIDE the sheet so it doesn't
// collide with the morning/evening form state.
// ─────────────────────────────────────────────────────────────────────────

function TodaySoFar({
  C,
  date,
  morning,
  evening,
  notes,
}: {
  C: Palette;
  date: string;
  morning: JournalEntry["morning"];
  evening: JournalEntry["evening"];
  notes: JournalNote[];
}) {
  const [composerMode, setComposerMode] = useState<"closed" | "new" | string>("closed");
  const sortedNotes = [...(notes || [])].sort((a, b) => (a.at || "").localeCompare(b.at || ""));

  const hasAnything = morning || evening || sortedNotes.length > 0 || composerMode !== "closed";

  const handleAdd = async (draft: NoteDraft) => {
    await submitJournal({ slot: "note", date, ...draft });
    setComposerMode("closed");
  };

  const handleEdit = async (id: string, draft: NoteDraft) => {
    await updateJournalNote({ date, id, ...draft });
    setComposerMode("closed");
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("Delete this note?")) return;
    await deleteJournalNote(date, id);
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div
          style={{
            fontSize: 11,
            color: C.t3,
            textTransform: "uppercase",
            letterSpacing: ".12em",
            fontWeight: 700,
          }}
        >
          Today so far
        </div>
        <button
          type="button"
          onClick={() => setComposerMode(composerMode === "new" ? "closed" : "new")}
          style={{
            all: "unset",
            cursor: "pointer",
            fontSize: 11,
            color: C.primary,
            fontFamily: MONO,
            letterSpacing: ".06em",
            fontWeight: 700,
          }}
        >
          {composerMode === "new" ? "× close" : "+ note"}
        </button>
      </div>

      {composerMode === "new" && (
        <div style={{ marginBottom: 10 }}>
          <NoteComposer
            C={C}
            date={date}
            dateMode="today"
            onSubmit={handleAdd}
            onCancel={() => setComposerMode("closed")}
          />
        </div>
      )}

      {!hasAnything && composerMode === "closed" && (
        <div
          style={{
            background: C.s2,
            border: `1px dashed ${C.border}`,
            borderRadius: 12,
            padding: 12,
            fontSize: 11,
            color: C.t4,
            fontFamily: MONO,
            letterSpacing: ".04em",
            textAlign: "center",
          }}
        >
          NO ENTRIES YET TODAY
        </div>
      )}

      <Timeline C={C}>
        {morning && <TimelineItem C={C} label="Morning" time={morning.savedAt} text={morning.text} />}
        {sortedNotes.map((n) =>
          composerMode === n.id ? (
            <div key={n.id} style={{ marginLeft: 10, marginBottom: 10 }}>
              <NoteComposer
                C={C}
                date={date}
                dateMode="today"
                initial={n}
                onSubmit={(draft) => handleEdit(n.id, draft)}
                onCancel={() => setComposerMode("closed")}
              />
            </div>
          ) : (
            <TimelineItem
              key={n.id}
              C={C}
              label="Note"
              time={n.at}
              text={n.text}
              tags={n.tags}
              mood={n.mood ?? undefined}
              stress={n.stress ?? undefined}
              onEdit={() => setComposerMode(n.id)}
              onDelete={() => handleDelete(n.id)}
            />
          ),
        )}
        {evening && <TimelineItem C={C} label="Evening" time={evening.savedAt} text={evening.text} />}
      </Timeline>
    </div>
  );
}

function Timeline({ C, children }: { C: Palette; children: React.ReactNode }) {
  return (
    <div
      style={{
        borderLeft: `2px solid ${C.border}`,
        paddingLeft: 10,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {children}
    </div>
  );
}

function TimelineItem({
  C,
  label,
  time,
  text,
  tags,
  mood,
  stress,
  onEdit,
  onDelete,
}: {
  C: Palette;
  label: string;
  time: string | null | undefined;
  text?: string | null;
  tags?: string[];
  mood?: number;
  stress?: number;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  const tagObjs = (tags ?? [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean) as JournalTag[];
  return (
    <div
      style={{
        background: C.s,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: "8px 10px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
          <span
            style={{
              fontSize: 10,
              color: C.t4,
              textTransform: "uppercase",
              letterSpacing: ".12em",
              fontWeight: 700,
            }}
          >
            {label}
          </span>
          <span style={{ fontSize: 10, color: C.t3, fontFamily: MONO, letterSpacing: ".04em" }}>
            {formatRelative(time)}
          </span>
        </div>
        {(onEdit || onDelete) && (
          <div style={{ display: "flex", gap: 6 }}>
            {onEdit && (
              <button
                type="button"
                onClick={onEdit}
                style={{ all: "unset", cursor: "pointer", fontSize: 10, color: C.t3, fontFamily: MONO }}
              >
                edit
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                onClick={onDelete}
                style={{ all: "unset", cursor: "pointer", fontSize: 10, color: C.warn, fontFamily: MONO }}
              >
                delete
              </button>
            )}
          </div>
        )}
      </div>
      {text && (
        <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.4, marginTop: 4 }}>
          "{text}"
        </div>
      )}
      {(tagObjs.length > 0 || mood !== undefined || stress !== undefined) && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6, alignItems: "center" }}>
          {tagObjs.map((t) => (
            <span
              key={t.id}
              style={{
                fontSize: 10,
                color: t.negative ? C.warn : C.primary,
                background: (t.negative ? C.warn : C.primary) + "15",
                padding: "2px 6px",
                borderRadius: 8,
                fontWeight: 600,
              }}
            >
              {t.icon} {t.label}
            </span>
          ))}
          {mood !== undefined && (
            <span style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>mood {mood}/5</span>
          )}
          {stress !== undefined && (
            <span style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>stress {stress}/5</span>
          )}
        </div>
      )}
    </div>
  );
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  const hhmm = `${dt.getHours().toString().padStart(2, "0")}:${dt.getMinutes().toString().padStart(2, "0")}`;
  const diffMin = Math.round((Date.now() - dt.getTime()) / 60_000);
  if (diffMin < 1) return `now · ${hhmm}`;
  if (diffMin < 60) return `${diffMin}m ago · ${hhmm}`;
  const hrs = Math.round(diffMin / 60);
  if (hrs < 24) return `${hrs}h ago · ${hhmm}`;
  return hhmm;
}
