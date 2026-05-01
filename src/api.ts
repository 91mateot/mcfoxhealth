import useSWR, { type SWRResponse, mutate } from "swr";
import type {
  TodayResponse,
  WorkoutsResponse,
  NutritionResponse,
  ProgressResponse,
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
  LatestConversationResponse,
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

async function fetcher<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<TResp>(path: string, body: unknown): Promise<TResp> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function patch<TResp>(path: string, body: unknown): Promise<TResp> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function del<TResp>(path: string): Promise<TResp> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
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

export function useNutrition(date: string): SWRResponse<NutritionResponse> {
  return useSWR<NutritionResponse>(`/api/nutrition/${date}`, fetcher);
}

export function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
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

  const tag = guessTag(new Date().getHours());
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
  const result = await patch<{ meal: Meal }>(`/api/meal/${date}/${mealId}`, updates);
  invalidateMealCaches();
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
}

export async function submitJournal(journal: JournalSubmission) {
  const result = await post<{ status: string; date: string; slot: string }>("/api/journal", journal);
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

export async function fetchLatestConversation(): Promise<LatestConversationResponse> {
  const res = await fetch(`${API_BASE}/api/conversation/latest`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export interface AskCoachOptions {
  conversationId?: string | null;
  onConversationId?: (id: string) => void;
  signal?: AbortSignal;
}

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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: opts?.signal,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

  const returnedId = res.headers.get("X-Conversation-Id") || res.headers.get("x-conversation-id");
  if (returnedId && opts?.onConversationId) opts.onConversationId(returnedId);

  if (!res.body) {
    const text = await res.text();
    if (text) onToken(text);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    if (chunk) onToken(chunk);
  }
}
