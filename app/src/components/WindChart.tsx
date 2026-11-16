import React, { useState } from "react";
import { View } from "react-native";
import Svg, { Line, Path, Rect, Text as SvgText } from "react-native-svg";
import { useColors } from "../lib/theme";
import { Hour, localTime } from "../lib/api";

/** Wind and gusts through the racing window, with the class's gust limit and minimum wind drawn across. */
export function WindChart({ hours, limit, min, tz, height = 150 }: { hours: Hour[]; limit?: number; min?: number; tz?: string; height?: number }) {
  const c = useColors(); const [w, setW] = useState(320);
  const pts = hours.filter((h) => h.wind_kn != null);
  if (pts.length < 2) return null;
  const pad = { l: 28, r: 8, t: 10, b: 22 };
  const top = Math.max(...pts.map((h) => h.gust_kn ?? h.wind_kn ?? 0), limit ?? 0) * 1.15 || 1;
  const x = (i: number) => pad.l + (i / (pts.length - 1)) * (w - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / top) * (height - pad.t - pad.b);
  const path = (k: "wind_kn" | "gust_kn") => pts.map((h, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(h[k] ?? h.wind_kn ?? 0).toFixed(1)}`).join("");
  const ticks = [0, Math.round(top / 2), Math.round(top * 0.9)];
  return (
    <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ marginTop: 8 }}
      accessibilityLabel={`Wind ${Math.round(pts[0].wind_kn ?? 0)} knots, gusts up to ${Math.round(Math.max(...pts.map((h) => h.gust_kn ?? 0)))}${limit ? `, limit ${limit}` : ""}`}>
      <Svg width={w} height={height}>
        {ticks.map((t) => (
          <React.Fragment key={t}>
            <Line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} stroke={c.line} strokeWidth={1} />
            <SvgText x={pad.l - 4} y={y(t) + 4} fontSize={10} fontFamily="System" fill={c.muted} textAnchor="end">{t}</SvgText>
          </React.Fragment>
        ))}
        {limit != null && <>
          <Rect x={pad.l} y={pad.t} width={w - pad.l - pad.r} height={Math.max(0, y(limit) - pad.t)} fill={c.off} opacity={0.08} />
          <Line x1={pad.l} x2={w - pad.r} y1={y(limit)} y2={y(limit)} stroke={c.off} strokeWidth={1.5} strokeDasharray="5 4" />
          <SvgText x={w - pad.r} y={y(limit) - 4} fontSize={10} fontFamily="System" fill={c.off} textAnchor="end">gust limit {limit} kn</SvgText>
        </>}
        {min != null && <Line x1={pad.l} x2={w - pad.r} y1={y(min)} y2={y(min)} stroke={c.marginal} strokeWidth={1.5} strokeDasharray="2 4" />}
        <Path d={path("gust_kn")} stroke={c.muted} strokeWidth={2} fill="none" strokeDasharray="4 3" />
        <Path d={path("wind_kn")} stroke={c.blue} strokeWidth={3} fill="none" />
        {pts.map((h, i) => (i % Math.max(1, Math.round(pts.length / 4)) === 0 || i === pts.length - 1) && (
          <SvgText key={h.time} x={x(i)} y={height - 6} fontSize={10} fontFamily="System" fill={c.muted} textAnchor={i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}>{localTime(h.time, tz)}</SvgText>
        ))}
      </Svg>
    </View>
  );
}
