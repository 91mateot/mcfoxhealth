import { useState } from "react";
import { MONO, type Palette } from "../theme";
import { JOURNAL_TAGS, type JournalEntry, type JournalNote, type JournalTag } from "../types";
import { Sheet } from "../components/Sheet";
import { NoteComposer, type NoteDraft } from "../components/NoteComposer";
import {
  deleteJournalNote,
  submitJournal,
  todayISO,
  updateJournalNote,
  useJournalHistory,
} from "../api";

interface Props {
  C: Palette;
  open: boolean;
  onClose: () => void;
}

export function JournalHistorySheet({ C, open, onClose }: Props) {
  const { data, error, isLoading } = useJournalHistory(open);
  const entries = data?.entries ?? [];

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Journal · past entries" height="92%">
      {error && (
        <div style={{ fontSize: 12, color: C.warn, marginBottom: 12 }}>Couldn't load history.</div>
      )}
      {isLoading && entries.length === 0 && (
        <div
          style={{
            fontSize: 11,
            color: C.t4,
            fontFamily: MONO,
            letterSpacing: ".1em",
            padding: "40px 0",
            textAlign: "center",
          }}
        >
          LOADING…
        </div>
      )}
      {!isLoading && entries.length === 0 && !error && (
        <div style={{ fontSize: 12, color: C.t3, lineHeight: 1.5, padding: "20px 0" }}>
          No entries yet. Morning check-in + evening reflection build up here.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {entries.map((e) => (
          <EntryRow key={e.date} C={C} entry={e} />
        ))}
      </div>
    </Sheet>
  );
}

function EntryRow({ C, entry }: { C: Palette; entry: JournalEntry }) {
  const [expanded, setExpanded] = useState(false);
  const [composerMode, setComposerMode] = useState<"closed" | "new" | string>("closed");
  const morning = entry.morning;
  const evening = entry.evening;
  const notes = entry.notes ?? [];
  const sortedNotes = [...notes].sort((a, b) => (a.at || "").localeCompare(b.at || ""));
  const isToday = entry.date === todayISO();

  const primaryTags = (morning?.tags || evening?.tags || [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean) as JournalTag[];
  const snippet =
    (morning?.text || "").trim() ||
    (evening?.text || "").trim() ||
    firstPromptAnswer(morning?.prompts) ||
    firstPromptAnswer(evening?.prompts) ||
    (sortedNotes[0]?.text || "").trim() ||
    "";

  const handleAdd = async (draft: NoteDraft) => {
    await submitJournal({ slot: "note", date: entry.date, ...draft });
    setComposerMode("closed");
  };
  const handleEdit = async (id: string, draft: NoteDraft) => {
    await updateJournalNote({ date: entry.date, id, ...draft });
    setComposerMode("closed");
  };
  const handleDelete = async (id: string) => {
    if (!window.confirm("Delete this note?")) return;
    await deleteJournalNote(entry.date, id);
  };

  const moodFor = morning?.mood ?? evening?.mood ?? null;
  const dotColor = moodDotColor(C, moodFor);

  return (
    <div
      style={{
        background: C.s,
        border: `1px solid ${C.border}`,
        borderRadius: 14,
        padding: 12,
      }}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          all: "unset",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
        }}
      >
        <div
          aria-label={moodFor ? `mood ${moodFor}/5` : "no mood"}
          style={{
            width: 10,
            height: 10,
            borderRadius: 5,
            background: dotColor,
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, color: C.t2, fontFamily: MONO, letterSpacing: ".05em" }}>
            {formatDate(entry.date)}
          </div>
          {snippet && (
            <div
              style={{
                fontSize: 12.5,
                color: C.t,
                marginTop: 3,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {snippet}
            </div>
          )}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>{expanded ? "−" : "+"}</div>
      </button>
      {primaryTags.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
          {primaryTags.slice(0, 6).map((t) => (
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
          ))}
          {primaryTags.length > 6 && (
            <span style={{ fontSize: 10.5, color: C.t4, padding: "3px 4px" }}>
              +{primaryTags.length - 6}
            </span>
          )}
        </div>
      )}
      {expanded && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
          {morning && <SlotBlock C={C} label="Morning" slot={morning} />}
          {sortedNotes.length > 0 && (
            <div style={{ marginBottom: 10 }}>
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
                Notes
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {sortedNotes.map((n) =>
                  composerMode === n.id ? (
                    <NoteComposer
                      key={n.id}
                      C={C}
                      date={entry.date}
                      dateMode={isToday ? "today" : "past"}
                      initial={n}
                      onSubmit={(draft) => handleEdit(n.id, draft)}
                      onCancel={() => setComposerMode("closed")}
                    />
                  ) : (
                    <NoteRow
                      key={n.id}
                      C={C}
                      note={n}
                      onEdit={() => setComposerMode(n.id)}
                      onDelete={() => handleDelete(n.id)}
                    />
                  ),
                )}
              </div>
            </div>
          )}
          {evening && <SlotBlock C={C} label="Evening" slot={evening} />}

          {composerMode === "new" ? (
            <NoteComposer
              C={C}
              date={entry.date}
              dateMode={isToday ? "today" : "past"}
              onSubmit={handleAdd}
              onCancel={() => setComposerMode("closed")}
            />
          ) : (
            <button
              type="button"
              onClick={() => setComposerMode("new")}
              style={{
                all: "unset",
                cursor: "pointer",
                marginTop: 6,
                fontSize: 11,
                color: C.primary,
                fontFamily: MONO,
                letterSpacing: ".08em",
                fontWeight: 700,
              }}
            >
              + add note to this day
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function NoteRow({
  C,
  note,
  onEdit,
  onDelete,
}: {
  C: Palette;
  note: JournalNote;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const tagObjs = (note.tags ?? [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean) as JournalTag[];
  const dt = note.at ? new Date(note.at) : null;
  const hhmm = dt && !Number.isNaN(dt.getTime())
    ? `${dt.getHours().toString().padStart(2, "0")}:${dt.getMinutes().toString().padStart(2, "0")}`
    : "";
  return (
    <div
      style={{
        background: C.s2,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: "8px 10px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 10, color: C.t4, fontFamily: MONO, letterSpacing: ".06em" }}>{hhmm}</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={onEdit}
            style={{ all: "unset", cursor: "pointer", fontSize: 10, color: C.t3, fontFamily: MONO }}
          >
            edit
          </button>
          <button
            type="button"
            onClick={onDelete}
            style={{ all: "unset", cursor: "pointer", fontSize: 10, color: C.warn, fontFamily: MONO }}
          >
            delete
          </button>
        </div>
      </div>
      <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.4, marginTop: 4 }}>
        "{note.text}"
      </div>
      {(tagObjs.length > 0 || note.mood !== undefined || note.stress !== undefined) && (
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
          {note.mood !== undefined && note.mood !== null && (
            <span style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>mood {note.mood}/5</span>
          )}
          {note.stress !== undefined && note.stress !== null && (
            <span style={{ fontSize: 10, color: C.t3, fontFamily: MONO }}>stress {note.stress}/5</span>
          )}
        </div>
      )}
    </div>
  );
}

function SlotBlock({
  C,
  label,
  slot,
}: {
  C: Palette;
  label: string;
  slot: NonNullable<JournalEntry["morning"]> | NonNullable<JournalEntry["evening"]>;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
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
        {label}
      </div>
      {(slot.mood !== null && slot.mood !== undefined) ||
      (slot.stress !== null && slot.stress !== undefined) ||
      ("soreness" in slot && slot.soreness !== null && slot.soreness !== undefined) ? (
        <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, marginBottom: 6 }}>
          {slot.mood !== null && slot.mood !== undefined && `mood ${slot.mood}/5  `}
          {slot.stress !== null && slot.stress !== undefined && `stress ${slot.stress}/5  `}
          {"soreness" in slot && slot.soreness !== null && slot.soreness !== undefined && `soreness ${slot.soreness}/5`}
        </div>
      ) : null}
      {slot.text && (
        <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.5, marginBottom: 6 }}>
          "{slot.text}"
        </div>
      )}
      {slot.prompts?.map((p, i) => (
        <div key={i} style={{ marginTop: 6 }}>
          <div style={{ fontSize: 11, color: C.t3, fontWeight: 600, lineHeight: 1.4 }}>{p.q}</div>
          {p.a && (
            <div style={{ fontSize: 12, color: C.t2, lineHeight: 1.5, marginTop: 2 }}>{p.a}</div>
          )}
        </div>
      ))}
    </div>
  );
}

function firstPromptAnswer(prompts?: { q: string; a: string }[]): string {
  if (!prompts) return "";
  for (const p of prompts) {
    if ((p.a || "").trim()) return p.a.trim();
  }
  return "";
}

function moodDotColor(C: Palette, mood: number | null | undefined): string {
  if (mood === null || mood === undefined) return C.s4;
  if (mood >= 4) return C.primary;
  if (mood <= 2) return C.warn;
  return C.yellow;
}

function formatDate(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  const [y, m, d] = parts.map((p) => parseInt(p, 10));
  const dt = new Date(y, (m || 1) - 1, d || 1);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const short = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return `${short[dt.getDay()]} · ${months[dt.getMonth()]} ${dt.getDate()}`;
}
