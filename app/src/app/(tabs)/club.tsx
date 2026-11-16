import React, { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import { useSession } from "../../lib/session";
import { useApi } from "../../lib/hooks";
import { api, API_URL, ClubView, Notice } from "../../lib/api";
import { useColors } from "../../lib/theme";
import { Button, Card, Chip, Field, H, Message, Screen, T, styles } from "../../components/ui";
import { ClubLicence, SailorPlans } from "../../components/Upgrade";

const PLAN = { free: "Free", racer: "Racer", racer_pro: "Racer Pro" } as const;

export default function Club() {
  const { me, club, refresh, signOut, setClubSlug } = useSession(); const c = useColors();
  const [code, setCode] = useState(""); const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const cv = useApi<ClubView>(club ? `/clubs/${club.slug}` : null);
  const notices = useApi<Notice[]>(club ? `/clubs/${club.slug}/notices` : null);
  const found = useApi<{ slug: string; name: string; country: string }[]>(q.length >= 2 ? `/clubs?q=${encodeURIComponent(q)}` : null);
  if (!me) return null;

  const act = async (f: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await f(); await refresh(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Screen title="Club" sub={`${me.email} · ${PLAN[me.plan]}${me.plan_via ? ` via ${me.plan_via}` : ""}`}>
      {me.clubs.map((k) => (
        <Card key={k.slug} style={club?.slug === k.slug ? { borderColor: c.blue } : undefined}>
          <Pressable onPress={() => setClubSlug(k.slug)}>
            <View style={styles.between}><H>{k.name}</H><T muted size={13}>{k.home ? "Home club" : "Following"}{k.role !== "member" ? ` · ${k.role}` : ""}</T></View>
          </Pressable>
          {club?.slug === k.slug && cv.data && (
            <>
              <T muted size={13}>Your class (the race call uses its limits)</T>
              <View style={[styles.row, { flexWrap: "wrap" }]}>
                {cv.data.fleets.map((f) => (
                  <Chip key={f.cls} label={f.name} active={k.fleet === f.cls}
                    onPress={() => act(() => api(`/me/clubs/${k.slug}`, { method: "PATCH", body: { fleet: f.cls } }))} />
                ))}
              </View>
              <Button kind="ghost" title="Live wind in the clubhouse" onPress={() => Linking.openURL(`${API_URL}/clubs/${k.slug}/clubhouse`)} />
              <Button kind="danger" title={`Leave ${k.name}`} onPress={() => act(() => api(`/me/clubs/${k.slug}`, { method: "DELETE" }))} />
            </>
          )}
        </Card>
      ))}

      <Card>
        <H>Join your club</H>
        <T muted size={14}>Your club's code is on the noticeboard or from your race officer. If the club has a bluepuff licence, Racer is included.</T>
        <Field label="Club code" value={code} onChangeText={setCode} autoCapitalize="characters" placeholder="e.g. 7KQ2HF" />
        <Button title="Join" busy={busy} disabled={code.length < 4} onPress={() => act(async () => { await api("/me/clubs", { body: { code } }); setCode(""); })} />
      </Card>

      <Card>
        <H>Follow another venue</H>
        <T muted size={14}>For travel regattas. Free accounts follow one club, Racer follows three.</T>
        <Field label="Search clubs" value={q} onChangeText={setQ} placeholder="Club name" />
        {found.data?.map((f) => (
          <View key={f.slug} style={[styles.between, { marginTop: 8 }]}>
            <T>{f.name} <T muted size={13}>{f.country}</T></T>
            <Button kind="ghost" title="Follow" onPress={() => act(() => api("/me/clubs", { body: { slug: f.slug } }))} />
          </View>
        ))}
      </Card>
      {err && <Message text={err} />}

      <SailorPlans />
      {club?.role === "admin" && cv.data && <ClubLicence slug={club.slug} tier={cv.data.licensed ? cv.data.tier : "none"} />}

      {club && <Card><H>Notices from {club.name}</H>
        {(notices.data ?? []).length === 0 ? <T muted>Nothing yet.</T> : notices.data!.map((n) => (
          <View key={n.id} style={{ marginTop: 8 }}><T muted size={12}>{new Date(n.created).toLocaleString()}</T><T>{n.text}</T></View>))}
      </Card>}

      <Button kind="ghost" title="Sign out" onPress={signOut} />
    </Screen>
  );
}
