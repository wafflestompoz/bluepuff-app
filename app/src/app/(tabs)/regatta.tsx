import React, { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import { useSession } from "../../lib/session";
import { useApi } from "../../lib/hooks";
import { API_URL, EventSummary } from "../../lib/api";
import { dayLabel, pct } from "../../lib/format";
import { useColors } from "../../lib/theme";
import { Button, Card, CallPill, Chip, ClubSwitcher, H, Message, Screen, T, styles } from "../../components/ui";

type EventView = {
  name: string; club: { name: string }; entries: number | null;
  days: { date: string; label: string; tide: { kind: string; local: string }[];
    races: { gun_local: string; fleet_name: string; call: { call: string; p_race: number; wind_kn: number; gust_max_kn: number } }[] }[];
  notices: { id: number; text: string; local: string }[];
};

export default function Regatta() {
  const { club } = useSession(); const c = useColors();
  const list = useApi<EventSummary[]>(club ? `/clubs/${club.slug}/events` : null);
  const [pick, setPick] = useState<string | null>(null);
  const slug = pick ?? list.data?.[0]?.slug ?? null;
  const ev = useApi<EventView>(slug ? `/events/${slug}` : null);
  if (!club) return <Screen title="Regatta"><Message text="Join a club first." /></Screen>;
  return (
    <Screen title="Regatta" sub={club.name} refreshing={ev.loading} onRefresh={() => { list.reload(); ev.reload(); }}>
      <ClubSwitcher />
      {list.data && list.data.length === 0 && <Message text="No regattas coming up at this club. Clubs on Club Pro publish up to four regatta pages a year." />}
      {list.data && list.data.length > 1 && (
        <View style={[styles.row, { flexWrap: "wrap" }]}>
          {list.data.map((e) => <Chip key={e.slug} label={e.name} active={slug === e.slug} onPress={() => setPick(e.slug)} />)}
        </View>
      )}
      {ev.data && (
        <>
          <Card style={{ backgroundColor: c.blue, borderColor: c.blue }}>
            <T bold size={22} style={{ color: "#fff" }}>{ev.data.name}</T>
            <T style={{ color: "#CFE0FF" }}>{ev.data.days[0]?.label} to {ev.data.days[ev.data.days.length - 1]?.label}{ev.data.entries ? ` · ${ev.data.entries} entries` : ""}</T>
            <Button kind="light" title="Open the public page" onPress={() => Linking.openURL(`${API_URL}/r/${slug}`)} />
          </Card>
          <Card><H>Notices</H>
            {ev.data.notices.length === 0 ? <T muted>No notices yet.</T> : ev.data.notices.map((n) => (
              <View key={n.id} style={{ marginTop: 6 }}><T muted size={12}>{n.local}</T><T>{n.text}</T></View>))}
          </Card>
          {ev.data.days.map((d) => (
            <Card key={d.date}>
              <H>{d.label}</H>
              {d.tide.length > 0 && <T muted size={13}>{d.tide.map((t) => `${t.kind === "high" ? "HW" : "LW"} ${t.local}`).join(" · ")}</T>}
              {d.races.length === 0 ? <T muted>Forecast appears about a week ahead.</T> : d.races.map((r, i) => (
                <View key={i} style={[styles.between, { paddingVertical: 6, borderTopWidth: i ? 1 : 0, borderTopColor: c.line }]}>
                  <T style={{ flex: 1 }}>{r.gun_local} {r.fleet_name}</T>
                  <T muted size={14} style={{ marginRight: 8 }}>{Math.round(r.call.wind_kn)}/{Math.round(r.call.gust_max_kn)} kn · {pct(r.call.p_race)}</T>
                  <CallPill call={r.call.call} />
                </View>
              ))}
            </Card>
          ))}
        </>
      )}
    </Screen>
  );
}
