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
  hrv: number | null;
  rhr: number | null;
  resp: number | null;
  sleepNeed: number;
  steps: number | null;
}

export interface StrainTarget {
  low: number;
  high: number;
  optimal: number;
  reason: string;
}

export type SleepQualityFlag = "ok" | "partial" | "truncated" | "missing";

export interface SleepSegment {
  /** HAE timestamp e.g. "2026-05-03 23:30:00 -0700". Preserved verbatim. */
  start: string;
  end?: string | null;
  stage: "deep" | "rem" | "core" | "awake" | "in_bed" | "asleep";
  dur_min: number;
}

export type SleepComponentLabel = "Excellent" | "Good" | "Fair" | "Poor";

export interface SleepComponentScore {
  score: number | null;
  label: SleepComponentLabel | null;
}

export interface SleepComponentScores {
  duration: SleepComponentScore;
  efficiency: SleepComponentScore;
  deep: SleepComponentScore;
  rem: SleepComponentScore;
  continuity: SleepComponentScore;
  hrDip: SleepComponentScore;
}

export interface SleepStages {
  score: number | null;
  hours: number | null;
  minutes: number | null;
  efficiency: number | null;
  deep: number | null;
  rem: number | null;
  core: number | null;
  awake: number | null;
  /** Band-2 additions. Optional for back-compat with older score rows. */
  qualityFlag?: SleepQualityFlag;
  qualityReasons?: string[];
  confidence?: number;
  arousalCount?: number;
  onsetMin?: number;
  continuityIdx?: number;
  avgHrSleep?: number;
  minHrSleep?: number;
  /** Band-3 additions — nocturnal HR dip + personal-need-anchored duration. */
  hrDipIdx?: number | null;
  hrDipPct?: number | null;
  durationTargetUsed?: number | null;
  /** Per-component 0–100 score + bucket label for the detail-sheet grid. */
  componentScores?: SleepComponentScores | null;
  segments?: SleepSegment[];
}

export interface SleepBank {
  /** Rolling 7-night sum of actual asleep minus need baseline. Positive = surplus. */
  minutes: number;
  trend: "surplus" | "deficit" | "balanced";
  /** How many of the 7 nights had data — lets the UI dim if partial. */
  samples: number;
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
  rec: number | null;
  hrv: number | null;
  rhr: number | null;
  sleep: number | null;
  strain: number | null;
  tag: RecoveryTag | null;
  today?: boolean;
}

export interface StepsDay {
  d: string;
  v: number | null;
  today?: boolean;
}

export interface ProteinDay {
  d: string;
  date: string;
  p: number | null;
  cal: number | null;
  flag?: boolean;
  today?: boolean;
  inProgress?: boolean;
}

export interface Ingredient {
  name: string;
  portion?: string;
  cal: number;
  p: number;
  c: number;
  f: number;
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
  originalText?: string;
  assumptions?: string[];
  confidence?: EstimateConfidence;
  source?: MealSource;
  sourceUrl?: string;
  ingredients?: Ingredient[];
  waterOz?: number;
  caffeineMg?: number;
  validatedAt?: string;
  validatedSource?: "usda" | "llm_audit" | "openfoodfacts" | "bedrock_vision" | "none";
}

export type MealSource = "known_foods" | "llm" | "barcode" | "label_photo";

export interface NutritionTargets {
  cal: number;
  p: number;
  c: number;
  f: number;
  water: number;
}

export interface Supplement {
  name: string;
  /** Matching JOURNAL_TAGS id — used to toggle today's tag. */
  tag: string;
  dose: string;
  taken: boolean;
}

export interface CoachInsight {
  type: string;
  title: string;
  body: string;
  tag: string;
  icon: string;
}

export interface ChatImage {
  /** data:image/jpeg;base64,... — kept locally for <img src> thumbnails.
   *  Stripped before sending to the coach Function URL. */
  dataUrl: string;
  /** Raw base64 body (no data: prefix) sent to Bedrock. */
  base64: string;
  mediaType: "image/jpeg" | "image/png" | "image/webp" | "image/gif";
  bytes: number;
}

export interface ChatMessage {
  from: "coach" | "me";
  t: string;
  text: string;
  /** Stable id assigned server-side. Present on new messages and any
   * message loaded from history after 2026-05. Older rows omit it. */
  id?: string;
  /** Current thumbs signal for this message. Kept client-side; not
   * hydrated from the GET — we only track thumbs that were set during
   * this session. Future reads could be added if aggregated feedback
   * surfaces somewhere. */
  feedback?: "up" | "down";
  /** Attached images — only user messages carry these. */
  images?: ChatImage[];
  /** Set on historical turns loaded from storage — bytes were stripped. */
  imgCount?: number;
}

export interface LatestConversationResponse {
  conversationId: string | null;
  messages?: ChatMessage[];
  summary?: string | null;
  messageCount?: number;
  updatedAt?: string;
}

export interface ConversationListItem {
  conversationId: string;
  updatedAt: string;
  createdAt: string;
  messageCount: number;
  preview: string;
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

export type MetricKind = "observed" | "derived" | "configured_target" | "fallback";
export type MetricAvailability = "available" | "unavailable" | "insufficient_history";

export interface MetricSemantics {
  kind?: MetricKind;
  availability: MetricAvailability;
  samples?: number;
  expectedSamples?: number;
  reason?: string;
}

export type TodayMetricSemantics = Record<string, MetricSemantics>;

export interface TodayResponse {
  date: string;
  dateFull: string;
  updatedAt?: string | null;
  recovery: number | null;
  recoveryZone?: RecoveryTag | null;
  recoveryComponents?: RecoveryComponents;
  strain: number | null;
  strainProjected?: number;
  strainTarget: StrainTarget;
  acwr?: ACWR;
  sleep: SleepStages;
  sleepNeedTonight: SleepNeed | null;
  /** 7-night rolling sleep bank. Null when no daily_scores rows carry a
   * sleep_bank_delta yet. */
  sleepBank?: SleepBank | null;
  hrv: number | null;
  rhr: number | null;
  resp: number | null;
  spo2?: number | null;
  wristTemp?: number | null;
  steps: number | null;
  stepsGoal: number;
  calories: { active: number | null; resting: number | null };
  water: number | null;
  waterGoal: number;
  caffeineMg?: number | null;
  caffeineGoal?: number;
  nutritionHasData?: boolean;
  recoveryWeek: RecoveryDay[];
  hrv30d: Array<number | null>;
  stepsWeek: StepsDay[];
  mealsToday: Meal[];
  mealPlanned?: Meal;
  nutritionTargets: NutritionTargets;
  proteinWeek: ProteinDay[];
  supplements: Supplement[];
  coachInsights: CoachInsight[];
  plannedWorkout?: PlannedWorkout | null;
  base: Baselines;
  /** Additive provenance/availability metadata for values that retain the
   * legacy top-level response shape. Null remains the value-level signal for
   * unavailable observations; this map explains why and distinguishes
   * observations, derived values, targets, and legacy fallbacks. */
  metricSemantics: TodayMetricSemantics;
  journal?: JournalToday;
  journalLastNight?: JournalLastNight;
  /** Raw tag list on today's journal row. Set whether or not the morning
   * check-in has been submitted — used by Fuel supplement-chip toggles that
   * need to know the live tag state before Mateo does the full morning
   * entry. */
  journalTagsToday?: string[];
}

export type WorkoutType =
  | "push"
  | "pull"
  | "legs"
  | "run"
  | "hiit"
  | "pilates"
  | "pickleball"
  | "walk"
  | "mobility"
  | "sport_prep"
  | "rest";

export type WorkoutIntensity = "light" | "moderate" | "hard";

export interface ActivationExercise {
  name: string;
  sets?: number;
  reps?: string;
  cue?: string;
}

export interface ActivationBlock {
  name: string;
  durationMin: number;
  location: "gym" | "home";
  exercises: ActivationExercise[];
}

export interface FocusLift {
  name: string;
  canonical: string;
  muscleGroup: string;
  tag: "stalled" | "volume behind" | "anchor" | string;
}

export interface PlannedMain {
  type: WorkoutType;
  durationMin: number;
  intensity: WorkoutIntensity;
  reason: string;
  focusMuscleGroups?: string[];
  focusLifts?: FocusLift[];
}

export interface PlannedWorkout {
  main: PlannedMain;
  activation?: ActivationBlock | null;
  reason: string;
  phase?: number;
  generatedAt: string;
  matched: boolean;
  matchedWorkoutId?: string | null;
  /** True when Mateo explicitly marked today as a recovery day (via the
   * Today card or the coach). The nightly cron won't replace the rest plan
   * while this is set; hitting Refresh clears it. */
  restOverride?: boolean;
}

export type MuscleGroup =
  | "chest"
  | "back"
  | "shoulders"
  | "arms"
  | "legs"
  | "glutes"
  | "core"
  | "cardio"
  | "mobility"
  | "other";

export interface LiftSet {
  reps: number;
  weight: number;
  unit?: "lbs" | "kg";
  warmup?: boolean;
  ramp?: boolean;
  dropset?: boolean;
  duration_sec?: number;
}

export interface WorkoutExercise {
  name: string;
  canonical?: string;
  muscle_group?: MuscleGroup;
  sets: LiftSet[];
  superset_with?: string;
  superset_group?: string[];
  note?: string;
  pr?: { weight?: boolean; e1rm?: boolean; volume?: boolean };
  e1rm?: number;
  top_weight?: number;
  top_reps_at_top_weight?: number;
  // legacy fields still tolerated from older rows
  scheme?: string;
  hr?: number;
}

export interface CardioInterval {
  name: string;
  params: Record<string, number>;
  duration_min?: number;
}

export interface Workout {
  date: string;
  day: string;
  type: string;
  title: string;
  strava_id?: string;
  dur: number;
  avgHR: number;
  maxHR: number;
  cal: number;
  strain: number;
  sets: number;
  notes?: string;
  exercises?: WorkoutExercise[];
  cardioIntervals?: CardioInterval[];
  sessionNotes?: string;
  annotatedAt?: string;
  originalText?: string;
  source?: "strava" | "manual";
  coachFeedback?: string;
  coachFeedbackAt?: string;
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

export interface PRRecord {
  date: string;
  canonical: string;
  name: string;
  muscleGroup: MuscleGroup;
  topWeight: number;
  topReps: number;
  e1rm: number;
  prKinds: string[];
}

export interface StallRecord {
  canonical: string;
  name: string;
  muscleGroup: MuscleGroup;
  weight: number;
  reps: number;
  sessions: number;
  sinceDate?: string;
}

export interface MuscleVolumeWeek {
  muscleGroup: MuscleGroup;
  volumeLb: number;
  prevVolumeLb: number;
  sessions: number;
}

export interface LiftsSection {
  recentPRs: PRRecord[];
  stalls: StallRecord[];
  weeklyVolume: MuscleVolumeWeek[];
  weekStart: string;
}

export interface WaterLog {
  id: string;
  oz: number;
  loggedAt?: string;
  sourceMealId?: string;
}

export interface NutritionResponse {
  date: string;
  meals: Meal[];
  mealPlanned?: Meal;
  totals: { cal: number; p: number; c: number; f: number };
  water: number;
  waterLogs?: WaterLog[];
  caffeineMg?: number;
  caffeineGoal?: number;
  targets: NutritionTargets;
  supplements?: Supplement[];
}

export interface NutritionHistoryDay {
  date: string;
  meals: Meal[];
  totals: { cal: number; p: number; c: number; f: number };
  water: number;
  caffeineMg?: number;
}

export interface NutritionHistoryResponse {
  days: NutritionHistoryDay[];
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

export interface CorrelationPoint {
  x: number;
  y: number;
  date: string;
}

export interface NumericCorrelation {
  /** e.g. "numeric:caffeine_mg" — the CorrelationsTable row key. */
  tag: string;
  /** Input key without the `numeric:` prefix, e.g. "caffeine_mg". */
  input: string;
  inputLabel: string;
  inputUnits: string;
  /** Outcome metric column, e.g. "sleep_score". */
  outcome: string;
  outcomeLabel: string;
  outcomeUnits: string;
  lagDays: number;
  better: "up" | "down";
  n: number;
  r: number;
  slope: number;
  intercept: number;
  /** "none" means |r| is too weak to claim a pattern; UI should deprioritize. */
  confidence: "high" | "medium" | "low" | "none";
  insight: string;
  points: CorrelationPoint[];
  windowDays: number;
  computedAt?: string;
}

export interface InsightsResponse {
  numeric: NumericCorrelation[];
  journal: Correlation[];
  computedAt?: string | null;
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

export interface ProgressResponse {
  now: BodyResponse;
  trend: TrendsResponse;
  lifts?: LiftsSection;
}

export interface InfraCostBreakdown {
  service: string;
  cost: number;
}

export interface InfraCostWeek {
  week_start: string;
  total: number;
  breakdown: InfraCostBreakdown[];
}

export interface InfraCostResponse {
  month_to_date: {
    period_start: string;
    total: number;
    breakdown: InfraCostBreakdown[];
  };
  weekly: InfraCostWeek[];
  computed_at: string;
  cached?: boolean;
  age_sec?: number;
  stale?: boolean;
  error?: string;
}

export interface JournalTag {
  id: string;
  label: string;
  cat: "intake" | "sleep" | "body" | "mind" | "context" | "supplement";
  icon: string;
  negative: boolean;
  /** Display-name override — used when the DB tag id is intentionally generic
   * (e.g., id="rx" renders as "Rx" in the UI; coach knows rx=Adderall). */
  displayLabel?: string;
}

export interface JournalPrompt {
  q: string;
  a: string;
}

export interface MorningEntry {
  tags: string[];
  mood: number | null;
  stress: number | null;
  soreness: number | null;
  text?: string;
  prompts?: JournalPrompt[];
  savedAt?: string | null;
}

export interface EveningEntry {
  tags?: string[];
  mood?: number | null;
  stress?: number | null;
  text?: string;
  prompts?: JournalPrompt[];
  savedAt?: string | null;
}

/** Time-marked mid-day journal note. Lives alongside morning/evening entries
 * on the same daily row — never overwrites them. */
export interface JournalNote {
  id: string;
  at: string;
  text: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  tags?: string[];
  mood?: number | null;
  stress?: number | null;
}

export interface JournalEntry {
  date: string;
  submitted?: boolean;
  morning?: MorningEntry | null;
  evening?: EveningEntry | null;
  notes?: JournalNote[];
}

export type JournalSlot = "morning" | "evening";
/** API-layer slot: includes "tags_only" for the Fuel supplement-chip live toggle,
 * which updates tags on today's journal row without marking morning as submitted;
 * and "note" for time-marked mid-day notes that append to the notes[] array. */
export type JournalSlotApi = JournalSlot | "tags_only" | "note";

export interface JournalToday extends JournalEntry {}

export interface JournalLastNight {
  date: string;
  tags: string[];
  mood: number | null;
  stress: number | null;
  soreness: number | null;
}

export interface JournalHistoryResponse {
  entries: JournalEntry[];
}

export interface JournalPromptsResponse {
  prompts: JournalPrompt[];
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
  original_text?: string;
  assumptions?: string[];
  confidence?: EstimateConfidence;
  source?: MealSource;
  sourceUrl?: string;
  ingredients?: Ingredient[];
  water_oz?: number;
  caffeine_mg?: number;
}

export interface MealPatch {
  name?: string;
  cal?: number;
  p?: number;
  c?: number;
  f?: number;
  tag?: string;
  portion?: string;
  time?: string;
  /** YYYY-MM-DD in local TZ. When provided (and different from the meal's
   * current date), the backend moves the row across days and returns the new
   * date in the response. */
  date?: string;
  original_text?: string;
  assumptions?: string[];
  confidence?: EstimateConfidence;
  source_url?: string;
  ingredients?: Ingredient[];
  water_oz?: number;
  caffeine_mg?: number;
}

export interface Favorite {
  id: string;
  name: string;
  cal: number;
  p: number;
  c: number;
  f: number;
  tag: string;
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
  source?: MealSource;
  sourceUrl?: string;
  ingredients?: Ingredient[];
  time?: string;
  water_oz?: number;
  caffeine_mg?: number;
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
  // Supplements — logged per-day, feed the correlation engine on equal footing
  // with other journal tags. Order here is the canonical display order.
  { id: "creatine", label: "Creatine", cat: "supplement", icon: "💪", negative: false },
  { id: "zinc", label: "Zinc", cat: "supplement", icon: "⚗️", negative: false },
  { id: "d3_k2", label: "D3 + K2", cat: "supplement", icon: "☀️", negative: false },
  { id: "fish_oil", label: "Fish Oil", cat: "supplement", icon: "🐟", negative: false },
  { id: "vitamin_c", label: "Vitamin C", cat: "supplement", icon: "🍊", negative: false },
  { id: "l_theanine", label: "L-theanine", cat: "supplement", icon: "🍵", negative: false },
  { id: "rx", label: "Rx", cat: "supplement", icon: "💊", negative: false },
  { id: "5_htp", label: "5-HTP", cat: "supplement", icon: "🌙", negative: false },
  { id: "b_complex", label: "B-complex", cat: "supplement", icon: "🧬", negative: false },
];

export const SUPPLEMENT_TAGS: JournalTag[] = JOURNAL_TAGS.filter((t) => t.cat === "supplement");

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
