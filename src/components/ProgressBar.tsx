import type { Palette } from "../theme";

interface ProgressBarProps {
  C: Palette;
  val: number;
  max: number;
  color: string;
  height?: number;
}

export function ProgressBar({ C, val, max, color, height = 6 }: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, (val / max) * 100));
  return (
    <div style={{ height, borderRadius: height / 2, background: C.s4, overflow: "hidden" }}>
      <div
        style={{
          height: "100%",
          borderRadius: height / 2,
          width: `${pct}%`,
          background: color,
          transition: "width 1s ease",
        }}
      />
    </div>
  );
}
