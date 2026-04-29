import { useEffect, useRef, useState } from "react";
import { FONT, MONO, type Palette } from "../theme";

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

declare global {
  interface Window {
    SpeechRecognition?: { new (): SpeechRecognitionInstance };
    webkitSpeechRecognition?: { new (): SpeechRecognitionInstance };
  }
}

interface VoiceInputProps {
  C: Palette;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  minHeight?: number;
  onSubmit?: () => void;
  submitOnStop?: boolean;
}

export function VoiceInput({ C, value, onChange, placeholder, minHeight = 72, onSubmit, submitOnStop }: VoiceInputProps) {
  const [listening, setListening] = useState(false);
  const [level, setLevel] = useState(0);
  const [supported, setSupported] = useState(true);
  const recRef = useRef<SpeechRecognitionInstance | null>(null);
  const intervalRef = useRef<number | null>(null);
  const baseRef = useRef("");

  useEffect(() => {
    const SR = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    setSupported(Boolean(SR));
  }, []);

  // Stop in-flight recognition and clear the level-meter interval on unmount.
  useEffect(() => {
    return () => {
      if (recRef.current) {
        try { recRef.current.stop(); } catch {}
      }
      if (intervalRef.current != null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, []);

  const stop = () => {
    if (recRef.current) {
      try {
        recRef.current.stop();
      } catch {}
    }
    if (intervalRef.current != null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setListening(false);
    if (submitOnStop && onSubmit) setTimeout(onSubmit, 100);
  };

  const start = () => {
    const SR = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    baseRef.current = value ? value + " " : "";

    if (SR) {
      const rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (e: any) => {
        let transcript = "";
        for (let i = 0; i < e.results.length; i++) transcript += e.results[i][0].transcript;
        onChange(baseRef.current + transcript);
      };
      rec.onerror = () => stop();
      rec.onend = () => {
        setListening(false);
        if (intervalRef.current != null) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      };
      recRef.current = rec;
      try {
        rec.start();
      } catch {}
    } else {
      const demo = "Push day. Bench four sets of eight at one eighty five. Overhead press three sets of eight at one fifteen.";
      const words = demo.split(" ");
      let i = 0;
      intervalRef.current = window.setInterval(() => {
        if (i >= words.length) {
          stop();
          return;
        }
        onChange(baseRef.current + words.slice(0, i + 1).join(" "));
        i++;
      }, 180);
    }

    setListening(true);
    const lvl = window.setInterval(() => setLevel(Math.random()), 80);
    if (intervalRef.current == null) intervalRef.current = lvl;
  };

  const toggle = () => (listening ? stop() : start());

  return (
    <div
      style={{
        position: "relative",
        background: C.s,
        border: `1px solid ${listening ? C.primary : C.border}`,
        borderRadius: 14,
        overflow: "hidden",
        transition: "border-color .2s ease",
        boxShadow: listening ? `0 0 0 3px ${C.primaryDim}` : "none",
      }}
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          padding: "12px 50px 12px 12px",
          color: C.t,
          fontFamily: FONT,
          fontSize: 12,
          minHeight,
          outline: "none",
          resize: "none",
          boxSizing: "border-box",
          lineHeight: 1.5,
        }}
      />
      {listening && (
        <div style={{ position: "absolute", left: 12, bottom: 8, display: "flex", gap: 2, alignItems: "flex-end", height: 14 }}>
          {[0, 1, 2, 3, 4].map((i) => (
            <div
              key={i}
              style={{
                width: 2.5,
                borderRadius: 2,
                background: C.primary,
                height: 3 + (Math.sin(Date.now() / 120 + i) + 1) * 5 + level * 4,
                transition: "height .08s linear",
              }}
            />
          ))}
          <span
            style={{
              fontSize: 11,
              color: C.primary,
              fontFamily: MONO,
              fontWeight: 700,
              marginLeft: 6,
              letterSpacing: ".1em",
            }}
          >
            LISTENING…
          </span>
        </div>
      )}
      <button
        type="button"
        onClick={toggle}
        aria-label={listening ? "Stop dictation" : "Start dictation"}
        style={{
          position: "absolute",
          right: 8,
          bottom: 8,
          width: 34,
          height: 34,
          borderRadius: 17,
          background: listening ? C.primary : C.s2,
          border: listening ? "none" : `1px solid ${C.s3}`,
          color: listening ? "#0a0a0a" : C.t2,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "all .2s ease",
          boxShadow: listening ? `0 0 0 6px ${C.primary}22` : "none",
        }}
      >
        {listening ? (
          <svg width="12" height="12" viewBox="0 0 24 24">
            <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0014 0M12 18v3" />
          </svg>
        )}
      </button>
      {!supported && !listening && (
        <div style={{ position: "absolute", left: 12, bottom: 8, fontSize: 11, color: C.t4, fontFamily: MONO, letterSpacing: ".05em" }}>
          TAP MIC · DEMO DICTATION
        </div>
      )}
    </div>
  );
}

interface MicButtonProps {
  C: Palette;
  onTranscript: (t: string) => void;
  onAutosend?: () => void;
}

export function MicButton({ C, onTranscript, onAutosend }: MicButtonProps) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionInstance | null>(null);
  const textRef = useRef("");

  // Stop any in-flight recognition when the component unmounts (e.g. chat
  // sheet closed mid-dictation). Without this the mic keeps listening until
  // the user taps it again, because the browser never returns permission.
  useEffect(() => {
    return () => {
      if (recRef.current) {
        try { recRef.current.stop(); } catch {}
      }
    };
  }, []);

  const start = () => {
    const SR = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    textRef.current = "";
    if (SR) {
      const rec = new SR();
      // Non-continuous: the browser ends recognition on silence, which fires
      // onend → onAutosend. Matches Wispr / iOS Dictation UX: speak, pause,
      // message sends itself.
      rec.continuous = false;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (e: any) => {
        let t = "";
        for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
        textRef.current = t;
        onTranscript(t);
      };
      rec.onerror = () => {
        setListening(false);
      };
      rec.onend = () => {
        setListening(false);
        if (textRef.current && onAutosend) onAutosend();
      };
      recRef.current = rec;
      try {
        rec.start();
      } catch {}
    } else {
      const demo = "What should I eat for dinner";
      const words = demo.split(" ");
      let i = 0;
      const t = window.setInterval(() => {
        if (i >= words.length) {
          clearInterval(t);
          setListening(false);
          if (onAutosend) onAutosend();
          return;
        }
        const v = words.slice(0, i + 1).join(" ");
        textRef.current = v;
        onTranscript(v);
        i++;
      }, 160);
    }
    setListening(true);
  };
  const stop = () => {
    if (recRef.current) {
      try {
        recRef.current.stop();
      } catch {}
    }
    setListening(false);
    if (textRef.current && onAutosend) onAutosend();
  };

  return (
    <button
      type="button"
      onClick={() => (listening ? stop() : start())}
      aria-label={listening ? "Stop" : "Dictate"}
      style={{
        width: 34,
        height: 34,
        borderRadius: 16,
        border: "none",
        background: listening ? C.primary : "transparent",
        color: listening ? "#0a0a0a" : C.t3,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "all .2s ease",
        boxShadow: listening ? `0 0 0 4px ${C.primary}30` : "none",
      }}
    >
      {listening ? (
        <svg width="12" height="12" viewBox="0 0 24 24">
          <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0014 0M12 18v3" />
        </svg>
      )}
    </button>
  );
}
