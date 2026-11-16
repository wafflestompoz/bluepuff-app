import React, { useEffect, useState } from "react";
import { Linking, View } from "react-native";
import { api } from "../lib/api";
import { buy, Offer, offers, restore, storeAvailable } from "../lib/purchases";
import { useSession } from "../lib/session";
import { Button, Card, H, T, styles } from "./ui";

/** Sailor plans, bought in the app store. Prices come from the store, so they show in the sailor's currency. */
export function SailorPlans() {
  const { me, refresh } = useSession();
  const [list, setList] = useState<Offer[]>([]); const [msg, setMsg] = useState<string | null>(null); const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { if (me) offers(me.id).then(setList).catch(() => setList([])); }, [me?.id]);
  if (!me || me.plan === "racer_pro") return null;
  const after = async () => { for (let i = 0; i < 5; i++) { await new Promise((r) => setTimeout(r, 1500)); await refresh(); } };
  const go = async (o: Offer) => {
    setBusy(o.id); setMsg(null);
    try { await buy(o); setMsg("Thanks! Your plan updates in a few seconds."); await after(); }
    catch (e: any) { if (!e?.userCancelled) setMsg(e?.message ?? "The purchase didn't go through."); }
    finally { setBusy(null); }
  };
  return (
    <Card>
      <H>{me.plan === "free" ? "Upgrade" : "Racer Pro"}</H>
      <T muted size={14}>{me.plan === "free"
        ? "Racer: 7 days ahead, three clubs, shift and tack advice, rig settings, water and live club wind. Racer Pro adds every venue for travel and coaching."
        : "Every venue, not just your three clubs: for travel regattas and coaches."}</T>
      {!storeAvailable() && <T muted size={14} style={{ marginTop: 8 }}>Subscribe in the bluepuff app for iPhone or Android.</T>}
      {list.map((o) => <Button key={o.id} title={`${o.title} · ${o.price}${o.period ? ` ${o.period}` : ""}`} busy={busy === o.id} onPress={() => go(o)} />)}
      {storeAvailable() && <Button kind="ghost" title="Restore purchases" onPress={async () => { await restore(me.id); await after(); }} />}
      {msg && <T style={{ marginTop: 8 }}>{msg}</T>}
    </Card>
  );
}

const TIERS = [
  { tier: "club", name: "Club", line: "Up to 50 sailors on Racer · €590 a year" },
  { tier: "plus", name: "Club Plus", line: "Up to 150 sailors, one wind sensor shipped for you to fit · €990 a year, 2-year term" },
  { tier: "pro", name: "Club Pro", line: "Up to 250 sailors, two sensors, 4 regatta pages a year, 5 coach seats · €1,690 a year, 2-year term" },
];

/** Club admins buy the licence on the web (Stripe Checkout). */
export function ClubLicence({ slug, tier }: { slug: string; tier: string }) {
  const [msg, setMsg] = useState<string | null>(null);
  const go = async (t: string) => {
    setMsg(null);
    try { const r = await api<{ url: string }>(`/clubs/${slug}/checkout`, { body: { tier: t } }); Linking.openURL(r.url); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <Card>
      <H>Club licence</H>
      <T muted size={14}>Every sailor who joins with your club code gets Racer, paid by the club.</T>
      {TIERS.map((t) => (
        <View key={t.tier} style={{ marginTop: 10 }}>
          <T bold>{t.name}{t.tier === tier ? " · current" : ""}</T><T muted size={14}>{t.line}</T>
          {t.tier !== tier && <Button kind="ghost" title={`Choose ${t.name}`} onPress={() => go(t.tier)} />}
        </View>
      ))}
      {msg && <T style={{ marginTop: 8 }}>{msg}</T>}
    </Card>
  );
}
