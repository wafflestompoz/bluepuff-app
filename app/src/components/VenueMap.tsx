import React, { useMemo, useState } from "react";
import { View } from "react-native";
import Svg, { G, Line, Polygon, Rect, Text as SvgText } from "react-native-svg";
import { useColors } from "../lib/theme";
import { VenueMapData } from "../lib/api";
import { T } from "./ui";

/** The race area, 2.4 km across, north up: land in grey, water shaded by how much of the open-water wind reaches it
 * (darker = more wind, as puffs look on the water), with the wind arrow and the beat's left and right sides. */
export function VenueMap({ map, sector }: { map: VenueMapData; sector: number }) {
  const c = useColors(); const [w, setW] = useState(300);
  const n = map.n; const g = map.grids[sector]; const px = w / n; const frm = sector * 22.5;
  const cells = useMemo(() => {
    const out: { x: number; y: number; fill: string }[] = [];
    for (let r = 0; r < n; r++) for (let q = 0; q < n; q++) {
      const ch = g[r * n + q];
      if (ch === "!") out.push({ x: q, y: r, fill: c.land });
      else { const p = (ch.charCodeAt(0) - 35) * 2; out.push({ x: q, y: r, fill: mix(c.card, c.blue, Math.max(0.08, Math.min(0.9, (p - 60) / 42))) }); }
    }
    return out;
  }, [g, n, c]);
  const th = (frm * Math.PI) / 180; const cx = w / 2; const L = w * 0.42;
  const ux = Math.sin(th), uy = -Math.cos(th);                 // toward where the wind comes from (screen y down)
  const head = { x: cx + ux * L * 0.35, y: cx + uy * L * 0.35 };
  const tail = { x: cx + ux * L, y: cx + uy * L };
  const lx = uy, ly = -ux;                                      // looking upwind, the left-hand side (screen y runs down)
  const arrow = `${head.x},${head.y} ${head.x + ux * 12 + lx * 7},${head.y + uy * 12 + ly * 7} ${head.x + ux * 12 - lx * 7},${head.y + uy * 12 - ly * 7}`;
  return (
    <View onLayout={(e) => setW(Math.min(e.nativeEvent.layout.width, 420))} style={{ marginTop: 8 }}
      accessibilityLabel={`Map of the race area with the wind from ${Math.round(frm)} degrees`}>
      <Svg width={w} height={w}>
        <Rect x={0} y={0} width={w} height={w} fill={c.card} />
        <G shapeRendering="crispEdges">{cells.map((k) => <Rect key={k.y * n + k.x} x={k.x * px} y={k.y * px} width={px + 0.5} height={px + 0.5} fill={k.fill} />)}</G>
        <Line x1={tail.x} y1={tail.y} x2={head.x + ux * 10} y2={head.y + uy * 10} stroke={c.off} strokeWidth={3} />
        <Polygon points={arrow} fill={c.off} />
        <SvgText x={cx - lx * w * 0.32} y={cx - ly * w * 0.32} fontSize={12} fontFamily="System" fontWeight="bold" fill={c.fg} textAnchor="middle">right</SvgText>
        <SvgText x={cx + lx * w * 0.32} y={cx + ly * w * 0.32} fontSize={12} fontFamily="System" fontWeight="bold" fill={c.fg} textAnchor="middle">left</SvgText>
        <SvgText x={w - 6} y={14} fontSize={11} fontFamily="System" fill={c.muted} textAnchor="end">N ↑ · {map.size_m / 1000} km across</SvgText>
      </Svg>
      <T muted size={12}>Darker water = more wind. Estimated from the shore, trees, buildings and hills; not yet checked on the water.</T>
    </View>
  );
}

/** Solid colour a fraction t of the way from a to b (hex), so neighbouring cells never double up at their edges. */
function mix(a: string, b: string, t: number) {
  const h = (x: string) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const A = h(a), B = h(b);
  return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
}
