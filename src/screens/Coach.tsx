import { useEffect } from "react";
import { mutate } from "swr";
import { FONT, type Palette } from "../theme";
import type { TodayResponse } from "../types";
import { Panel } from "../components/Panel";
import { SectionHead } from "../components/SectionHead";

interface CoachScreenProps {
  C: Palette;
  today: TodayResponse;
  onOpenChat: (prompt?: string) => void;
}

export function CoachScreen({ C, today, onOpenChat }: CoachScreenProps) {
  // SWR's revalidateOnFocus only fires on browser-level focus, not tab
  // switches within the SPA. Explicit mutate on mount guarantees fresh data
  // whenever Mateo opens the Coach tab.
  useEffect(() => {
    mutate("/api/today");
  }, []);

  return (
    <div>
      <SectionHead C={C} kicker="AI briefings" title="Coach" />

      {today.coachInsights.map((ins, i) => {
        const col = ins.tag === "green" ? C.primary : ins.tag === "yellow" ? C.yellow : ins.tag === "blue" ? C.cyan : C.warn;
        return (
          <Panel key={i} C={C}>
            <div style={{ display: "flex", gap: 10 }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 10,
                  flexShrink: 0,
                  background: col + "20",
                  border: `1px solid ${col}40`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 16,
                }}
              >
                {ins.icon}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: C.t }}>{ins.title}</div>
                <div style={{ fontSize: 11.5, color: C.t2, marginTop: 5, lineHeight: 1.5 }}>{ins.body}</div>
              </div>
            </div>
          </Panel>
        );
      })}

      <button
        onClick={() => onOpenChat()}
        style={{
          width: "100%",
          background: C.primary,
          border: "none",
          color: "#0a0a0a",
          borderRadius: 18,
          padding: "14px 16px",
          marginTop: 4,
          fontFamily: FONT,
          fontSize: 14,
          fontWeight: 800,
          cursor: "pointer",
          letterSpacing: ".01em",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
        }}
      >
        💬 Ask Coach anything
      </button>

      <SectionHead C={C} kicker="Try asking" title="Daily commands" />
      <Panel C={C} style={{ padding: 10 }}>
        {[
          "Morning briefing",
          "End of day report",
          "Weekly review",
          "What should I eat next?",
          "Am I cleared to train?",
          "What's my protein gap?",
        ].map((q, i) => (
          <button
            key={i}
            onClick={() => onOpenChat(q)}
            style={{
              width: "100%",
              textAlign: "left",
              background: C.s2,
              border: "none",
              padding: "10px 12px",
              borderRadius: 10,
              color: C.t2,
              fontSize: 12,
              fontFamily: FONT,
              fontWeight: 600,
              cursor: "pointer",
              marginBottom: 6,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span>"{q}"</span>
            <span style={{ color: C.t4, fontSize: 11 }}>→</span>
          </button>
        ))}
      </Panel>
    </div>
  );
}
