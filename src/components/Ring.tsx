interface RingProps {
  val: number;
  max: number;
  color: string;
  trackColor: string;
  size?: number;
  stroke?: number;
  animate?: boolean;
}

export function Ring({ val, max, color, trackColor, size = 88, stroke = 5, animate = true }: RingProps) {
  const r = 50 - stroke / 2 - 1;
  const ci = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, val / max));
  const off = ci - pct * ci;
  return (
    <svg
      viewBox="0 0 100 100"
      style={{ width: size, height: size, transform: "rotate(-90deg)" }}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={val}
    >
      <circle cx="50" cy="50" r={r} stroke={trackColor} strokeWidth={stroke} fill="none" />
      <circle
        cx="50"
        cy="50"
        r={r}
        stroke={color}
        strokeWidth={stroke}
        fill="none"
        strokeLinecap="round"
        strokeDasharray={ci}
        strokeDashoffset={off}
        style={{ transition: animate ? "stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)" : "none" }}
      />
    </svg>
  );
}
