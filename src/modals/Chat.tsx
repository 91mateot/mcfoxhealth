import { useEffect, useRef, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";
import type { ChatMessage } from "../types";
import { Sheet } from "../components/Sheet";
import { MicButton } from "../components/VoiceInput";
import { askCoach } from "../api";

interface ChatModalProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  initialPrompt?: string;
}

function nowStamp(): string {
  return new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase().replace(" ", "");
}

export function ChatModal({ C, open, onClose, initialPrompt }: ChatModalProps) {
  const [msgs, setMsgs] = useState<ChatMessage[]>([
    {
      from: "coach",
      t: nowStamp(),
      text: "Morning. I read your recovery, strain, sleep, and nutrition data. Ask me anything.",
    },
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    if (open && initialPrompt) setInput(initialPrompt);
  }, [open, initialPrompt]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, thinking]);

  useEffect(() => {
    return () => {
      if (animationRef.current != null) {
        window.clearInterval(animationRef.current);
        animationRef.current = null;
      }
    };
  }, []);

  const cancelAnimation = () => {
    if (animationRef.current != null) {
      window.clearInterval(animationRef.current);
      animationRef.current = null;
    }
  };

  const revealReply = (base: ChatMessage[], fullText: string) => {
    cancelAnimation();
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

    if (reduceMotion || fullText.length < 30) {
      setMsgs([...base, { from: "coach", t: nowStamp(), text: fullText }]);
      return;
    }

    const stamp = nowStamp();
    setMsgs([...base, { from: "coach", t: stamp, text: "" }]);

    const charsPerTick = 2;
    const tickMs = 25;
    let i = 0;
    animationRef.current = window.setInterval(() => {
      i = Math.min(i + charsPerTick, fullText.length);
      setMsgs([...base, { from: "coach", t: stamp, text: fullText.slice(0, i) }]);
      if (i >= fullText.length) cancelAnimation();
    }, tickMs);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || thinking) return;
    cancelAnimation();
    const t = nowStamp();
    const userMsg: ChatMessage = { from: "me", t, text };
    const next = [...msgs, userMsg];
    setMsgs(next);
    setInput("");
    setThinking(true);
    try {
      const reply = await askCoach(next);
      revealReply(next, reply || "(no response)");
    } catch (err) {
      setMsgs([
        ...next,
        {
          from: "coach",
          t: nowStamp(),
          text: "Couldn't reach coach. Check your connection and try again.",
        },
      ]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} height="88%">
      <div style={{ position: "sticky", top: 0, background: C.bg, padding: "4px 0 10px", marginTop: -6, zIndex: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 2px" }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              background: `linear-gradient(135deg, ${C.primary}, ${C.cyan})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.bg,
              fontWeight: 800,
              fontSize: 13,
            }}
          >
            AI
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.t }}>Coach</div>
            <div style={{ fontSize: 11, color: C.primary, fontFamily: MONO, fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: 3, background: C.primary, display: "inline-block" }} />
              ONLINE · reads all your data
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close chat"
            style={{ background: C.s2, border: "none", color: C.t2, width: 30, height: 30, borderRadius: 15, cursor: "pointer", fontSize: 14 }}
          >
            ✕
          </button>
        </div>
      </div>

      <div ref={scrollRef} style={{ padding: "6px 0 10px" }}>
        {msgs.map((m, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: m.from === "me" ? "flex-end" : "flex-start",
              marginBottom: 8,
            }}
          >
            <div
              style={{
                maxWidth: "82%",
                background: m.from === "me" ? C.primary : C.s,
                color: m.from === "me" ? "#0a0a0a" : C.t,
                border: m.from === "me" ? "none" : `1px solid ${C.border}`,
                padding: "9px 13px",
                borderRadius: m.from === "me" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                fontSize: 12.5,
                lineHeight: 1.5,
                fontWeight: m.from === "me" ? 600 : 500,
                whiteSpace: "pre-wrap",
              }}
            >
              {m.text}
              <div
                style={{
                  fontSize: 11,
                  fontFamily: MONO,
                  color: m.from === "me" ? "#0a0a0aa0" : C.t4,
                  marginTop: 4,
                  fontWeight: 500,
                  textAlign: m.from === "me" ? "right" : "left",
                }}
              >
                {m.t}
              </div>
            </div>
          </div>
        ))}
        {thinking && (
          <div style={{ display: "flex", marginBottom: 8 }}>
            <div
              style={{
                background: C.s,
                border: `1px solid ${C.border}`,
                borderRadius: "16px 16px 16px 4px",
                padding: "10px 14px",
                display: "flex",
                gap: 4,
              }}
            >
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    background: C.t3,
                    animation: `dot 1.2s ${i * 0.15}s infinite`,
                  }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 6, overflowX: "auto", padding: "2px 0 8px", marginBottom: 4 }}>
        {["Morning briefing", "What should I eat?", "Back check-in", "Weekly review"].map((q, i) => (
          <button
            key={i}
            onClick={() => setInput(q)}
            style={{
              flexShrink: 0,
              background: C.s2,
              border: `1px solid ${C.border}`,
              color: C.t2,
              padding: "6px 11px",
              borderRadius: 14,
              fontFamily: FONT,
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {q}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 6, background: C.s, border: `1px solid ${C.border}`, borderRadius: 20, padding: 5, alignItems: "center" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask coach…"
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            padding: "8px 10px",
            color: C.t,
            fontFamily: FONT,
            fontSize: 13,
          }}
        />
        <MicButton C={C} onTranscript={(t) => setInput(t)} onAutosend={() => setTimeout(send, 80)} />
        <button
          onClick={send}
          aria-label="Send"
          disabled={thinking}
          style={{
            width: 34,
            height: 34,
            borderRadius: 16,
            border: "none",
            background: C.primary,
            color: "#0a0a0a",
            cursor: thinking ? "not-allowed" : "pointer",
            opacity: thinking ? 0.6 : 1,
            fontSize: 16,
            fontWeight: 800,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          ↑
        </button>
      </div>
    </Sheet>
  );
}
