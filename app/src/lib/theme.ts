import { useColorScheme } from "react-native";

const light = {
  bg: "#F6F8FC", card: "#FFFFFF", fg: "#0B1B33", muted: "#5B6B85", line: "#E3E8F1",
  blue: "#0A4DA8", on: "#1F8A4C", marginal: "#C98A00", off: "#B3261E", tint: "#E8F0FB", land: "#D9D4C7",
};
const dark: typeof light = {
  bg: "#07142A", card: "#0D2142", fg: "#EEF3FB", muted: "#9FB0CC", line: "#1D3561",
  blue: "#4F9BFF", on: "#3DBE73", marginal: "#E8AE2A", off: "#F06A5F", tint: "#12305E", land: "#2A3445",
};
export type Colors = typeof light;
export function useColors(): Colors {
  return useColorScheme() === "dark" ? dark : light;
}

export const CALLS: Record<string, { word: string; key: "on" | "marginal" | "off"; line: string }> = {
  race_on: { word: "Racing on", key: "on", line: "Wind should stay inside your class limits." },
  marginal: { word: "Marginal", key: "marginal", line: "Close to a limit. The race officer decides on the water." },
  too_light: { word: "Too light", key: "off", line: "Likely postponement for lack of wind." },
  blown_out: { word: "Too windy", key: "off", line: "Gusts likely past your class limit." },
};
