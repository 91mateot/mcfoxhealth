import useSWR, { type SWRResponse, mutate } from "swr";
import type {
  TodayResponse,
  TrendsResponse,
  WorkoutsResponse,
  NutritionResponse,
  BodyResponse,
  ProgressResponse,
  Meal,
  MealInput,
  MealEstimate,
  MealPatch,
  Favorite,
  ChatMessage,
  JournalToday,
} from "./types";

export const API_BASE =
  import.meta.env.VITE_API_BASE ??
  "https://5vvp43vamk.execute-api.us-west-2.amazonaws.com";

// Coach lives on a separate Lambda Function URL (RESPONSE_STREAM mode) so it
// can stream; API Gateway HTTP API buffers. Falls back to the API Gateway
// host for local dev before the Function URL is wired.
export const COACH_URL =
  import.meta.env.VITE_COACH_URL ?? `${API_BASE}/api/coach`;

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

/** @deprecated — superseded by useProgress(). Keep one release then remove. */
export function useTrends(): SWRResponse<TrendsResponse> {
  return useSWR<TrendsResponse>("/api/trends", fetcher);
}

export function useWorkouts(): SWRResponse<WorkoutsResponse> {
  return useSWR<WorkoutsResponse>("/api/workouts", fetcher);
}

/** @deprecated — superseded by useProgress(). Keep one release then remove. */
export function useBody(): SWRResponse<BodyResponse> {
  return useSWR<BodyResponse>("/api/body", fetcher);
}

export function useProgress(): SWRResponse<ProgressResponse> {
  return useSWR<ProgressResponse>("/api/progress", fetcher);
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

export async function submitJournal(journal: Partial<JournalToday> & { tags: string[] }) {
  const result = await post<{ ok: boolean }>("/api/journal", journal);
  mutate("/api/today");
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

export async function askCoachStream(
  messages: ChatMessage[],
  snapshot: TodayResponse | undefined,
  onToken: (chunk: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(COACH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, snapshot: snapshot ?? null }),
    signal,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
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
