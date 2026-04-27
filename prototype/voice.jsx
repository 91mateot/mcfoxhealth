// VoiceInput — textarea/input with Web Speech API mic button
// Falls back to simulated dictation if SpeechRecognition not available

function VoiceInput({ C, value, onChange, placeholder, minHeight = 72, onSubmit, submitOnStop }) {
  const [listening, setListening] = useState(false);
  const [level, setLevel] = useState(0);
  const [supported, setSupported] = useState(true);
  const recRef = useRef(null);
  const intervalRef = useRef(null);
  const baseRef = useRef("");

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    setSupported(!!SR);
  }, []);

  const start = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    baseRef.current = value ? value + " " : "";

    if (SR) {
      const rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (e) => {
        let transcript = "";
        for (let i = 0; i < e.results.length; i++) transcript += e.results[i][0].transcript;
        onChange(baseRef.current + transcript);
      };
      rec.onerror = () => stop();
      rec.onend = () => { setListening(false); clearInterval(intervalRef.current); };
      recRef.current = rec;
      try { rec.start(); } catch (e) {}
    } else {
      // Fallback: simulated dictation (no mic permission in sandbox)
      const demo = "Push day. Bench four sets of eight at one eighty five. Overhead press three sets of eight at one fifteen. Dips three sets body weight. Felt strong, no back issues.";
      const words = demo.split(" ");
      let i = 0;
      intervalRef.current = setInterval(() => {
        if (i >= words.length) { stop(); return; }
        onChange(baseRef.current + words.slice(0, i + 1).join(" "));
        i++;
      }, 180);
    }

    setListening(true);
    // Animate levels
    const lvl = setInterval(() => setLevel(Math.random()), 80);
    intervalRef.current = intervalRef.current || lvl;
    // Double-wrap interval so both tick
    const lvl2 = setInterval(() => setLevel(Math.random()), 80);
    setTimeout(() => clearInterval(lvl2), 120000);
  };

  const stop = () => {
    if (recRef.current) { try { recRef.current.stop(); } catch (e) {} }
    if (intervalRef.current) clearInterval(intervalRef.current);
    setListening(false);
    if (submitOnStop && onSubmit) setTimeout(onSubmit, 100);
  };

  const toggle = () => listening ? stop() : start();

  return (
    <div style={{
      position: "relative",
      background: C.s, border: `1px solid ${listening ? C.primary : C.border}`,
      borderRadius: 14, overflow: "hidden",
      transition: "border-color .2s ease",
      boxShadow: listening ? `0 0 0 3px ${C.primaryDim}` : "none",
    }}>
      <textarea value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%", background: "transparent", border: "none",
          padding: "12px 50px 12px 12px", color: C.t, fontFamily: FONT, fontSize: 12,
          minHeight, outline: "none", resize: "none", boxSizing: "border-box",
          lineHeight: 1.5,
        }} />
      {listening && (
        <div style={{
          position: "absolute", left: 12, bottom: 8, display: "flex", gap: 2, alignItems: "flex-end", height: 14,
        }}>
          {[0,1,2,3,4].map(i => (
            <div key={i} style={{
              width: 2.5, borderRadius: 2, background: C.primary,
              height: 3 + ((Math.sin((Date.now()/120) + i) + 1) * 5 + level * 4),
              transition: "height .08s linear",
            }} />
          ))}
          <span style={{ fontSize: 9, color: C.primary, fontFamily: MONO, fontWeight: 700, marginLeft: 6, letterSpacing: ".1em" }}>
            LISTENING…
          </span>
        </div>
      )}
      <button onClick={toggle} aria-label={listening ? "Stop" : "Record"} style={{
        position: "absolute", right: 8, bottom: 8,
        width: 34, height: 34, borderRadius: 17,
        background: listening ? C.primary : C.s2,
        border: listening ? "none" : `1px solid ${C.s3}`,
        color: listening ? "#0a0a0a" : C.t2,
        cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all .2s ease",
        boxShadow: listening ? `0 0 0 6px ${C.primary}22` : "none",
      }}>
        {listening ? (
          <svg width="12" height="12" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/></svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="3" width="6" height="11" rx="3"/>
            <path d="M5 11a7 7 0 0014 0M12 18v3"/>
          </svg>
        )}
      </button>
      {!supported && !listening && (
        <div style={{ position: "absolute", left: 12, bottom: 8, fontSize: 8.5, color: C.t4, fontFamily: MONO, letterSpacing: ".05em" }}>
          TAP MIC · DEMO DICTATION
        </div>
      )}
    </div>
  );
}

function VoiceFab({ C, onTranscript, label = "Hold to dictate" }) {
  const [listening, setListening] = useState(false);
  const [text, setText] = useState("");
  const recRef = useRef(null);

  const start = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      const rec = new SR();
      rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
      rec.onresult = e => {
        let t = "";
        for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
        setText(t);
      };
      rec.onend = () => setListening(false);
      recRef.current = rec;
      try { rec.start(); } catch (e) {}
    } else {
      // demo
      const demo = "Had rotisserie chicken 8 oz and mashed potatoes";
      const words = demo.split(" ");
      let i = 0;
      const t = setInterval(() => {
        if (i >= words.length) { clearInterval(t); return; }
        setText(words.slice(0, i + 1).join(" ")); i++;
      }, 220);
    }
    setListening(true);
  };

  const stop = () => {
    if (recRef.current) { try { recRef.current.stop(); } catch (e) {} }
    setListening(false);
    if (text) onTranscript(text);
    setText("");
  };

  return null; // reserved for future use
}

function MicButton({ C, onTranscript, onAutosend }) {
  const [listening, setListening] = useState(false);
  const recRef = useRef(null);
  const textRef = useRef("");

  const start = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    textRef.current = "";
    if (SR) {
      const rec = new SR();
      rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
      rec.onresult = e => {
        let t = "";
        for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
        textRef.current = t; onTranscript(t);
      };
      rec.onend = () => { setListening(false); if (textRef.current && onAutosend) onAutosend(); };
      recRef.current = rec;
      try { rec.start(); } catch (e) {}
    } else {
      const demo = "What should I eat for dinner";
      const words = demo.split(" "); let i = 0;
      const t = setInterval(() => {
        if (i >= words.length) {
          clearInterval(t); setListening(false);
          if (onAutosend) onAutosend();
          return;
        }
        const v = words.slice(0, i + 1).join(" ");
        textRef.current = v; onTranscript(v); i++;
      }, 160);
    }
    setListening(true);
  };
  const stop = () => {
    if (recRef.current) { try { recRef.current.stop(); } catch (e) {} }
    setListening(false);
    if (textRef.current && onAutosend) onAutosend();
  };

  return (
    <button onClick={() => listening ? stop() : start()} aria-label={listening ? "Stop" : "Dictate"} style={{
      width: 34, height: 34, borderRadius: 16, border: "none",
      background: listening ? C.primary : "transparent",
      color: listening ? "#0a0a0a" : C.t3,
      cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
      transition: "all .2s ease",
      boxShadow: listening ? `0 0 0 4px ${C.primary}30` : "none",
    }}>
      {listening ? (
        <svg width="12" height="12" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/></svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="3" width="6" height="11" rx="3"/>
          <path d="M5 11a7 7 0 0014 0M12 18v3"/>
        </svg>
      )}
    </button>
  );
}

Object.assign(window, { VoiceInput, VoiceFab, MicButton });
