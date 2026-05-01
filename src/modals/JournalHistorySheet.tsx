import { useState } from "react";
import { MONO, type Palette } from "../theme";
import { JOURNAL_TAGS, type JournalEntry, type JournalTag } from "../types";
import { Sheet } from "../components/Sheet";
import { useJournalHistory } from "../api";

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
  const morning = entry.morning;
  const evening = entry.evening;

  const primaryTags = (morning?.tags || evening?.tags || [])
    .map((id) => JOURNAL_TAGS.find((t) => t.id === id))
    .filter(Boolean) as JournalTag[];
  const snippet =
    (morning?.text || "").trim() ||
    (evening?.text || "").trim() ||
    firstPromptAnswer(morning?.prompts) ||
    firstPromptAnswer(evening?.prompts) ||
    "";

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
          {evening && <SlotBlock C={C} label="Evening" slot={evening} />}
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
