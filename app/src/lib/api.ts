import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";

export const API_URL: string =
  process.env.EXPO_PUBLIC_API_URL ?? (Constants.expoConfig?.extra as any)?.apiUrl ?? "http://localhost:8000";

const KEY = "bluepuff.token";
let token: string | null = null;

export async function loadToken() {
  token = await AsyncStorage.getItem(KEY);
  return token;
}
export async function setToken(t: string | null) {
  token = t;
  if (t) await AsyncStorage.setItem(KEY, t);
  else await AsyncStorage.removeItem(KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(API_URL + path, {
    method: opts.method ?? (opts.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as any)?.detail;
    throw new ApiError(res.status, typeof d === "string" ? d : "Something went wrong. Try again.");
  }
  return data as T;
}

// --- shapes returned by the server (server/app.py) ---
export type Plan = "free" | "racer" | "racer_pro";
export type ClubLink = { slug: string; name: string; role: string; home: boolean; fleet: string | null };
export type Me = { id: number; email: string; name: string; plan: Plan; plan_via: string | null; clubs: ClubLink[] };
export type Call = {
  call: "race_on" | "marginal" | "too_light" | "blown_out"; p_race: number; p_too_light?: number; p_blown_out?: number;
  wind_kn: number; gust_max_kn?: number; gust_max_at?: string; dir: number; why?: string;
};
export type Shift = { kind: "unreliable" | "steady" | "shift"; side?: "left" | "right"; size_deg?: number; at?: string; p?: number; advice?: string };
export type Water = {
  chop?: { m: number; period_s: number; max_m: number; label: string };
  waves?: { m: number; period_s: number; swell_m: number };
  stream?: { kn: number; to_dir: number; wind_against_tide: boolean };
  tide?: { kind: "high" | "low"; time: string; height_m: number }[];
};
export type Hour = { time: string; wind_kn?: number; gust_kn?: number; wind_dir?: number; chop_m?: number; current_kn?: number };
export type Briefing = {
  date: string; start: string; fleet: string; fleet_name: string; gun: string; window_h?: number; call: Call;
  shift?: Shift; rig?: { band: string; tip: string }; water?: Water; hourly?: Hour[]; sensor_used?: boolean;
};
export type Briefings = { club: string; plan: Plan; sensor: { time: string; wind_kn: number; gust_kn: number; dir: number } | null; briefings: Briefing[] };
export type Fleet = { cls: string; name: string; min_kn: number; max_gust_kn: number; club_limit: boolean };
export type ClubView = { slug: string; name: string; country: string; tz: string; licensed: boolean; tier: string; fleets: Fleet[];
  starts: { id: number; date: string; time: string; fleets: string[]; window_h: number; event_id: number | null }[] };
export type Notice = { id: number; text: string; created: string; event_id: number | null; pushed: number };
export type EventSummary = { slug: string; name: string; first_day: string; last_day: string; classes: string[]; entries: number | null; url: string };
export type Live = { club: string; name: string; sensors: { label: string; model: string;
  latest: null | { time: string; wind_kn: number; gust_kn: number | null; dir: number | null; age_min: number; fresh: boolean };
  trace: { time: string; wind_kn: number; gust_kn: number | null; dir: number | null }[] }[] };

export function localTime(iso: string, tz?: string) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz });
  } catch { return iso.slice(11, 16); }
}
