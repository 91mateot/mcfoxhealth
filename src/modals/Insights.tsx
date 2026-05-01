import { useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import { Sheet } from "../components/Sheet";
import { Panel } from "../components/Panel";
import { SectionHead } from "../components/SectionHead";
import { Chip } from "../components/Chip";
import { InsightCard } from "../components/InsightCard";
import { Scatterplot } from "../components/Scatterplot";
import { useInsights } from "../api";
import type { Correlation, NumericCorrelation } from "../types";
import { JOURNAL_TAGS } from "../types";

interface InsightsModalProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
}

/** Insights modal — surfaces numeric Pearson correlations with scatterplots and
 * natural-language cards, plus the existing journal-tag correlations. Reuses
 * the bottom-sheet pattern. Fetches /api/insights when opened. */
export function InsightsModal({ C, open, onClose }: InsightsModalProps) {
  // SWR key is gated on `open` so we only hit the API when the modal is up.
  const { data, error, isLoading } = useInsights(open);
  const [detail, setDetail] = useState<NumericCorrelation | null>(null);

  const numeric = data?.numeric ?? [];
  const journal = data?.journal ?? [];
  // Top cards: skip "none"-confidence pairs — they have no actionable signal.
  const top3 = numeric.filter((c) => c.confidence !== "none").slice(0, 3);

  return (
    <>
      <Sheet C={C} open={open && detail === null} onClose={onClose} title="Insights" height="92%">
        {error && (
          <Panel C={C}>
            <div style={{ fontSize: 12, color: C.warn, lineHeight: 1.5 }}>
              Couldn't load insights. Pull down or try again in a moment.
            </div>
          </Panel>
        )}

        {isLoading && !data && (
          <div style={{ padding: "30px 4px", textAlign: "center", fontSize: 12, color: C.t3, fontFamily: MONO, letterSpacing: ".1em" }}>
            LOADING…
          </div>
        )}

        {data && numeric.length === 0 && journal.length === 0 && (
          <Panel C={C}>
            <div style={{ fontSize: 13, color: C.t2, lineHeight: 1.55, textAlign: "center", padding: "16px 4px" }}>
              No patterns yet. Insights need at least 10 days of logged meals, sleep, and journal
              entries to find anything reliable. Check back after a couple of weeks.
            </div>
          </Panel>
        )}

        {top3.length > 0 && (
          <>
            <SectionHead
              C={C}
              kicker="Top signals"
              title="What your data says"
              right={<Chip C={C} color={C.primary}>numeric</Chip>}
            />
            <div>
              {top3.map((c) => (
                <InsightCard key={`${c.tag}:${c.outcome}`} C={C} c={c} onClick={() => setDetail(c)} />
              ))}
            </div>
          </>
        )}

        {numeric.length > 0 && (
          <>
            <SectionHead C={C} kicker="Scatterplots" title="Every pair" />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
              {numeric.map((c) => (
                <ScatterTile key={`${c.tag}:${c.outcome}`} C={C} c={c} onOpen={() => setDetail(c)} />
              ))}
            </div>
          </>
        )}

        {journal.length > 0 && (
          <>
            <SectionHead
              C={C}
              kicker="Behavior → outcome"
              title="Journal patterns"
              right={<Chip C={C} color={C.primary}>from journal</Chip>}
            />
            <Panel C={C} style={{ padding: 4 }}>
              {journal.slice(0, 12).map((c, i) => (
                <JournalRow
                  key={`${c.tag}:${c.metric}`}
                  C={C}
                  c={c}
                  last={i === Math.min(journal.length, 12) - 1}
                />
              ))}
            </Panel>
          </>
        )}

        {data && (
          <div style={{ padding: "16px 4px 24px", fontSize: 11, color: C.t4, lineHeight: 1.55, fontFamily: MONO }}>
            Updated {formatComputedAt(data.computedAt)} · 60-day window · refreshes Sunday 6am PT.
          </div>
        )}
      </Sheet>

      <DetailSheet
        C={C}
        open={detail !== null}
        onClose={() => setDetail(null)}
        c={detail}
      />
    </>
  );
}

// ─── Scatterplot tile ──────────────────────────────────────────────


function ScatterTile({
  C,
  c,
  onOpen,
}: {
  C: Palette;
  c: NumericCorrelation;
  onOpen: () => void;
}) {
  const noSignal = c.confidence === "none";
  const expected = c.better === "up" ? c.r > 0 : c.r < 0;
  const col = noSignal ? C.t4 : expected ? C.primary : C.warn;

  return (
    <div
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      style={{
        background: C.s,
        border: `1px solid ${C.border}`,
        borderRadius: 16,
        padding: 10,
        cursor: "pointer",
        opacity: noSignal ? 0.55 : 1,
      }}
    >
      <div style={{ fontSize: 11, color: C.t3, textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 }}>
        {c.inputLabel} → {c.outcomeLabel}
      </div>
      <div style={{ marginTop: 6 }}>
        <Scatterplot
          points={c.points}
          color={col}
          slope={c.slope}
          intercept={c.intercept}
          axis={C.border}
          bg={C.s2}
          h={96}
        />
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 6 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: col, fontFamily: MONO, letterSpacing: "-.03em" }}>
          {c.r >= 0 ? "+" : ""}
          {c.r.toFixed(2)}
        </div>
        <div style={{ fontSize: 10, color: C.t4, fontFamily: MONO }}>n={c.n}</div>
      </div>
    </div>
  );
}

// ─── Detail drawer ─────────────────────────────────────────────────


function DetailSheet({
  C,
  open,
  onClose,
  c,
}: {
  C: Palette;
  open: boolean;
  onClose: () => void;
  c: NumericCorrelation | null;
}) {
  if (!c) {
    return <Sheet C={C} open={open} onClose={onClose} />;
  }
  const expected = c.better === "up" ? c.r > 0 : c.r < 0;
  const col = expected ? C.primary : C.warn;
  const confCol = c.confidence === "high" ? C.primary : c.confidence === "medium" ? C.yellow : C.t4;

  // Sort points by date for the table view — easier to scan.
  const sortedPoints = [...c.points].sort((a, b) => b.date.localeCompare(a.date));

  return (
    <Sheet C={C} open={open} onClose={onClose} title={`${c.inputLabel} → ${c.outcomeLabel}`} height="92%">
      <div style={{ padding: "4px 4px 12px" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: C.t, lineHeight: 1.5 }}>{c.insight}</div>
      </div>

      <Panel C={C}>
        <Scatterplot
          points={c.points}
          color={col}
          slope={c.slope}
          intercept={c.intercept}
          axis={C.border}
          bg={C.s2}
          h={180}
        />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: C.t4, fontFamily: MONO }}>
          <span>
            x: {c.inputLabel} ({c.inputUnits || "—"})
          </span>
          <span>
            y: {c.outcomeLabel} ({c.outcomeUnits || "—"})
          </span>
        </div>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
        <StatTile C={C} label="Pearson r" value={`${c.r >= 0 ? "+" : ""}${c.r.toFixed(2)}`} col={col} />
        <StatTile C={C} label="Sample size" value={`n=${c.n}`} col={C.t} />
        <StatTile C={C} label="Confidence" value={c.confidence.toUpperCase()} col={confCol} />
      </div>

      <div style={{ padding: "8px 4px 4px", fontSize: 11, color: C.t3, fontFamily: MONO, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>
        Days in window
      </div>
      <Panel C={C} style={{ padding: 0 }}>
        {sortedPoints.map((p, i) => (
          <div
            key={p.date + i}
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 10,
              padding: "9px 12px",
              borderBottom: i === sortedPoints.length - 1 ? "none" : `1px solid ${C.border}`,
            }}
          >
            <div style={{ fontSize: 11, color: C.t3, fontFamily: MONO, width: 80 }}>{p.date}</div>
            <div style={{ flex: 1, fontSize: 11, color: C.t2, fontFamily: MONO }}>
              {formatAxisValue(p.x, c.inputUnits)} {c.inputUnits}
            </div>
            <div style={{ fontSize: 11, color: col, fontFamily: MONO, fontWeight: 700 }}>
              {formatAxisValue(p.y, c.outcomeUnits)} {c.outcomeUnits}
            </div>
          </div>
        ))}
      </Panel>

      <div style={{ padding: "14px 4px 24px", fontSize: 11, color: C.t4, lineHeight: 1.55 }}>
        Pearson r measures how tightly two numbers track each other, from −1 (perfect opposite) through
        0 (unrelated) to +1 (perfect match). The dashed line is the best-fit trend through these{" "}
        {c.n} days.
      </div>
    </Sheet>
  );
}

function StatTile({ C, label, value, col }: { C: Palette; label: string; value: string; col: string }) {
  return (
    <div style={{ background: C.s, border: `1px solid ${C.border}`, borderRadius: 14, padding: "10px 10px" }}>
      <div style={{ fontSize: 10, color: C.t3, textTransform: "uppercase", letterSpacing: ".1em", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 15, fontWeight: 800, color: col, fontFamily: MONO, marginTop: 4, letterSpacing: "-.03em" }}>
        {value}
      </div>
    </div>
  );
}

// ─── Journal row (mirrors Progress.tsx's CorrelationRow) ───────────


function JournalRow({ C, c, last }: { C: Palette; c: Correlation; last: boolean }) {
  const tag = JOURNAL_TAGS.find((t) => t.id === c.tag);
  const col = c.direction === "positive" ? C.primary : C.warn;
  const arrow = c.effect > 0 ? "▲" : "▼";
  const confCol = c.confidence === "high" ? C.primary : c.confidence === "medium" ? C.yellow : C.t4;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "11px 12px",
        borderBottom: last ? "none" : `1px solid ${C.border}`,
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 10,
          flexShrink: 0,
          background: col + "15",
          border: `1px solid ${col}30`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 16,
        }}
      >
        {tag?.icon ?? "•"}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontSize: 12.5, color: C.t, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {tag?.label ?? c.tag}
          </span>
          <span style={{ fontSize: 11, color: C.t3, fontFamily: MONO, whiteSpace: "nowrap", flexShrink: 0 }}>
            → {c.metric}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
          <div
            style={{
              fontSize: 11,
              color: confCol,
              fontFamily: MONO,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: ".06em",
            }}
          >
            {c.confidence}
          </div>
          <div style={{ width: 3, height: 3, borderRadius: 2, background: C.t4, flexShrink: 0 }} />
          <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO }}>n={c.n}</div>
        </div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0, fontFamily: FONT }}>
        <div style={{ fontSize: 16, fontWeight: 800, fontFamily: MONO, color: col, letterSpacing: "-.04em", whiteSpace: "nowrap" }}>
          {arrow} {Math.abs(c.effect)}
          {c.unit === "%" ? "%" : ""}
        </div>
        <div style={{ fontSize: 11, color: C.t4, fontFamily: MONO, whiteSpace: "nowrap" }}>
          {c.unit !== "%" ? c.unit : "effect"}
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────


function formatComputedAt(ts: string | null | undefined): string {
  if (!ts) return "recently";
  try {
    const d = new Date(ts);
    return d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return ts;
  }
}

function formatAxisValue(v: number, units: string): string {
  if (units === "%") return v.toFixed(1);
  if (units === "mg" || units === "g" || units === "oz") return Math.round(v).toString();
  if (units === "ms") return v.toFixed(1);
  if (units === "hrs") return v.toFixed(2);
  return v.toFixed(1);
}
