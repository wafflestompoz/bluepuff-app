import React from "react";
import { View } from "react-native";
import { router } from "expo-router";
import { useSession } from "../../lib/session";
import { useApi } from "../../lib/hooks";
import { Briefing, Briefings, ClubView, Notice } from "../../lib/api";
import { CALLS, useColors } from "../../lib/theme";
import { compass, dayLabel, pct } from "../../lib/format";
import { Button, Card, CallPill, ClubSwitcher, H, Message, Screen, T, Upsell, styles } from "../../components/ui";
import { WindChart } from "../../components/WindChart";

export default function Race() {
  const { club } = useSession();
  const b = useApi<Briefings>(club ? `/clubs/${club.slug}/briefings` : null);
  const cv = useApi<ClubView>(club ? `/clubs/${club.slug}` : null);
  const notices = useApi<Notice[]>(club ? `/clubs/${club.slug}/notices?limit=1` : null);
  const reload = () => { b.reload(); notices.reload(); };

  if (!club) return (
    <Screen title="Race"><Message text="Join your club to see race calls for its starts."
      action={<Button title="Find my club" onPress={() => router.push("/club")} />} /></Screen>
  );
  const mine = (b.data?.briefings ?? []).filter((x) => !club.fleet || x.fleet === club.fleet);
  const byDay = groupBy(mine, (x) => x.date);
  return (
    <Screen title="Race" sub={club.name} refreshing={b.loading} onRefresh={reload}>
      <ClubSwitcher />
      {notices.data?.[0] && <Card style={{ borderLeftWidth: 4, borderLeftColor: "#0A4DA8" }}>
        <T muted size={13}>From the race office</T><T>{notices.data[0].text}</T></Card>}
      {b.data?.sensor && <LiveStrip s={b.data.sensor} />}
      {b.error && <Message text={b.error} />}
      {b.data && mine.length === 0 && <Message text={club.fleet
        ? "No starts for your class in the next few days. The race officer adds them to the programme."
        : "No starts in the programme yet. Pick your class on the Club tab to see just yours."} />}
      {Object.entries(byDay).map(([d, list]) => (
        <View key={d}>
          <T bold size={13} style={{ marginTop: 18, textTransform: "uppercase", letterSpacing: 0.6 }} muted>{dayLabel(d)}</T>
          {list.map((x) => <BriefingCard key={x.date + x.start + x.fleet} b={x} cv={cv.data} free={b.data?.plan === "free"} />)}
        </View>
      ))}
      {b.data?.plan === "free" && <Upsell what="7 days ahead, shift and tack advice, rig settings, water and live club wind" />}
    </Screen>
  );
}

function BriefingCard({ b, cv, free }: { b: Briefing; cv: ClubView | null; free: boolean }) {
  const c = useColors(); const call = b.call; const fl = cv?.fleets.find((f) => f.cls === b.fleet);
  return (
    <Card>
      <View style={styles.between}><H>{b.start} · {b.fleet_name}</H><CallPill call={call.call} /></View>
      <View style={[styles.row, { marginTop: 4 }]}>
        <T size={40} bold style={{ color: c[CALLS[call.call].key] }}>{pct(call.p_race)}</T>
        <T muted style={{ marginLeft: 10, flex: 1 }}>chance of racing. {CALLS[call.call].line}</T>
      </View>
      <T style={{ marginTop: 6 }}>
        {Math.round(call.wind_kn)} kn from {compass(call.dir)} ({Math.round(call.dir)}°)
        {call.gust_max_kn != null ? `, gusts to ${Math.round(call.gust_max_kn)} kn` : ""}
      </T>
      {call.why ? <T muted size={14}>{call.why}</T> : null}
      {!free && b.hourly && <WindChart hours={b.hourly} limit={fl?.max_gust_kn} min={fl?.min_kn} tz={cv?.tz} />}
      {b.shift?.kind === "shift" && <Tip title={`Shift: ${b.shift.side} ${b.shift.size_deg}°${b.shift.p != null ? ` (${pct(b.shift.p)} of models agree)` : ""}`} text={b.shift.advice!} />}
      {b.shift?.kind === "steady" && <Tip title="Steady direction" text="No big shift expected in the racing window. Play the puffs." />}
      {b.shift?.kind === "unreliable" && <Tip title="Shifty and light" text="Direction is unreliable at this strength. Keep your head out of the boat." />}
      {b.rig && <Tip title={`Rig: ${b.rig.band} air`} text={b.rig.tip} />}
      {b.sensor_used && <T muted size={12} style={{ marginTop: 8 }}>Adjusted with the club sensor's latest reading.</T>}
    </Card>
  );
}

function Tip({ title, text }: { title: string; text: string }) {
  const c = useColors();
  return <View style={{ backgroundColor: c.tint, borderRadius: 10, padding: 10, marginTop: 10 }}><T bold size={14}>{title}</T><T size={14}>{text}</T></View>;
}

function LiveStrip({ s }: { s: NonNullable<Briefings["sensor"]> }) {
  const age = Math.round((Date.now() - new Date(s.time).getTime()) / 60000);
  return (
    <Card>
      <T muted size={13}>On the water now · club sensor · {age <= 1 ? "just now" : `${age} min ago`}</T>
      <T size={22} bold>{Math.round(s.wind_kn)} kn{s.gust_kn != null ? `, gusts ${Math.round(s.gust_kn)}` : ""} {s.dir != null ? `from ${compass(s.dir)}` : ""}</T>
    </Card>
  );
}

function groupBy<T>(xs: T[], k: (x: T) => string) {
  return xs.reduce((a, x) => { (a[k(x)] ||= []).push(x); return a; }, {} as Record<string, T[]>);
}
