import type { CorrelationPoint } from "../types";

interface ScatterplotProps {
  points: CorrelationPoint[];
  color: string;
  /** y = slope*x + intercept — drawn as a subtle regression line behind points. */
  slope?: number;
  intercept?: number;
  /** Background/border reference colors from the palette. */
  axis: string;
  bg: string;
  w?: number;
  h?: number;
}

/** Tiny, dependency-free scatterplot. Normalizes axes to the data range,
 * with 6% padding so extremes don't touch the edges. Draws a regression line
 * when slope/intercept are provided. */
export function Scatterplot({
  points,
  color,
  slope,
  intercept,
  axis,
  bg,
  w = 280,
  h = 120,
}: ScatterplotProps) {
  if (!points || points.length < 2) {
    return (
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }} aria-hidden />
    );
  }

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const padX = xRange * 0.06;
  const padY = yRange * 0.08;
  const xLo = xMin - padX;
  const xHi = xMax + padX;
  const yLo = yMin - padY;
  const yHi = yMax + padY;

  const toPx = (x: number, y: number): [number, number] => [
    ((x - xLo) / (xHi - xLo)) * w,
    h - ((y - yLo) / (yHi - yLo)) * h,
  ];

  // Regression line: draw across the full x-range so slope/intercept are
  // obvious at a glance. Clip at the plot edges.
  let lineX1 = 0;
  let lineY1 = 0;
  let lineX2 = 0;
  let lineY2 = 0;
  let hasLine = false;
  if (typeof slope === "number" && typeof intercept === "number" && Number.isFinite(slope) && Number.isFinite(intercept)) {
    const [p1x, p1y] = toPx(xLo, slope * xLo + intercept);
    const [p2x, p2y] = toPx(xHi, slope * xHi + intercept);
    lineX1 = p1x;
    lineY1 = p1y;
    lineX2 = p2x;
    lineY2 = p2y;
    hasLine = true;
  }

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }} aria-hidden>
      <rect x={0} y={0} width={w} height={h} fill={bg} rx={8} />
      <line x1={0} x2={w} y1={h - 0.5} y2={h - 0.5} stroke={axis} strokeWidth={1} />
      <line x1={0.5} x2={0.5} y1={0} y2={h} stroke={axis} strokeWidth={1} />
      {hasLine && (
        <line
          x1={lineX1}
          x2={lineX2}
          y1={lineY1}
          y2={lineY2}
          stroke={color}
          strokeOpacity={0.55}
          strokeWidth={1.4}
          strokeDasharray="4 3"
        />
      )}
      {points.map((p, i) => {
        const [cx, cy] = toPx(p.x, p.y);
        return <circle key={i} cx={cx} cy={cy} r={2.4} fill={color} fillOpacity={0.85} />;
      })}
    </svg>
  );
}
