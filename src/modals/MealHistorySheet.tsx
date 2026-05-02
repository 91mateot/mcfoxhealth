import { useState } from "react";
import { MONO, type Palette } from "../theme";
import type { NutritionHistoryDay } from "../types";
import { Sheet } from "../components/Sheet";
import { formatMealTime, useNutritionHistory } from "../api";

interface Props {
  C: Palette;
  open: boolean;
  onClose: () => void;
}

export function MealHistorySheet({ C, open, onClose }: Props) {
  const { data, error, isLoading } = useNutritionHistory(open);
  const days = data?.days ?? [];

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Meals · past 7 days" height="92%">
      {error && (
        <div style={{ fontSize: 12, color: C.warn, marginBottom: 12 }}>Couldn't load history.</div>
      )}
      {isLoading && days.length === 0 && (
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
      {!isLoading && days.length === 0 && !error && (
        <div style={{ fontSize: 12, color: C.t3, lineHeight: 1.5, padding: "20px 0" }}>
          No meals logged in the last week.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {days.map((d) => (
          <DayRow key={d.date} C={C} day={d} />
        ))}
      </div>
    </Sheet>
  );
}

function DayRow({ C, day }: { C: Palette; day: NutritionHistoryDay }) {
  const [expanded, setExpanded] = useState(false);
  const count = day.meals.length;
  const cal = Math.round(day.totals.cal);
  const p = Math.round(day.totals.p);

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
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, color: C.t2, fontFamily: MONO, letterSpacing: ".05em" }}>
            {formatDate(day.date)}
          </div>
          <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 3 }}>
            {count} {count === 1 ? "meal" : "meals"} · {cal} kcal · {p}g P · {day.water} oz water
          </div>
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>{expanded ? "−" : "+"}</div>
      </button>
      {expanded && count > 0 && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
          {day.meals.map((m) => (
            <div
              key={String(m.id)}
              style={{
                display: "flex",
                gap: 10,
                padding: "8px 0",
                borderBottom: `1px solid ${C.border}`,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  color: C.t4,
                  fontFamily: MONO,
                  minWidth: 54,
                }}
              >
                {m.time ? formatMealTime(m.time) : "—"}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: C.t, fontWeight: 600 }}>{m.name}</div>
                <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, marginTop: 2 }}>
                  {Math.round(m.cal)} kcal · {Math.round(m.p)}g P · {Math.round(m.c)}g C · {Math.round(m.f)}g F
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {expanded && count === 0 && (
        <div style={{ marginTop: 10, fontSize: 12, color: C.t3, lineHeight: 1.5 }}>
          Nothing logged.
        </div>
      )}
    </div>
  );
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
