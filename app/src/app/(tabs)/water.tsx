import React from "react";
import { View } from "react-native";
import { useSession } from "../../lib/session";
import { useApi } from "../../lib/hooks";
import { Briefings, ClubView, localTime } from "../../lib/api";
import { compass, dayLabel } from "../../lib/format";
import { useColors } from "../../lib/theme";
import { Card, ClubSwitcher, H, Message, Screen, T, Upsell, styles } from "../../components/ui";

export default function Water() {
  const { club } = useSession(); const c = useColors();
  const b = useApi<Briefings>(club ? `/clubs/${club.slug}/briefings` : null);
  const cv = useApi<ClubView>(club ? `/clubs/${club.slug}` : null);
  if (!club) return <Screen title="Water"><Message text="Join a club first." /></Screen>;
  const tz = cv.data?.tz;
  const seen = new Set<string>();
  const days = (b.data?.briefings ?? []).filter((x) => x.water && !seen.has(x.date) && seen.add(x.date));
  return (
    <Screen title="Water" sub={`${club.name} · tide, chop and stream at race time`} refreshing={b.loading} onRefresh={b.reload}>
      <ClubSwitcher />
      {b.data?.plan === "free" && <Upsell what="tide times, chop, waves and stream for every start" />}
      {b.data && b.data.plan !== "free" && days.length === 0 && <Message text="No starts with a water forecast yet." />}
      {days.map((x) => {
        const w = x.water!;
        return (
          <Card key={x.date}>
            <H>{dayLabel(x.date)} · first gun {x.start}</H>
            {w.tide && w.tide.length > 0 && (
              <View style={[styles.row, { flexWrap: "wrap", marginBottom: 6 }]}>
                {w.tide.map((t) => (
                  <View key={t.time} style={{ marginRight: 18, marginTop: 4 }}>
                    <T muted size={12}>{t.kind === "high" ? "High water" : "Low water"}</T>
                    <T bold size={18}>{localTime(t.time, tz)}</T><T muted size={12}>{t.height_m.toFixed(1)} m</T>
                  </View>
                ))}
              </View>
            )}
            {w.chop && <Row k="Chop" v={`${w.chop.label} (${w.chop.max_m.toFixed(2)} m, ${w.chop.period_s.toFixed(0)} s)`} />}
            {w.waves && <Row k="Waves" v={`${w.waves.m.toFixed(1)} m, ${w.waves.period_s.toFixed(0)} s${w.waves.swell_m > 0.2 ? `, swell ${w.waves.swell_m.toFixed(1)} m` : ""}`} />}
            {w.stream && <Row k="Stream" v={`${w.stream.kn.toFixed(1)} kn towards ${compass(w.stream.to_dir)}`} />}
            {w.stream?.wind_against_tide && <T style={{ color: c.marginal, marginTop: 6 }} bold>Wind against tide: expect steeper, shorter chop.</T>}
            {x.hourly && (
              <View style={{ marginTop: 10 }}>
                {x.hourly.map((h) => (
                  <View key={h.time} style={[styles.between, { paddingVertical: 4, borderTopWidth: 1, borderTopColor: c.line }]}>
                    <T muted size={14}>{localTime(h.time, tz)}</T>
                    <T size={14}>{Math.round(h.wind_kn ?? 0)}–{Math.round(h.gust_kn ?? 0)} kn {compass(h.wind_dir)}</T>
                    <T muted size={14}>{h.current_kn != null ? `${h.current_kn.toFixed(1)} kn stream` : ""}</T>
                  </View>
                ))}
              </View>
            )}
          </Card>
        );
      })}
    </Screen>
  );
}

const Row = ({ k, v }: { k: string; v: string }) => (
  <View style={[styles.row, { marginTop: 4 }]}><T muted style={{ width: 70 }}>{k}</T><T style={{ flex: 1 }}>{v}</T></View>
);
