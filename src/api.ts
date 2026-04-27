import useSWR, { type SWRResponse, mutate } from "swr";
import type {
  TodayResponse,
  TrendsResponse,
  WorkoutsResponse,
  NutritionResponse,
  BodyResponse,
  MealInput,
  MealEstimate,
  ChatMessage,
  JournalToday,
} from "./types";

export const API_BASE =
  import.meta.env.VITE_API_BASE ??
  "https://5vvp43vamk.execute-api.us-west-2.amazonaws.com";

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

export function useToday(): SWRResponse<TodayResponse> {
  return useSWR<TodayResponse>("/api/today", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });
}

export function useTrends(): SWRResponse<TrendsResponse> {
  return useSWR<TrendsResponse>("/api/trends", fetcher);
}

export function useWorkouts(): SWRResponse<WorkoutsResponse> {
  return useSWR<WorkoutsResponse>("/api/workouts", fetcher);
}

export function useBody(): SWRResponse<BodyResponse> {
  return useSWR<BodyResponse>("/api/body", fetcher);
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

export async function logMeal(meal: MealInput) {
  const result = await post<{ ok: boolean; meal_id?: string }>("/api/meal", meal);
  mutate("/api/today");
  mutate(`/api/nutrition/${todayISO()}`);
  return result;
}

export async function estimateMeal(text: string): Promise<MealEstimate> {
  return post<MealEstimate>("/api/meal/estimate", { text });
}

export async function logWater(oz: number) {
  const result = await post<{ ok: boolean; water: number }>("/api/water", { oz });
  mutate("/api/today");
  mutate(`/api/nutrition/${todayISO()}`);
  return result;
}

export async function submitJournal(journal: Partial<JournalToday> & { tags: string[] }) {
  const result = await post<{ ok: boolean }>("/api/journal", journal);
  mutate("/api/today");
  return result;
}

export async function askCoach(messages: ChatMessage[]): Promise<string> {
  const res = await fetch(`${API_BASE}/api/coach`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) return res.text();
  const data = await res.json();
  const r = data.reply;
  if (r && typeof r === "object" && typeof r.text === "string") return r.text;
  if (typeof r === "string") return r;
  return data.text ?? data.message ?? "";
}

export async function askCoachStream(
  messages: ChatMessage[],
  onToken: (chunk: string) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/coach`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, context: "today_summary", stream: true }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  if (!res.body) {
    const text = await res.text();
    onToken(text);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    onToken(decoder.decode(value, { stream: true }));
  }
}
