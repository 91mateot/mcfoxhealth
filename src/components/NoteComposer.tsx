import { useEffect, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import { JOURNAL_TAGS, type JournalNote, type JournalTag } from "../types";
import { VoiceInput } from "./VoiceInput";
import { Btn } from "./Btn";
import { Scale5 } from "./Scale5";

export interface NoteDraft {
  text: string;
  at?: string;
  tags?: string[];
  mood?: number | null;
  stress?: number | null;
}

interface NoteComposerProps {
  C: Palette;
  /** YYYY-MM-DD in local TZ — the date the note belongs to. */
  date: string;
  /** "today" | "past" — drives default time and whether the time picker is surfaced by default. */
  dateMode: "today" | "past";
  /** When editing, seed from an existing note. */
  initial?: JournalNote;
  onSubmit: (draft: NoteDraft) => void | Promise<void>;
  onCancel: () => void;
  /** Primary button label override — defaults to "Add note" / "Save note". */
  submitLabel?: string;
  /** When true the optional chips/scales row is expanded by default. */
  defaultExpanded?: boolean;
}

/** Tags available on a mid-day note — same vocabulary as evening, since
 * supplements and sleep-behavior aren't the point of an in-the-moment capture. */
const NOTE_TAG_IDS = new Set([
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

const NOTE_TAGS: JournalTag[] = JOURNAL_TAGS.filter((t) => NOTE_TAG_IDS.has(t.id));

export function NoteComposer({
  C,
  date,
  dateMode,
  initial,
  onSubmit,
  onCancel,
  submitLabel,
  defaultExpanded,
}: NoteComposerProps) {
  const [text, setText] = useState(initial?.text ?? "");
  const [tags, setTags] = useState<Set<string>>(new Set(initial?.tags ?? []));
  const [mood, setMood] = useState<number | null>(initial?.mood ?? null);
  const [stress, setStress] = useState<number | null>(initial?.stress ?? null);
  const [at, setAt] = useState<string>(() =>
    initial?.at ? isoToLocalInput(initial.at) : defaultAtForDate(date, dateMode),
  );
  const [showTime, setShowTime] = useState(dateMode === "past" || Boolean(initial));
  const [expanded, setExpanded] = useState(
    Boolean(defaultExpanded || initial?.tags?.length || initial?.mood || initial?.stress),
  );
  const [saving, setSaving] = useState(false);

  // Keep "now" fresh if the composer sits open on today's mode without the user touching the time.
  useEffect(() => {
    if (initial || showTime || dateMode !== "today") return;
    const id = window.setInterval(() => setAt(defaultAtForDate(date, dateMode)), 30_000);
    return () => window.clearInterval(id);
  }, [date, dateMode, initial, showTime]);

  const toggleTag = (id: string) => {
    const next = new Set(tags);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setTags(next);
  };

  const save = async () => {
    const clean = text.trim();
    if (!clean) return;
    setSaving(true);
    try {
      await onSubmit({
        text: clean,
        at: localInputToIso(at, date),
        tags: tags.size ? Array.from(tags) : undefined,
        mood,
        stress,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        background: C.s2,
        border: `1px solid ${C.border}`,
        borderRadius: 14,
        padding: 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, gap: 8 }}>
        <div
          style={{
            fontSize: 10,
            color: C.t4,
            textTransform: "uppercase",
            letterSpacing: ".14em",
            fontWeight: 700,
          }}
        >
          {initial ? "Edit note" : "New note"}
        </div>
        <TimeDisplay
          C={C}
          at={at}
          dateMode={dateMode}
          showInput={showTime}
          onToggle={() => setShowTime((v) => !v)}
          onChange={(v) => setAt(v)}
          date={date}
        />
      </div>

      <VoiceInput
        C={C}
        value={text}
        onChange={setText}
        placeholder={
          dateMode === "past"
            ? "Write (or voice) what happened then…"
            : "Say what's on your mind right now — anything the day just surfaced."
        }
        minHeight={72}
      />

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{
          all: "unset",
          cursor: "pointer",
          marginTop: 10,
          fontSize: 11,
          color: C.t4,
          fontFamily: MONO,
          letterSpacing: ".08em",
        }}
      >
        {expanded ? "▾ fewer options" : "▸ add mood, stress, tags"}
      </button>

      {expanded && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
            <Scale5 C={C} label="Mood" val={mood} set={setMood} good="high" />
            <Scale5 C={C} label="Stress" val={stress} set={setStress} good="low" />
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {NOTE_TAGS.map((t) => {
              const active = tags.has(t.id);
              const col = t.negative ? C.warn : C.primary;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggleTag(t.id)}
                  aria-pressed={active}
                  style={{
                    fontSize: 11,
                    color: active ? col : C.t2,
                    background: active ? col + "18" : C.s2,
                    border: `1px solid ${active ? col + "60" : C.border}`,
                    padding: "6px 10px",
                    borderRadius: 16,
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
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Btn C={C} onClick={onCancel} full>
          Cancel
        </Btn>
        <Btn C={C} primary full onClick={save} disabled={saving || !text.trim()}>
          {saving ? "Saving…" : submitLabel || (initial ? "Save note" : "Add note")}
        </Btn>
      </div>
    </div>
  );
}

function TimeDisplay({
  C,
  at,
  dateMode,
  showInput,
  onToggle,
  onChange,
  date,
}: {
  C: Palette;
  at: string;
  dateMode: "today" | "past";
  showInput: boolean;
  onToggle: () => void;
  onChange: (v: string) => void;
  date: string;
}) {
  if (showInput) {
    return (
      <input
        type="datetime-local"
        value={at}
        min={`${date}T00:00`}
        max={`${date}T23:59`}
        onChange={(e) => onChange(e.target.value)}
        style={{
          background: C.s,
          color: C.t,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: "4px 6px",
          fontSize: 11,
          fontFamily: MONO,
        }}
      />
    );
  }
  const label = dateMode === "today" ? `now · ${humanTime(at)}` : humanTime(at);
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{
        all: "unset",
        cursor: "pointer",
        fontSize: 11,
        color: C.t3,
        fontFamily: MONO,
        letterSpacing: ".06em",
      }}
    >
      {label} <span style={{ color: C.t4 }}>· change</span>
    </button>
  );
}

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

function defaultAtForDate(date: string, mode: "today" | "past"): string {
  if (mode === "today") {
    const now = new Date();
    return `${date}T${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
  }
  // Past day: default to 12:00 local, the user opts in to pick a specific time.
  return `${date}T12:00`;
}

function isoToLocalInput(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}T${pad2(dt.getHours())}:${pad2(dt.getMinutes())}`;
}

function localInputToIso(value: string, fallbackDate: string): string {
  if (!value) {
    const fallback = new Date(`${fallbackDate}T12:00`);
    return fallback.toISOString();
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return new Date(`${fallbackDate}T12:00`).toISOString();
  }
  return dt.toISOString();
}

function humanTime(localValue: string): string {
  // localValue is either a YYYY-MM-DDTHH:mm string or empty; keep it short.
  const parts = localValue.split("T");
  if (parts.length !== 2) return localValue;
  return parts[1];
}
