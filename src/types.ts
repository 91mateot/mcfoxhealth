export type RecoveryTag = "green" | "yellow" | "red";

export interface Mateo {
  name: string;
  age: number;
  height: string;
  weight: number;
  bodyFat: number;
  leanMass: number;
  location: string;
  goal: string;
}

export interface Baselines {
  hrv: number;
  rhr: number;
  resp: number | null;
  sleepNeed: number;
  steps: number;
}

export interface StrainTarget {
  low: number;
  high: number;
  optimal: number;
  reason: string;
}

export interface SleepStages {
  score: number;
  hours: number;
  minutes: number;
  efficiency: number;
  deep: number;
  rem: number;
  core: number;
  awake: number;
}

export interface SleepNeed {
  baseMin: number;
  debtMin: number;
  strainMin: number;
  totalMin: number;
  bedtimeBy: string;
}

export interface RecoveryDay {
  d: string;
  date: string;
  rec: number;
  hrv: number | null;
  rhr: number | null;
  sleep: number | null;
  strain: number;
  tag: RecoveryTag;
  today?: boolean;
}

export interface StepsDay {
  d: string;
  v: number;
  today?: boolean;
}

export interface ProteinDay {
  d: string;
  date: string;
  p: number;
  cal: number;
  flag?: boolean;
  today?: boolean;
  inProgress?: boolean;
}

export interface Meal {
  id: string | number;
  time: string;
  name: string;
  portion: string;
  cal: number;
  p: number;
  c: number;
  f: number;
  tag: string;
}

export interface NutritionTargets {
  cal: number;
  p: number;
  c: number;
  f: number;
  water: number;
}

export interface Supplement {
  name: string;
  dose: string;
  timing: string;
  taken: boolean;
}

export interface CoachInsight {
  type: string;
  title: string;
  body: string;
  tag: string;
  icon: string;
}

export interface ChatMessage {
  from: "coach" | "me";
  t: string;
  text: string;
}

export interface RecoveryComponents {
  hrv?: number | null;
  rhr?: number | null;
  sleep?: number | null;
  resp?: number | null;
  spo2?: number | null;
  wrist_temp?: number | null;
}

export interface ACWR {
  ratio: number;
  acute: number;
  chronic: number;
  zone: RecoveryTag;
  interpretation: string;
}

export interface TodayResponse {
  date: string;
  dateFull: string;
  updatedAt?: string | null;
  recovery: number;
  recoveryZone?: RecoveryTag;
  recoveryComponents?: RecoveryComponents;
  strain: number;
  strainProjected?: number;
  strainTarget: StrainTarget;
  acwr?: ACWR;
  sleep: SleepStages;
  sleepNeedTonight: SleepNeed;
  hrv: number | null;
  rhr: number | null;
  resp: number | null;
  spo2?: number | null;
  wristTemp?: number | null;
  steps: number;
  stepsGoal: number;
  calories: { active: number; resting: number };
  water: number;
  waterGoal: number;
  recoveryWeek: RecoveryDay[];
  hrv30d: number[];
  stepsWeek: StepsDay[];
  mealsToday: Meal[];
  mealPlanned?: Meal;
  nutritionTargets: NutritionTargets;
  proteinWeek: ProteinDay[];
  supplements: Supplement[];
  coachInsights: CoachInsight[];
  base: Baselines;
  journal?: JournalToday;
  journalLastNight?: JournalLastNight;
}

export interface Workout {
  date: string;
  day: string;
  type: string;
  title: string;
  dur: number;
  avgHR: number;
  maxHR: number;
  cal: number;
  strain: number;
  sets: number;
  notes?: string;
}

export interface WorkoutExercise {
  name: string;
  scheme: string;
  note?: string;
  hr?: number;
}

export interface WorkoutDetail {
  title: string;
  date: string;
  type: string;
  exercises: WorkoutExercise[];
  zones: { z1: number; z2: number; z3: number; z4: number; z5: number };
}

export interface WorkoutsResponse {
  workouts: Workout[];
  lastDetail?: WorkoutDetail;
}

export interface NutritionResponse {
  date: string;
  meals: Meal[];
  mealPlanned?: Meal;
  totals: { cal: number; p: number; c: number; f: number };
  water: number;
  targets: NutritionTargets;
  supplements?: Supplement[];
}

export interface TrendMetric {
  cur: number;
  prev: number;
  unit: string;
  better: "up" | "down";
}

export interface Correlation {
  tag: string;
  metric: string;
  effect: number;
  unit: string;
  n: number;
  confidence: "high" | "medium" | "low";
  direction: "positive" | "negative";
}

export interface TrendsResponse {
  trends30d: {
    hrv: TrendMetric;
    rhr: TrendMetric;
    sleep: TrendMetric;
    recovery: TrendMetric;
    weight?: TrendMetric;
    bodyFat?: TrendMetric;
    protein: TrendMetric;
    proteinHit?: TrendMetric;
    strain: TrendMetric;
    sessions?: TrendMetric;
    steps: TrendMetric;
    resp?: TrendMetric;
    spo2?: TrendMetric;
    wristTemp?: TrendMetric;
  };
  trendSeries: {
    hrv: number[];
    rhr: number[];
    sleep: number[];
    recovery: number[];
    weight?: number[];
    protein: number[];
    strain: number[];
    steps: number[];
    resp?: number[];
    spo2?: number[];
    wristTemp?: number[];
  };
  correlations: Correlation[];
}

export interface BodyHistoryPoint {
  month?: string;
  date?: string;
  weight: number;
  bodyFat?: number;
  leanMass?: number;
}

export interface BodyResponse {
  weight14d: number[];
  weightHistory: BodyHistoryPoint[];
  fatHistory: BodyHistoryPoint[];
  leanHistory: BodyHistoryPoint[];
  current?: {
    weight: number;
    bodyFat: number;
    leanMass: number;
  };
}

export interface JournalTag {
  id: string;
  label: string;
  cat: "intake" | "sleep" | "body" | "mind" | "context";
  icon: string;
  negative: boolean;
}

export interface JournalToday {
  submitted: boolean;
  tags: string[];
  mood: number | null;
  stress: number | null;
  soreness: number | null;
}

export interface JournalLastNight {
  date: string;
  tags: string[];
  mood: number;
  stress: number;
  soreness: number;
}

export interface MealInput {
  name: string;
  portion?: string;
  cal: number;
  p: number;
  c: number;
  f: number;
  tag?: string;
  time?: string;
}

export type EstimateConfidence = "high" | "medium" | "low";

export interface MealEstimate {
  name: string;
  cal: number;
  p: number;
  c: number;
  f: number;
  tag: string;
  confidence: EstimateConfidence;
  assumptions: string[];
  source?: "known_foods" | "llm";
  sourceUrl?: string;
}

export interface CoachRequest {
  messages: ChatMessage[];
  context?: string;
}

export const JOURNAL_TAGS: JournalTag[] = [
  { id: "alcohol", label: "Alcohol", cat: "intake", icon: "🍷", negative: true },
  { id: "caffeine_late", label: "Caffeine after 2pm", cat: "intake", icon: "☕", negative: true },
  { id: "ate_late", label: "Ate late", cat: "intake", icon: "🌙", negative: true },
  { id: "heavy_meal", label: "Heavy dinner", cat: "intake", icon: "🍖", negative: true },
  { id: "hydrated", label: "Hydrated 100oz", cat: "intake", icon: "💧", negative: false },
  { id: "screens_bed", label: "Screens in bed", cat: "sleep", icon: "📱", negative: true },
  { id: "late_bedtime", label: "Late bedtime", cat: "sleep", icon: "🕐", negative: true },
  { id: "meditated", label: "Meditated", cat: "mind", icon: "🧘", negative: false },
  { id: "stretched", label: "Stretched / PT", cat: "body", icon: "🤸", negative: false },
  { id: "sauna", label: "Sauna", cat: "body", icon: "🔥", negative: false },
  { id: "cold", label: "Cold plunge", cat: "body", icon: "🧊", negative: false },
  { id: "sunlight_am", label: "AM sunlight", cat: "body", icon: "☀️", negative: false },
  { id: "stress", label: "High stress", cat: "mind", icon: "⚡", negative: true },
  { id: "social", label: "Social night", cat: "mind", icon: "👥", negative: false },
  { id: "travel", label: "Travel", cat: "context", icon: "✈️", negative: true },
  { id: "sick", label: "Feeling sick", cat: "context", icon: "🤒", negative: true },
  { id: "back_flare", label: "Back flare", cat: "context", icon: "⚠️", negative: true },
];

export const MATEO: Mateo = {
  name: "Mateo Thompson",
  age: 34,
  height: "5'8\"",
  weight: 169,
  bodyFat: 13.6,
  leanMass: 146,
  location: "Pacific Beach, SD",
  goal: "Sub-12% BF, defend lean mass",
};
