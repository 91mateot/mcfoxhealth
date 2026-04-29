import { useEffect, useRef, useState } from "react";
import { mutate } from "swr";
import { FONT, MONO, type Palette } from "../theme";
import type { ChatImage, ChatMessage, TodayResponse } from "../types";
import { Sheet } from "../components/Sheet";
import { MicButton } from "../components/VoiceInput";
import { askCoachStream, todayISO } from "../api";
import { compressImage } from "../lib/images";

const MAX_IMAGES_PER_TURN = 5;

interface ChatModalProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  initialPrompt?: string;
  today?: TodayResponse;
}

function nowStamp(): string {
  return new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase().replace(" ", "");
}

export function ChatModal({ C, open, onClose, initialPrompt, today }: ChatModalProps) {
  const [msgs, setMsgs] = useState<ChatMessage[]>([
    {
      from: "coach",
      t: nowStamp(),
      text: "Morning. I read your recovery, strain, sleep, and nutrition data. Ask me anything.",
    },
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [pendingImages, setPendingImages] = useState<ChatImage[]>([]);
  const [attachBusy, setAttachBusy] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (open && initialPrompt) setInput(initialPrompt);
    if (open) {
      setPendingImages([]);
      setAttachBusy(false);
      setAttachError(null);
    }
  }, [open, initialPrompt]);

  const handlePickImage = async (file: File | null) => {
    if (!file) return;
    if (pendingImages.length >= MAX_IMAGES_PER_TURN) {
      setAttachError(`Max ${MAX_IMAGES_PER_TURN} images per message.`);
      return;
    }
    setAttachBusy(true);
    setAttachError(null);
    try {
      // Tighter compression when the user is stacking multiple photos so we
      // don't blow past the 1 MB streaming-request budget on send.
      const nextCount = pendingImages.length + 1;
      const maxEdge = nextCount >= 3 ? 900 : 1024;
      const compressed = await compressImage(file, maxEdge, 0.7);
      setPendingImages((prev) => [
        ...prev,
        {
          dataUrl: compressed.dataUrl,
          base64: compressed.base64,
          mediaType: compressed.mediaType,
          bytes: compressed.bytes,
        },
      ]);
    } catch (e) {
      setAttachError(e instanceof Error ? e.message : "Couldn't read that image.");
    } finally {
      setAttachBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const removePendingImage = (i: number) => {
    setPendingImages((prev) => prev.filter((_, idx) => idx !== i));
  };

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, thinking]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const send = async () => {
    const text = input.trim();
    const imgs = pendingImages;
    // Allow send when there's text OR at least one image.
    if ((!text && imgs.length === 0) || thinking) return;
    const t = nowStamp();
    const userMsg: ChatMessage = { from: "me", t, text };
    if (imgs.length > 0) userMsg.images = imgs;
    const next = [...msgs, userMsg];
    setMsgs(next);
    setInput("");
    setPendingImages([]);
    setAttachError(null);
    setThinking(true);

    const replyStamp = nowStamp();
    let streamed = "";
    let started = false;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await askCoachStream(
        next,
        today,
        (chunk) => {
          streamed += chunk;
          if (!started) {
            started = true;
            setMsgs([...next, { from: "coach", t: replyStamp, text: streamed }]);
          } else {
            setMsgs([...next, { from: "coach", t: replyStamp, text: streamed }]);
          }
        },
        controller.signal,
      );
      if (!streamed) {
        setMsgs([...next, { from: "coach", t: replyStamp, text: "(no response)" }]);
      }
      // Pick up any side effects from coach tool use (log_meal, log_water, log_journal)
      mutate("/api/today");
      mutate(`/api/nutrition/${todayISO()}`);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMsgs([
          ...next,
          {
            from: "coach",
            t: nowStamp(),
            text: "Couldn't reach coach. Check your connection and try again.",
          },
        ]);
      }
    } finally {
      setThinking(false);
      abortRef.current = null;
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
                padding: m.images && m.images.length > 0 ? "6px 6px 9px" : "9px 13px",
                borderRadius: m.from === "me" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                fontSize: 12.5,
                lineHeight: 1.5,
                fontWeight: m.from === "me" ? 600 : 500,
                whiteSpace: "pre-wrap",
              }}
            >
              {m.images && m.images.length > 0 && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: m.images.length === 1 ? "1fr" : "1fr 1fr",
                    gap: 4,
                    marginBottom: m.text ? 6 : 4,
                  }}
                >
                  {m.images.map((img, j) => (
                    <img
                      key={j}
                      src={img.dataUrl}
                      alt=""
                      style={{
                        width: "100%",
                        aspectRatio: "1 / 1",
                        objectFit: "cover",
                        borderRadius: 10,
                        display: "block",
                      }}
                    />
                  ))}
                </div>
              )}
              {m.text && <div style={{ padding: m.images && m.images.length > 0 ? "0 7px" : 0 }}>{m.text}</div>}
              <div
                style={{
                  fontSize: 11,
                  fontFamily: MONO,
                  color: m.from === "me" ? "#0a0a0aa0" : C.t4,
                  marginTop: 4,
                  fontWeight: 500,
                  textAlign: m.from === "me" ? "right" : "left",
                  padding: m.images && m.images.length > 0 ? "0 7px" : 0,
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

      {(pendingImages.length > 0 || attachError) && (
        <div style={{ padding: "4px 0 6px" }}>
          {pendingImages.length > 0 && (
            <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4 }}>
              {pendingImages.map((img, i) => (
                <div
                  key={i}
                  style={{
                    position: "relative",
                    flexShrink: 0,
                    width: 56,
                    height: 56,
                    borderRadius: 10,
                    overflow: "hidden",
                    border: `1px solid ${C.border}`,
                  }}
                >
                  <img
                    src={img.dataUrl}
                    alt=""
                    style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                  />
                  <button
                    onClick={() => removePendingImage(i)}
                    aria-label="Remove image"
                    style={{
                      position: "absolute",
                      top: 2,
                      right: 2,
                      width: 18,
                      height: 18,
                      borderRadius: 9,
                      border: "none",
                      background: "rgba(0,0,0,0.65)",
                      color: "#fff",
                      fontSize: 11,
                      fontWeight: 800,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: 0,
                      lineHeight: 1,
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
              {pendingImages.length < MAX_IMAGES_PER_TURN && (
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={attachBusy}
                  aria-label="Add another image"
                  style={{
                    flexShrink: 0,
                    width: 56,
                    height: 56,
                    borderRadius: 10,
                    border: `1px dashed ${C.border}`,
                    background: "transparent",
                    color: C.t3,
                    fontSize: 22,
                    fontWeight: 300,
                    cursor: attachBusy ? "default" : "pointer",
                  }}
                >
                  +
                </button>
              )}
            </div>
          )}
          {attachError && (
            <div style={{ fontSize: 11, color: C.warn, fontFamily: MONO, marginTop: 4 }}>{attachError}</div>
          )}
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={(e) => handlePickImage(e.target.files?.[0] ?? null)}
        style={{ display: "none" }}
      />

      <div style={{ display: "flex", gap: 6, background: C.s, border: `1px solid ${C.border}`, borderRadius: 20, padding: 5, alignItems: "center" }}>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={attachBusy || pendingImages.length >= MAX_IMAGES_PER_TURN}
          aria-label="Attach image"
          title={pendingImages.length >= MAX_IMAGES_PER_TURN ? `Max ${MAX_IMAGES_PER_TURN} images` : "Attach image"}
          style={{
            width: 34,
            height: 34,
            borderRadius: 16,
            border: "none",
            background: "transparent",
            color: attachBusy ? C.t4 : C.t2,
            cursor: attachBusy || pendingImages.length >= MAX_IMAGES_PER_TURN ? "default" : "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
            <circle cx="12" cy="13" r="4" />
          </svg>
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={pendingImages.length > 0 ? "Add a caption (optional)…" : "Ask coach…"}
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
          disabled={thinking || (!input.trim() && pendingImages.length === 0)}
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
