import useSWR, { type SWRResponse, mutate } from "swr";
import type {
  TodayResponse,
  WorkoutsResponse,
  NutritionResponse,
  NutritionHistoryResponse,
  ProgressResponse,
  InfraCostResponse,
  InsightsResponse,
  Meal,
  MealInput,
  MealEstimate,
  MealPatch,
  Favorite,
  ChatMessage,
  JournalHistoryResponse,
  JournalPromptsResponse,
  JournalPrompt,
  JournalSlot,
  JournalSlotApi,
  JournalNote,
  LatestConversationResponse,
  ConversationListItem,
  PlannedWorkout,
} from "./types";

export const API_BASE =
  import.meta.env.VITE_API_BASE ??
  "https://5vvp43vamk.execute-api.us-west-2.amazonaws.com";

// Coach lives on a separate Lambda Function URL (RESPONSE_STREAM mode) so it
// can stream; API Gateway HTTP API buffers. Falls back to the API Gateway
// host for local dev before the Function URL is wired. We treat empty strings
// as unset — a blank Vercel env var would otherwise win over the fallback and
// send chat traffic to the page origin (404).
export const COACH_URL =
  (import.meta.env.VITE_COACH_URL as string | undefined)?.trim()
    || `${API_BASE}/api/coach`;

const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined)?.trim() || "";
const PACIFIC_TIME_ZONE = "America/Los_Angeles";

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...(extra ?? {}) };
  if (API_KEY) h["x-api-key"] = API_KEY;
  return h;
}

async function fetcher<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<TResp>(path: string, body: unknown): Promise<TResp> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function patch<TResp>(path: string, body: unknown): Promise<TResp> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function del<TResp>(path: string): Promise<TResp> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

type EventProps = Record<string, string | number | boolean | null | undefined>;
type PendingEvent = { action: string; props?: EventProps };

const EVENT_FLUSH_MS = 2000;
const EVENT_FLUSH_MAX = 20;
const eventQueue: PendingEvent[] = [];
let eventFlushTimer: ReturnType<typeof setTimeout> | null = null;

function flushEvents() {
  if (eventFlushTimer) {
    clearTimeout(eventFlushTimer);
    eventFlushTimer = null;
  }
  if (eventQueue.length === 0) return;
  const batch = eventQueue.splice(0, eventQueue.length);
  const payload = JSON.stringify({ events: batch });
  const url = `${API_BASE}/api/event`;
  // Prefer sendBeacon for visibilitychange/pagehide paths — it survives
  // teardown. Falls back to fetch(keepalive) when the browser either lacks
  // sendBeacon or rejects the blob (e.g. when x-api-key is required and
  // sendBeacon can't set custom headers). We still send through fetch for
  // normal in-session flushes so the API key header travels.
  fetch(url, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: payload,
    keepalive: true,
  }).catch(() => {
    // Swallow — telemetry is best-effort, never block UX on it.
  });
}

/** Record a user action. Buffered — batched every 2s or when 20 accumulate.
 * Silent on failure. Valid action: snake_case with optional dots, e.g.
 * "tab.switch" or "chat.open". */
export function track(action: string, props?: EventProps) {
  if (!action) return;
  eventQueue.push({ action, props });
  if (eventQueue.length >= EVENT_FLUSH_MAX) {
    flushEvents();
    return;
  }
  if (eventFlushTimer === null) {
    eventFlushTimer = setTimeout(flushEvents, EVENT_FLUSH_MS);
  }
}

if (typeof window !== "undefined") {
  // Flush on tab hide so we don't lose the tail of a session.
  window.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushEvents();
  });
  window.addEventListener("pagehide", flushEvents);
}

export function useToday(): SWRResponse<TodayResponse> {
  return useSWR<TodayResponse>("/api/today", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });
}

export function useWorkouts(): SWRResponse<WorkoutsResponse> {
  return useSWR<WorkoutsResponse>("/api/workouts", fetcher);
}

export function useProgress(): SWRResponse<ProgressResponse> {
  return useSWR<ProgressResponse>("/api/progress", fetcher);
}

export function useInsights(enabled = true): SWRResponse<InsightsResponse> {
  return useSWR<InsightsResponse>(enabled ? "/api/insights" : null, fetcher);
}

export function useInfraCost(enabled = true): SWRResponse<InfraCostResponse> {
  return useSWR<InfraCostResponse>(enabled ? "/api/infra-cost" : null, fetcher, {
    // Cost Explorer is slow + the backend already caches for 6h, so cheap
    // to let this hook ride the cache rather than refetch aggressively.
    revalidateOnFocus: false,
    dedupingInterval: 60 * 60 * 1000,
  });
}

export function useNutrition(date: string): SWRResponse<NutritionResponse> {
  return useSWR<NutritionResponse>(`/api/nutrition/${date}`, fetcher);
}

export function useNutritionHistory(enabled = true, days = 7): SWRResponse<NutritionHistoryResponse> {
  return useSWR<NutritionHistoryResponse>(
    enabled ? `/api/nutrition/history?days=${days}` : null,
    fetcher,
  );
}

type PacificDatePart = "year" | "month" | "day" | "hour";

function pacificDateParts(date = new Date()): Record<PacificDatePart, string> {
  const parts: Record<PacificDatePart, string> = {
    year: "",
    month: "",
    day: "",
    hour: "",
  };
  for (const part of new Intl.DateTimeFormat("en-US", {
    timeZone: PACIFIC_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date)) {
    if (part.type === "year" || part.type === "month" || part.type === "day" || part.type === "hour") {
      parts[part.type] = part.value;
    }
  }
  return parts;
}

export function todayISO(): string {
  const { year, month, day } = pacificDateParts();
  return `${year}-${month}-${day}`;
}

function pacificHour(): number {
  const hour = Number(pacificDateParts().hour);
  return Number.isFinite(hour) ? hour : new Date().getHours();
}

/** Local tag inference mirroring backend/shared/shared/nutrition_service.py:guess_tag.
 * Used by the barcode path, which doesn't call the LLM estimator (which is where
 * the backend normally picks a tag). */
export function guessTag(hour: number): string {
  if (hour < 10) return "breakfast";
  if (hour < 14) return "lunch";
  if (hour < 17) return "snack";
  if (hour < 21) return "dinner";
  return "snack";
}

/** Look up a UPC/EAN against OpenFoodFacts. Returns a MealEstimate ready for
 * the LogMeal review step, or null if the product isn't in OFF or lacks
 * nutrition data. Free, no auth. 5 second timeout. */
export async function lookupBarcode(barcode: string): Promise<MealEstimate | null> {
  const clean = (barcode || "").trim().replace(/\D/g, "");
  if (!clean) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  let payload: any = null;
  try {
    const res = await fetch(
      `https://world.openfoodfacts.org/api/v0/product/${encodeURIComponent(clean)}.json`,
      { signal: controller.signal },
    );
    if (!res.ok) return null;
    payload = await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }

  if (!payload || payload.status !== 1 || !payload.product) return null;
  const p = payload.product;

  const name = String(
    p.product_name ||
      [p.brands, p.generic_name].filter(Boolean).join(" — ") ||
      "Scanned product",
  ).slice(0, 80);

  // Prefer per-serving. Fall back to per-100g × (serving_quantity / 100) when
  // per-serving fields are absent but we know the serving size.
  const servingQty =
    typeof p.serving_quantity === "number"
      ? p.serving_quantity
      : Number(p.serving_quantity) || null;

  function pick(perServingKey: string, per100gKey: string): number | null {
    const perServing = Number(p.nutriments?.[perServingKey]);
    if (Number.isFinite(perServing) && perServing > 0) return perServing;
    const per100 = Number(p.nutriments?.[per100gKey]);
    if (Number.isFinite(per100) && per100 > 0 && servingQty && servingQty > 0) {
      return round1((per100 * servingQty) / 100);
    }
    return null;
  }

  const cal = pick("energy-kcal_serving", "energy-kcal_100g");
  const protein = pick("proteins_serving", "proteins_100g");
  const carbs = pick("carbohydrates_serving", "carbohydrates_100g");
  const fat = pick("fat_serving", "fat_100g");

  // Must have calories AND at least one macro to be useful.
  if (cal === null || (protein === null && carbs === null && fat === null)) {
    return null;
  }

  const tag = guessTag(pacificHour());
  const servingSize = p.serving_size || (servingQty ? `${servingQty}g` : "1 serving");

  return {
    name,
    cal: round1(cal),
    p: round1(protein ?? 0),
    c: round1(carbs ?? 0),
    f: round1(fat ?? 0),
    tag,
    confidence: "high",
    source: "barcode",
    assumptions: [
      `Scanned UPC ${clean} → ${name}`,
      `Per-serving (${servingSize}) from OpenFoodFacts`,
    ],
  };
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function formatMealTime(t: string): string {
  const match = /^(\d{1,2}):(\d{2})$/.exec(t);
  if (!match) return t;
  const h24 = Number(match[1]);
  const mm = match[2];
  if (h24 < 0 || h24 > 23) return t;
  const suffix = h24 >= 12 ? "pm" : "am";
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${h12}:${mm}${suffix}`;
}

export async function logMeal(meal: MealInput) {
  const result = await post<{ ok: boolean; meal_id?: string }>("/api/meal", meal);
  mutate("/api/today");
  mutate(`/api/nutrition/${todayISO()}`);
  return result;
}

export async function estimateMeal(
  text: string,
  opts?: { skipKnownFoods?: boolean },
): Promise<MealEstimate> {
  const body: Record<string, unknown> = { text };
  if (opts?.skipKnownFoods) body.skip_known_foods = true;
  return post<MealEstimate>("/api/meal/estimate", body);
}

/** Image-driven meal estimate. `base64` has NO data: prefix. Returns the
 * same MealEstimate shape as text estimates; source is set by the server
 * (`label_photo` when a nutrition panel or product is identifiable). */
export async function estimateFromPhoto(
  base64: string,
  mediaType: string = "image/jpeg",
  caption?: string,
): Promise<MealEstimate> {
  return post<MealEstimate>("/api/meal/estimate", {
    text: (caption || "").trim(),
    image: { data: base64, media_type: mediaType },
    skip_known_foods: true,
  });
}

function invalidateMealCaches() {
  mutate("/api/today");
  mutate(`/api/nutrition/${todayISO()}`);
}

export async function patchMeal(date: string, mealId: string, updates: MealPatch) {
  const result = await patch<{ meal: Meal; date?: string }>(`/api/meal/${date}/${mealId}`, updates);
  invalidateMealCaches();
  // Cross-day move: the meal's nutrition day changed, so the target date's
  // SWR cache needs to refetch too.
  if (updates.date && updates.date !== date) {
    mutate(`/api/nutrition/${updates.date}`);
  }
  return result;
}

export async function deleteMeal(date: string, mealId: string) {
  const result = await del<{ ok: boolean; date: string; meal_id: string }>(`/api/meal/${date}/${mealId}`);
  invalidateMealCaches();
  return result;
}

export function useFavorites(): SWRResponse<{ favorites: Favorite[] }> {
  return useSWR<{ favorites: Favorite[] }>("/api/favorites", fetcher);
}

export async function addFavorite(fav: Omit<Favorite, "id">) {
  const result = await post<{ favorite: Favorite; count: number }>("/api/favorites", fav);
  mutate("/api/favorites");
  return result;
}

export async function deleteFavorite(id: string) {
  const result = await del<{ ok: boolean; count: number }>(`/api/favorites/${id}`);
  mutate("/api/favorites");
  return result;
}

export async function logWater(oz: number) {
  const result = await post<{ ok: boolean; water: number }>("/api/water", { oz });
  mutate("/api/today");
  mutate(`/api/nutrition/${todayISO()}`);
  return result;
}

export async function deleteWater(date: string, waterId: string) {
  const result = await del<{ ok: boolean; water_id: string }>(`/api/water/${date}/${waterId}`);
  mutate("/api/today");
  mutate(`/api/nutrition/${date}`);
  return result;
}

export interface JournalSubmission {
  slot?: JournalSlotApi;
  tags?: string[];
  mood?: number | null;
  stress?: number | null;
  soreness?: number | null;
  text?: string;
  prompts?: JournalPrompt[];
  /** ISO 8601 timestamp the entry refers to. Only meaningful for slot="note".
   * Backend rejects values that fall outside `date` in America/Los_Angeles. */
  at?: string;
  /** YYYY-MM-DD in local TZ. Defaults to today server-side. */
  date?: string;
}

export async function submitJournal(journal: JournalSubmission) {
  const result = await post<{ status: string; date: string; slot: string; note?: JournalNote }>(
    "/api/journal",
    journal,
  );
  mutate("/api/today");
  mutate("/api/journal/history");
  return result;
}

export interface NoteUpdate {
  date: string;
  id: string;
  text?: string;
  tags?: string[];
  mood?: number | null;
  stress?: number | null;
  at?: string;
}

export async function updateJournalNote(update: NoteUpdate) {
  const result = await patch<{ status: string; date: string; note: JournalNote }>(
    "/api/journal/note",
    update,
  );
  mutate("/api/today");
  mutate("/api/journal/history");
  return result;
}

export async function deleteJournalNote(date: string, id: string) {
  const qs = new URLSearchParams({ date, id }).toString();
  const result = await del<{ status: string; date: string; id: string }>(
    `/api/journal/note?${qs}`,
  );
  mutate("/api/today");
  mutate("/api/journal/history");
  return result;
}

export function useJournalHistory(enabled = true): SWRResponse<JournalHistoryResponse> {
  return useSWR<JournalHistoryResponse>(enabled ? "/api/journal/history" : null, fetcher);
}

export async function fetchJournalPrompts(slot: JournalSlot): Promise<JournalPrompt[]> {
  const result = await post<JournalPromptsResponse>("/api/journal/prompts", { slot });
  return result.prompts || [];
}

export async function logWorkout(text: string, date?: string) {
  const result = await post<{
    workout_id: string;
    title: string;
    type: string;
    duration_min: number;
    intensity: string;
    cal: number;
    strain: number;
  }>("/api/workout", { text, date });
  mutate("/api/workouts");
  mutate("/api/today");
  mutate("/api/progress");
  return result;
}

export async function annotateWorkout(date: string, workoutId: string, text: string) {
  const result = await post<{
    ok: boolean;
    workout_id: string;
    date: string;
    exercise_count: number;
    cardio_count: number;
    muscle_groups: string[];
    session_notes?: string;
    coach_feedback?: string;
  }>(`/api/workout/${date}/${workoutId}/annotate`, { text });
  mutate("/api/workouts");
  mutate("/api/progress");
  return result;
}

export async function regenerateWorkoutFeedback(date: string, workoutId: string) {
  const result = await post<{
    ok: boolean;
    date: string;
    workout_id: string;
    coach_feedback?: string;
    coach_feedback_at?: string;
  }>(`/api/workout/${date}/${workoutId}/feedback`, {});
  mutate("/api/workouts");
  return result;
}

export async function refreshPlannedWorkout(): Promise<PlannedWorkout | null> {
  const result = await post<{ plannedWorkout: PlannedWorkout | null }>("/api/planned-workout/refresh", {});
  mutate("/api/today");
  return result.plannedWorkout;
}

export async function markRestDay(reason?: string): Promise<PlannedWorkout | null> {
  const body: Record<string, unknown> = {};
  if (reason && reason.trim()) body.reason = reason.trim();
  const result = await post<{ plannedWorkout: PlannedWorkout | null }>("/api/planned-workout/rest", body);
  mutate("/api/today");
  return result.plannedWorkout;
}

export async function fetchLatestConversation(): Promise<LatestConversationResponse> {
  const res = await fetch(`${API_BASE}/api/conversation/latest`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchConversationList(limit = 20): Promise<ConversationListItem[]> {
  const res = await fetch(`${API_BASE}/api/conversation/list?limit=${limit}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const data = (await res.json()) as { threads?: ConversationListItem[] };
  return data.threads ?? [];
}

export async function fetchConversationById(id: string): Promise<LatestConversationResponse> {
  const res = await fetch(`${API_BASE}/api/conversation/${encodeURIComponent(id)}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export interface AskCoachOptions {
  conversationId?: string | null;
  onConversationId?: (id: string) => void;
  /** Called once with the assistant message id when the coach emits its
   * end-of-turn trailer. Use it to attach the id to the last coach bubble
   * so thumbs feedback has a stable target. */
  onFeedbackId?: (id: string) => void;
  signal?: AbortSignal;
}

// Mirrors backend/functions/coach/app.py:_feedback_trailer. The record-
// separator prefix makes the marker impossible to collide with real
// assistant text.
const FEEDBACK_TRAILER_RE = /\x1e<<FEEDBACK_ID:([^>]+)>>\s*$/;

export async function askCoachStream(
  messages: ChatMessage[],
  snapshot: TodayResponse | undefined,
  onToken: (chunk: string) => void,
  opts?: AskCoachOptions,
): Promise<void> {
  // Strip dataUrl from ChatImages — server only needs base64 + mediaType.
  // Doubles-up bytes on the wire otherwise (dataUrl inlines the same base64).
  const wireMessages = messages.map((m) => {
    if (!m.images || m.images.length === 0) return m;
    return {
      ...m,
      images: m.images.map((img) => ({
        base64: img.base64,
        mediaType: img.mediaType,
        bytes: img.bytes,
      })),
    };
  });
  const body: Record<string, unknown> = {
    messages: wireMessages,
    snapshot: snapshot ?? null,
  };
  if (opts?.conversationId) body.conversation_id = opts.conversationId;

  const res = await fetch(COACH_URL, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

  const returnedId = res.headers.get("X-Conversation-Id") || res.headers.get("x-conversation-id");
  if (returnedId && opts?.onConversationId) opts.onConversationId(returnedId);

  const emitBuffered = (buffer: string, flush: boolean): string => {
    // Hold back the tail while a trailer might still be arriving. Once we
    // see the full marker (or the stream ends), strip it and report the id.
    if (flush) {
      const match = FEEDBACK_TRAILER_RE.exec(buffer);
      if (match) {
        const visible = buffer.slice(0, match.index);
        if (visible) onToken(visible);
        if (opts?.onFeedbackId) opts.onFeedbackId(match[1]);
        return "";
      }
      if (buffer) onToken(buffer);
      return "";
    }
    // Not flushing yet: emit everything up to the last possible marker start.
    const sep = buffer.lastIndexOf("\x1e");
    if (sep === -1) {
      if (buffer) onToken(buffer);
      return "";
    }
    const emit = buffer.slice(0, sep);
    if (emit) onToken(emit);
    return buffer.slice(sep);
  };

  if (!res.body) {
    const text = await res.text();
    emitBuffered(text, true);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let tail = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    if (!chunk) continue;
    tail = emitBuffered(tail + chunk, false);
  }
  emitBuffered(tail + decoder.decode(), true);
}

export async function submitFeedback(
  signal: "up" | "down",
  targetType: "coach_msg" | "proposal",
  targetId: string,
  note?: string,
): Promise<{ ok: boolean }> {
  const body: Record<string, unknown> = {
    signal,
    target_type: targetType,
    target_id: targetId,
  };
  if (note && note.trim()) body.note = note.trim();
  return post<{ ok: boolean }>("/api/feedback", body);
}
