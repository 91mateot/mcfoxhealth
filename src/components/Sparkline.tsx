interface SparklineProps {
  data: number[];
  color: string;
  w?: number;
  h?: number;
  fill?: boolean;
  baseline?: number;
}

export function Sparkline({ data, color, w = 280, h = 44, fill = true, baseline }: SparklineProps) {
  if (!data || data.length === 0) {
    return <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }} />;
  }
  const min = Math.min(...data) - 2;
  const max = Math.max(...data) + 2;
  const range = max - min || 1;
  const stepX = w / Math.max(1, data.length - 1);
  const pts = data.map((v, i) => [i * stepX, h - ((v - min) / range) * h] as const);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const dFill = d + ` L${w},${h} L0,${h} Z`;
  const baseY = baseline != null ? h - ((baseline - min) / range) * h : null;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: h, display: "block" }}
      preserveAspectRatio="none"
      aria-hidden
    >
      {baseY != null && (
        <line x1="0" x2={w} y1={baseY} y2={baseY} stroke={color} strokeOpacity="0.25" strokeWidth="1" strokeDasharray="3 3" />
      )}
      {fill && <path d={dFill} fill={color} fillOpacity="0.12" />}
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
