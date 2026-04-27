export type PaletteKey = "lime" | "zine" | "graphite";

export interface Palette {
  name: string;
  bg: string;
  s: string;
  s2: string;
  s3: string;
  s4: string;
  border: string;
  t: string;
  t2: string;
  t3: string;
  t4: string;
  primary: string;
  primaryDim: string;
  warn: string;
  warnDim: string;
  danger: string;
  dangerDim: string;
  cyan: string;
  cyanDim: string;
  purple: string;
  purpleDim: string;
  yellow: string;
  yellowDim: string;
}

export const PALETTES: Record<PaletteKey, Palette> = {
  lime: {
    name: "Lime / Ember",
    bg: "#0a0a0a",
    s: "#121214",
    s2: "#17171b",
    s3: "#1f1f24",
    s4: "#2a2a32",
    border: "rgba(255,255,255,0.05)",
    t: "#f5f5f5",
    t2: "#a8a8b0",
    t3: "#6d6d78",
    t4: "#48484f",
    primary: "#d4ff3a",
    primaryDim: "rgba(212,255,58,0.10)",
    warn: "#ff6b35",
    warnDim: "rgba(255,107,53,0.10)",
    danger: "#ff4458",
    dangerDim: "rgba(255,68,88,0.10)",
    cyan: "#58e4ff",
    cyanDim: "rgba(88,228,255,0.10)",
    purple: "#c39cff",
    purpleDim: "rgba(195,156,255,0.10)",
    yellow: "#ffd84d",
    yellowDim: "rgba(255,216,77,0.10)",
  },
  zine: {
    name: "Newsprint",
    bg: "#050505",
    s: "#0d0d0d",
    s2: "#141414",
    s3: "#1c1c1c",
    s4: "#272727",
    border: "rgba(255,255,255,0.06)",
    t: "#fafafa",
    t2: "#bdbdbd",
    t3: "#7a7a7a",
    t4: "#4a4a4a",
    primary: "#fff45c",
    primaryDim: "rgba(255,244,92,0.10)",
    warn: "#ff5722",
    warnDim: "rgba(255,87,34,0.10)",
    danger: "#ff3b30",
    dangerDim: "rgba(255,59,48,0.10)",
    cyan: "#ffffff",
    cyanDim: "rgba(255,255,255,0.08)",
    purple: "#ff9ec7",
    purpleDim: "rgba(255,158,199,0.10)",
    yellow: "#fff45c",
    yellowDim: "rgba(255,244,92,0.10)",
  },
  graphite: {
    name: "Graphite / Cyan",
    bg: "#0c1116",
    s: "#141a21",
    s2: "#1a2129",
    s3: "#222a34",
    s4: "#2d3743",
    border: "rgba(255,255,255,0.04)",
    t: "#eef2f6",
    t2: "#9aa4b0",
    t3: "#636d7a",
    t4: "#3d4652",
    primary: "#6ee7b7",
    primaryDim: "rgba(110,231,183,0.10)",
    warn: "#fb923c",
    warnDim: "rgba(251,146,60,0.10)",
    danger: "#f87171",
    dangerDim: "rgba(248,113,113,0.10)",
    cyan: "#38bdf8",
    cyanDim: "rgba(56,189,248,0.10)",
    purple: "#a78bfa",
    purpleDim: "rgba(167,139,250,0.10)",
    yellow: "#fbbf24",
    yellowDim: "rgba(251,191,36,0.10)",
  },
};

export const FONT = "'Outfit', system-ui, sans-serif";
export const MONO = "'JetBrains Mono', monospace";
