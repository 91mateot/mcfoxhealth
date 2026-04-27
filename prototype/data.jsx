// Mateo's health data — grounded in CLAUDE.md
// April 22, 2026 — in progress

const MATEO = {
  name: "Mateo Thompson",
  age: 34,
  height: "5'8\"",
  weight: 169,
  bodyFat: 13.6,
  leanMass: 146,
  location: "Pacific Beach, SD",
  goal: "Sub-12% BF, defend lean mass",
  reta: { dose: 2, total: 4, mg: 2, startedISO: "2026-04-21" },
};

// Baselines (30d, validated April 17-21)
const BASE = {
  hrv: 48, rhr: 64, resp: 14.5, sleepNeed: 7.5, steps: 10000,
};

// Today (April 22, 2026 — Wed)
const TODAY = {
  date: "Wed, Apr 22",
  dateFull: "Wednesday, April 22, 2026",
  recovery: 82,
  strain: 4.2, // currently, day in progress
  strainProjected: 11.5,
  // Readiness-adjusted strain target (Whoop-style): recovered → train hard, depleted → active recovery
  strainTarget: { low: 14, high: 17, optimal: 15.5, reason: "Green recovery — hard day" },
  sleep: { score: 88, hours: 7, minutes: 42, efficiency: 91, deep: 78, rem: 112, core: 232, awake: 40 },
  // Tonight's sleep need — base + debt + today's strain adjustment
  sleepNeedTonight: {
    baseMin: 450,      // 7h 30m
    debtMin: 22,       // accumulated last 7 nights
    strainMin: 12,     // bonus for today's projected strain
    totalMin: 484,     // 8h 04m
    bedtimeBy: "10:56p",
  },
  hrv: 49, rhr: 60.5, resp: 14.3, spo2: 98, wristTemp: -0.1,
  steps: 6842, stepsGoal: 10000,
  calories: { active: 312, resting: 1680 },
  water: 36, waterGoal: 100,
};

// 7-day recovery trend (ending today)
const RECOVERY_WEEK = [
  { d: "Thu", date: "4/16", rec: 58, hrv: 43, rhr: 65, sleep: 6.3, strain: 9.8, tag: "yellow" },
  { d: "Fri", date: "4/17", rec: 62, hrv: 45, rhr: 64, sleep: 6.3, strain: 14.1, tag: "yellow" },
  { d: "Sat", date: "4/18", rec: 48, hrv: 37, rhr: 66, sleep: 5.8, strain: 15.3, tag: "yellow" },
  { d: "Sun", date: "4/19", rec: 18, hrv: 31, rhr: 66, sleep: 7.1, strain: 6.2, tag: "red" },
  { d: "Mon", date: "4/20", rec: 71, hrv: 49, rhr: 61, sleep: 8.7, strain: 8.4, tag: "green" },
  { d: "Tue", date: "4/21", rec: 79, hrv: 49, rhr: 60.5, sleep: 7.8, strain: 12.7, tag: "green" },
  { d: "Wed", date: "4/22", rec: 82, hrv: 49, rhr: 60.5, sleep: 7.7, strain: 4.2, tag: "green", today: true },
];

// 30-day HRV sparkline
const HRV_30D = [
  45,47,44,48,50,46,49,43,47,49,
  48,50,46,44,47,49,52,48,46,43,
  45,37,31,49,49,49,51,48,49,49
];

// Workouts (last ~10)
const WORKOUTS = [
  { date: "4/21", day: "Tue", type: "Push", title: "Push day", dur: 68, avgHR: 112, maxHR: 158, cal: 482, strain: 12.7, sets: 18, notes: "Bench + OHP + dips. Felt strong." },
  { date: "4/20", day: "Mon", type: "Walk", title: "Easy beach walk", dur: 42, avgHR: 94, maxHR: 108, cal: 186, strain: 4.8, sets: 0, notes: "Recovery. Sunrise walk." },
  { date: "4/18", day: "Sat", type: "Pull", title: "Pull day", dur: 109, avgHR: 96, maxHR: 167, cal: 1383, strain: 15.3, sets: 22, notes: "Full pull workout + 20min sauna." },
  { date: "4/17", day: "Fri", type: "Legs", title: "Leg day (light)", dur: 52, avgHR: 104, maxHR: 142, cal: 398, strain: 11.2, sets: 14, notes: "Back-safe: leg press, goblet squats, RDLs." },
  { date: "4/16", day: "Thu", type: "HIIT", title: "HIIT + core", dur: 38, avgHR: 138, maxHR: 172, cal: 421, strain: 13.4, sets: 12, notes: "Assault bike intervals." },
  { date: "4/14", day: "Tue", type: "Push", title: "Push day", dur: 64, avgHR: 110, maxHR: 155, cal: 466, strain: 12.1, sets: 16 },
  { date: "4/13", day: "Mon", type: "Walk", title: "Incline walk", dur: 35, avgHR: 98, maxHR: 118, cal: 178, strain: 5.2, sets: 0 },
];

// Pull day exercise detail (for detail view)
const LAST_WORKOUT_DETAIL = {
  title: "Pull day", date: "Apr 18", type: "Pull",
  exercises: [
    { name: "Pull-ups", scheme: "3 × BW", note: "superset w/ deadhang crunches", hr: 128 },
    { name: "Incline walk", scheme: "15 min @ 3.0 mph, 8% incline", note: "warmup", hr: 108 },
    { name: "T-bar rows", scheme: "5 × 7 @ 80 lb", note: "superset w/ push-ups 10-15", hr: 134 },
    { name: "Tricep pulldown", scheme: "3 × 10 (40, 43, 47 lb)", note: "ascending load", hr: 118 },
    { name: "RDLs", scheme: "3 × 7 @ 70 lb bar", note: "tri-set", hr: 126 },
    { name: "Dead bug crunches", scheme: "3 × 10", note: "tri-set close", hr: 104 },
    { name: "Cable Pallof press", scheme: "3 sets @ lv 10/16", note: "anti-rotation", hr: 112 },
    { name: "Sauna", scheme: "18 min", note: "finisher", hr: 92 },
  ],
  zones: { z1: 22, z2: 48, z3: 28, z4: 9, z5: 2 },
};

// Today's meals (logged so far)
const MEALS_TODAY = [
  { id: 1, time: "8:30a", name: "Morning shake", portion: "½ serving", cal: 356, p: 26.5, c: 51, f: 8.5, tag: "breakfast" },
  { id: 2, time: "11:30a", name: "Morning shake", portion: "2nd half", cal: 356, p: 26.5, c: 51, f: 8.5, tag: "snack" },
  { id: 3, time: "1:30p", name: "Rotisserie chicken", portion: "8 oz Sprouts", cal: 450, p: 52, c: 0, f: 26, tag: "lunch" },
  { id: 4, time: "1:30p", name: "Mashed potatoes", portion: "⅓ cup", cal: 80, p: 1, c: 12, f: 3, tag: "lunch" },
  { id: 5, time: "1:30p", name: "Power grains", portion: "¼ cup", cal: 55, p: 2, c: 10, f: 1, tag: "lunch" },
  { id: 6, time: "1:30p", name: "Fish oil", portion: "1 softgel", cal: 15, p: 0, c: 0, f: 1.5, tag: "supplement" },
];

const MEAL_PLANNED = { id: 7, time: "7:00p", name: "Gochujang broth bowl", portion: "MasonFit", cal: 380, p: 36, c: 40, f: 5, tag: "dinner" };

const NUTRITION_TARGETS = { cal: 2200, p: 180, c: 190, f: 65, water: 100 };

// 7-day protein
const PROTEIN_WEEK = [
  { d: "Thu", date: "4/16", p: 85, cal: 1705 },
  { d: "Fri", date: "4/17", p: 42, cal: 977, flag: true },
  { d: "Sat", date: "4/18", p: 0, cal: 300, flag: true },
  { d: "Sun", date: "4/19", p: 18, cal: 420, flag: true },
  { d: "Mon", date: "4/20", p: 242, cal: 2838 },
  { d: "Tue", date: "4/21", p: 108, cal: 1312 },
  { d: "Wed", date: "4/22", p: 108, cal: 1312, today: true, inProgress: true },
];

// Weight trend (last 14 days)
const WEIGHT_14D = [
  169.2,169.4,169.1,168.8,169.2,169.6,170.1,
  169.8,169.5,169.3,169.1,169.0,169.2,169.0
];

const BODY_HISTORY = {
  jan: 170, feb: 168, mar: 168, apr: 169,
};

// Step history (7d)
const STEPS_WEEK = [
  { d: "Thu", v: 8420 }, { d: "Fri", v: 6356 }, { d: "Sat", v: 12840 }, { d: "Sun", v: 4210 },
  { d: "Mon", v: 10820 }, { d: "Tue", v: 16027 }, { d: "Wed", v: 6842, today: true },
];

// Supplements (checkable)
const SUPPLEMENTS = [
  { name: "Creatine", dose: "5g", timing: "AM shake", taken: true },
  { name: "Zinc", dose: "1 serving", timing: "lunch", taken: true },
  { name: "D3 + K2", dose: "1 serving", timing: "lunch", taken: true },
  { name: "Fish Oil", dose: "1.5g", timing: "lunch", taken: true },
];

// Coach insights
const COACH_INSIGHTS = [
  {
    type: "recovery",
    title: "You're recovered — go train",
    body: "Nervous system's fresh (HRV 49 ms, above your usual). Heart's relaxed (pulse 60.5 — your lowest in 30 days). Push day is a go. Keep the back safe — avoid loaded squats and deadlifts.",
    tag: "green", icon: "🟢"
  },
  {
    type: "protein",
    title: "You're behind on protein",
    body: "108g so far, goal is 180g. Your planned gochujang bowl for dinner adds 36g. One Oikos (30g) between now and then closes the gap.",
    tag: "yellow", icon: "🥤"
  },
  {
    type: "hydration",
    title: "Water is lagging",
    body: "36 oz down, 64 to go. Finish them before dinner — going to bed dehydrated drags tomorrow's recovery down.",
    tag: "blue", icon: "💧"
  },
];

// AI coach chat seed (initial transcript)
const CHAT_SEED = [
  { from: "coach", t: "9:02a", text: "Morning. Recovery is 82% green. HRV 49 ms, RHR 60.5 — your lowest RHR in 30 days. You're cleared to train." },
  { from: "coach", t: "9:02a", text: "Cap strain at 12 today. Push session — keep it back-safe: no loaded squats/deadlifts. Finish with sauna." },
  { from: "me", t: "9:14a", text: "Protein plan for today?" },
  { from: "coach", t: "9:14a", text: "Split the morning shake (53g P total). Chicken + sides at lunch (55g). Gochujang bowl for dinner (36g). That's 144g — add one Oikos between meals to clear 180g." },
];

// ─── JOURNAL / BEHAVIOR TAGS ────────────────────────────────────
// Tagged each morning; correlate to recovery/HRV/sleep over time.
const JOURNAL_TAGS = [
  { id: "alcohol",      label: "Alcohol",        cat: "intake",   icon: "🍷", negative: true },
  { id: "caffeine_late",label: "Caffeine after 2pm", cat: "intake", icon: "☕", negative: true },
  { id: "ate_late",     label: "Ate late",       cat: "intake",   icon: "🌙", negative: true },
  { id: "heavy_meal",   label: "Heavy dinner",   cat: "intake",   icon: "🍖", negative: true },
  { id: "hydrated",     label: "Hydrated 100oz", cat: "intake",   icon: "💧", negative: false },
  { id: "screens_bed",  label: "Screens in bed", cat: "sleep",    icon: "📱", negative: true },
  { id: "late_bedtime", label: "Late bedtime",   cat: "sleep",    icon: "🕐", negative: true },
  { id: "meditated",    label: "Meditated",      cat: "mind",     icon: "🧘", negative: false },
  { id: "stretched",    label: "Stretched / PT", cat: "body",     icon: "🤸", negative: false },
  { id: "sauna",        label: "Sauna",          cat: "body",     icon: "🔥", negative: false },
  { id: "cold",         label: "Cold plunge",    cat: "body",     icon: "🧊", negative: false },
  { id: "sunlight_am",  label: "AM sunlight",    cat: "body",     icon: "☀️", negative: false },
  { id: "stress",       label: "High stress",    cat: "mind",     icon: "⚡", negative: true },
  { id: "social",       label: "Social night",   cat: "mind",     icon: "👥", negative: false },
  { id: "travel",       label: "Travel",         cat: "context",  icon: "✈️", negative: true },
  { id: "sick",         label: "Feeling sick",   cat: "context",  icon: "🤒", negative: true },
  { id: "back_flare",   label: "Back flare",     cat: "context",  icon: "⚠️", negative: true },
];

// Today's journal (not yet submitted — morning check-in pending)
const JOURNAL_TODAY = {
  submitted: false,
  tags: [],
  mood: null,   // 1-5
  stress: null, // 1-5
  soreness: null, // 1-5
};

// Last night's submitted journal (shown as reference)
const JOURNAL_LAST_NIGHT = {
  date: "Tue 4/21",
  tags: ["caffeine_late", "stretched", "screens_bed"],
  mood: 4, stress: 2, soreness: 2,
};

// Correlations (computed over 30-60 day window — realistic dummy data)
const CORRELATIONS = [
  { tag: "alcohol",       metric: "HRV",      effect: -18, unit: "%", n: 6,  confidence: "high",   direction: "negative" },
  { tag: "alcohol",       metric: "Sleep eff", effect: -9, unit: "%", n: 6,  confidence: "high",   direction: "negative" },
  { tag: "caffeine_late", metric: "REM",      effect: -12, unit: "%", n: 14, confidence: "medium", direction: "negative" },
  { tag: "screens_bed",   metric: "Deep",     effect: -8,  unit: "%", n: 18, confidence: "medium", direction: "negative" },
  { tag: "ate_late",      metric: "HRV",      effect: -6,  unit: "%", n: 11, confidence: "medium", direction: "negative" },
  { tag: "stretched",     metric: "Back flare next day", effect: -54, unit: "%", n: 12, confidence: "high", direction: "positive" },
  { tag: "sunlight_am",   metric: "Sleep onset", effect: -14, unit: "min", n: 16, confidence: "medium", direction: "positive" },
  { tag: "sauna",         metric: "Deep sleep", effect: 11,  unit: "%", n: 22, confidence: "high",   direction: "positive" },
  { tag: "meditated",     metric: "Morning HRV", effect: 7,  unit: "%", n: 9,  confidence: "low",    direction: "positive" },
  { tag: "late_bedtime",  metric: "Recovery", effect: -15, unit: "%", n: 13, confidence: "high",   direction: "negative" },
];

// 30-day trend data (for Trends tab)
const TRENDS_30D = {
  hrv:      { cur: 46.2, prev: 43.8, unit: "ms",   better: "up"   },
  rhr:      { cur: 62.1, prev: 63.7, unit: "bpm",  better: "down" },
  sleep:    { cur: 436,  prev: 418,  unit: "min",  better: "up"   }, // avg nightly
  recovery: { cur: 62,   prev: 54,   unit: "%",    better: "up"   },
  weight:   { cur: 169.3,prev: 169.8,unit: "lbs",  better: "down" },
  bodyFat:  { cur: 13.6, prev: 13.9, unit: "%",    better: "down" },
  protein:  { cur: 124,  prev: 98,   unit: "g",    better: "up"   }, // avg daily
  proteinHit:{cur: 43,   prev: 29,   unit: "%",    better: "up"   }, // % days hit 180g
  strain:   { cur: 11.4, prev: 10.2, unit: "",     better: "up"   }, // avg session
  sessions: { cur: 18,   prev: 15,   unit: "",     better: "up"   }, // last 30d
  steps:    { cur: 9820, prev: 8410, unit: "",     better: "up"   },
};

// Sparklines for trends (30d series for each)
const TREND_SERIES = {
  hrv:      HRV_30D,
  recovery: [58,62,55,60,71,65,62,48,58,62,65,70,68,64,55,62,71,65,60,55,48,18,52,68,71,79,75,68,79,82],
  sleep:    [395,420,440,460,380,410,450,420,390,400,430,460,440,420,380,410,450,470,430,400,380,350,420,460,480,460,440,420,468,462],
  weight:   [170.1,170.2,169.8,170.0,169.6,169.4,169.5,169.2,169.4,169.1,168.8,169.2,169.6,170.1,169.8,169.5,169.3,169.1,169.0,169.2,169.0,169.4,169.2,169.1,168.9,169.0,168.8,169.1,169.0,169.0],
  protein:  [95,110,140,165,180,120,85,98,145,170,185,160,120,95,110,140,165,180,85,42,0,18,242,108,108,120,140,160,180,108],
};

Object.assign(window, {
  MATEO, BASE, TODAY, RECOVERY_WEEK, HRV_30D, WORKOUTS, LAST_WORKOUT_DETAIL,
  MEALS_TODAY, MEAL_PLANNED, NUTRITION_TARGETS, PROTEIN_WEEK, WEIGHT_14D,
  BODY_HISTORY, STEPS_WEEK, SUPPLEMENTS, COACH_INSIGHTS, CHAT_SEED,
  JOURNAL_TAGS, JOURNAL_TODAY, JOURNAL_LAST_NIGHT, CORRELATIONS,
  TRENDS_30D, TREND_SERIES,
});
