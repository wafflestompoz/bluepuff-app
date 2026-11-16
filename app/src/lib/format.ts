export const dayLabel = (d: string) =>
  new Date(d + "T12:00:00Z").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
export const compass = (deg?: number | null) =>
  deg == null ? "" : ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][Math.round(deg / 22.5) % 16];
export const pct = (p: number) => `${Math.round(p * 100)}%`;
