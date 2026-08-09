interface SparklineProps {
  data: Array<number | null>;
  color: string;
  w?: number;
  h?: number;
  fill?: boolean;
  baseline?: number | null;
}

export function Sparkline({ data, color, w = 280, h = 44, fill = true, baseline }: SparklineProps) {
  const values = (data ?? []).filter((value): value is number => value != null && Number.isFinite(value));
  if (values.length === 0) {
    return <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }} />;
  }
  const min = Math.min(...values) - 2;
  const max = Math.max(...values) + 2;
  const range = max - min || 1;
  const stepX = w / Math.max(1, data.length - 1);
  const segments: Array<Array<readonly [number, number]>> = [];
  let segment: Array<readonly [number, number]> = [];
  data.forEach((value, i) => {
    if (value == null || !Number.isFinite(value)) {
      if (segment.length) segments.push(segment);
      segment = [];
      return;
    }
    segment.push([i * stepX, h - ((value - min) / range) * h] as const);
  });
  if (segment.length) segments.push(segment);
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
      {segments.map((points, index) => {
        const path = points.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(" ");
        const fillPath = points.length > 1
          ? `${path} L${points[points.length - 1][0].toFixed(1)},${h} L${points[0][0].toFixed(1)},${h} Z`
          : null;
        return (
          <g key={index}>
            {fill && fillPath && <path d={fillPath} fill={color} fillOpacity="0.12" />}
            {points.length === 1 ? (
              <circle cx={points[0][0]} cy={points[0][1]} r="1.8" fill={color} />
            ) : (
              <path d={path} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            )}
          </g>
        );
      })}
    </svg>
  );
}
