import { useEffect, useRef, useState } from "react";
import type { BrowserMultiFormatReader as BrowserMultiFormatReaderType } from "@zxing/browser";
import { FONT, MONO, type Palette } from "../theme";
import { Sheet } from "./Sheet";
import { Btn } from "./Btn";

interface BarcodeScannerProps {
  C: Palette;
  open: boolean;
  onClose: () => void;
  /** Called with the decoded barcode string when a scan succeeds or the user
   *  submits a manual-entry code. Caller is responsible for closing the sheet
   *  (typically via onClose inside its handler). */
  onDetected: (code: string) => void;
}

type Status = "requesting" | "scanning" | "denied" | "error";

export function BarcodeScanner({ C, open, onClose, onDetected }: BarcodeScannerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const readerRef = useRef<BrowserMultiFormatReaderType | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState<Status>("requesting");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [manualEntry, setManualEntry] = useState<string>("");

  useEffect(() => {
    if (!open) return;

    let active = true;
    setStatus("requesting");
    setErrorMsg("");

    const stopTracks = () => {
      // Reader's internal stream lives on the <video>. Stop every track to
      // release the camera on iOS Safari (critical — iOS leaks the indicator
      // dot if tracks aren't stopped, even after element removal).
      const v = videoRef.current;
      if (v) {
        const stream = v.srcObject as MediaStream | null;
        if (stream) {
          stream.getTracks().forEach((t) => t.stop());
          v.srcObject = null;
        }
      }
    };

    // Lazy-load zxing so the ~115KB gzip decoder only hits the network when
    // someone actually opens the scanner.
    import("@zxing/browser")
      .then(({ BrowserMultiFormatReader }) => {
        if (!active) return;
        const reader = new BrowserMultiFormatReader();
        readerRef.current = reader;

        return reader
          .decodeFromVideoDevice(undefined, videoRef.current!, (result, _err, controls) => {
            if (!active) return;
            if (result) {
              const text = result.getText();
              try {
                controls.stop();
              } catch {
                /* noop */
              }
              stopTracks();
              onDetected(text);
            }
            // Non-result err is NotFoundException per frame — normal; ignore.
          })
          .then(() => {
            if (active) setStatus("scanning");
          });
      })
      .catch((e: unknown) => {
        if (!active) return;
        const name = (e as { name?: string })?.name || "";
        if (name === "NotAllowedError" || name === "SecurityError") {
          setStatus("denied");
        } else {
          setStatus("error");
          setErrorMsg(e instanceof Error ? e.message : String(e));
        }
      });

    cleanupRef.current = () => {
      active = false;
      stopTracks();
      readerRef.current = null;
    };

    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [open, onDetected]);

  const handleManualSubmit = () => {
    const code = manualEntry.trim();
    if (!code) return;
    onDetected(code);
  };

  return (
    <Sheet C={C} open={open} onClose={onClose} title="Scan barcode" height="85%">
      {status === "denied" && (
        <div
          style={{
            background: C.s,
            border: `1px solid ${C.warn}40`,
            borderRadius: 14,
            padding: 14,
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 12.5, color: C.t, fontWeight: 700, marginBottom: 4 }}>
            Camera access blocked
          </div>
          <div style={{ fontSize: 11.5, color: C.t3, lineHeight: 1.5 }}>
            Safari needs permission to use the camera. In iOS: Settings → Safari → Camera →
            Allow. Or type the barcode number below.
          </div>
        </div>
      )}

      {status === "error" && (
        <div
          style={{
            background: C.s,
            border: `1px solid ${C.warn}40`,
            borderRadius: 14,
            padding: 14,
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 12.5, color: C.t, fontWeight: 700, marginBottom: 4 }}>
            Scanner unavailable
          </div>
          <div style={{ fontSize: 11.5, color: C.t3, lineHeight: 1.5 }}>
            {errorMsg || "The camera couldn't start. Enter the barcode below instead."}
          </div>
        </div>
      )}

      {(status === "requesting" || status === "scanning") && (
        <div
          style={{
            position: "relative",
            background: "#000",
            borderRadius: 16,
            overflow: "hidden",
            marginBottom: 14,
            aspectRatio: "4 / 5",
          }}
        >
          <video
            ref={videoRef}
            playsInline
            muted
            autoPlay
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
          {/* Reticle */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              pointerEvents: "none",
            }}
          >
            <div
              style={{
                width: "78%",
                height: 90,
                borderRadius: 12,
                border: `2px solid ${C.primary}`,
                boxShadow: "0 0 0 9999px rgba(0,0,0,0.35) inset",
              }}
            />
          </div>
          {status === "requesting" && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#fff",
                fontFamily: MONO,
                fontSize: 12,
                letterSpacing: ".1em",
                textTransform: "uppercase",
              }}
            >
              Requesting camera…
            </div>
          )}
          {status === "scanning" && (
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                bottom: 12,
                textAlign: "center",
                color: "#fff",
                fontFamily: MONO,
                fontSize: 11,
                letterSpacing: ".08em",
                textShadow: "0 1px 3px rgba(0,0,0,.8)",
              }}
            >
              Line up the barcode
            </div>
          )}
        </div>
      )}

      <div
        style={{
          fontSize: 10,
          color: C.t4,
          textTransform: "uppercase",
          letterSpacing: ".1em",
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        Or type it
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          inputMode="numeric"
          pattern="[0-9]*"
          value={manualEntry}
          onChange={(e) => setManualEntry(e.target.value)}
          placeholder="e.g. 0123456789012"
          style={{
            flex: 1,
            background: C.s,
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: "10px 12px",
            color: C.t,
            fontFamily: MONO,
            fontSize: 14,
            outline: "none",
            minWidth: 0,
            boxSizing: "border-box",
          }}
        />
        <Btn C={C} primary onClick={handleManualSubmit} disabled={!manualEntry.trim()}>
          Use
        </Btn>
      </div>
      <div style={{ height: 14 }} />
      <Btn C={C} full onClick={onClose}>
        Cancel
      </Btn>
      <div style={{ fontSize: 11, color: C.t4, marginTop: 10, lineHeight: 1.5, fontFamily: FONT }}>
        Data from OpenFoodFacts (free, community-maintained). Misses fall back to the AI
        estimator.
      </div>
    </Sheet>
  );
}
