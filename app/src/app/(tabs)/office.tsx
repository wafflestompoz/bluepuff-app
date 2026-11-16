import React, { useMemo, useState } from "react";
import { Platform, Pressable, Share, View } from "react-native";
import { useSession } from "../../lib/session";
import { useApi } from "../../lib/hooks";
import { api, Briefing, Briefings, ClubView } from "../../lib/api";
import { compass, dayLabel, pct } from "../../lib/format";
import { CALLS, useColors } from "../../lib/theme";
import { Button, Card, CallPill, Chip, Field, H, Message, Screen, T, styles } from "../../components/ui";
import { WindChart } from "../../components/WindChart";

/** Race officer view: starts against each fleet's limits, course axis, the call to members, the programme and limits. */
export default function Office() {
  const { me } = useSession(); const c = useColors();
  const mine = (me?.clubs ?? []).filter((k) => k.role === "officer" || k.role === "admin");
  const [slug, setSlug] = useState<string | null>(null);
  const k = mine.find((x) => x.slug === slug) ?? mine[0];
  const cv = useApi<ClubView>(k ? `/clubs/${k.slug}` : null);
  const b = useApi<Briefings>(k ? `/clubs/${k.slug}/briefings` : null);
  const [section, setSection] = useState<"day" | "programme" | "limits" | "regatta" | "people">("day");
  if (!k) return <Screen title="Race office"><Message text="Only race officers see this tab." /></Screen>;
  const reload = () => { cv.reload(); b.reload(); };
  return (
    <Screen title="Race office" sub={k.name} refreshing={b.loading} onRefresh={reload}>
      {mine.length > 1 && <View style={[styles.row, { flexWrap: "wrap" }]}>{mine.map((x) => <Chip key={x.slug} label={x.name} active={x.slug === k.slug} onPress={() => setSlug(x.slug)} />)}</View>}
      <View style={[styles.row, { flexWrap: "wrap", marginTop: 4 }]}>
        {(["day", "programme", "limits", "regatta", "people"] as const).filter((s) => s !== "people" || k.role === "admin").map((s) => (
          <Chip key={s} label={{ day: "Race day", programme: "Programme", limits: "Fleet limits", regatta: "Regattas", people: "Officers & coaches" }[s]}
            active={section === s} onPress={() => setSection(s)} />
        ))}
      </View>
      {section === "day" && <RaceDay slug={k.slug} b={b.data} cv={cv.data} error={b.error} />}
      {section === "programme" && cv.data && <Programme cv={cv.data} onChange={reload} />}
      {section === "limits" && cv.data && <Limits cv={cv.data} onChange={reload} />}
      {section === "regatta" && cv.data && <Regattas cv={cv.data} onChange={reload} />}
      {section === "people" && <People slug={k.slug} />}
    </Screen>
  );
}

function meanDir(b: Briefing) {
  const hs = (b.hourly ?? []).filter((h) => h.wind_dir != null);
  if (!hs.length) return b.call.dir;
  const s = hs.reduce((a, h) => a + Math.sin((h.wind_dir! * Math.PI) / 180), 0), co = hs.reduce((a, h) => a + Math.cos((h.wind_dir! * Math.PI) / 180), 0);
  return ((Math.atan2(s, co) * 180) / Math.PI + 360) % 360;
}

function callText(club: string, list: Briefing[]) {
  return `${club} race call\n` + list.map((x) => `${x.start} ${x.fleet_name}: ${CALLS[x.call.call].word} (${Math.round(x.call.wind_kn)} kn, gusts ${Math.round(x.call.gust_max_kn ?? x.call.wind_kn)}, ${pct(x.call.p_race)} chance of racing)`).join("\n");
}

function RaceDay({ slug, b, cv, error }: { slug: string; b: Briefings | null; cv: ClubView | null; error: string | null }) {
  const c = useColors();
  const days = useMemo(() => Array.from(new Set((b?.briefings ?? []).map((x) => x.date))), [b]);
  const [day, setDay] = useState<string | null>(null);
  const d = day ?? days[0];
  const list = (b?.briefings ?? []).filter((x) => x.date === d);
  const [note, setNote] = useState(""); const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null);
  const today = d === days[0];
  const send = async (withCall: boolean) => {
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ pushed: number }>(`/clubs/${slug}/notices`, { body: { text: note || null, send_call: withCall } });
      setMsg(`Sent to ${r.pushed} phone${r.pushed === 1 ? "" : "s"} and posted on the club's notices.`); setNote("");
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  const print = () => {
    const text = callText(cv?.name ?? slug, list);
    if (Platform.OS === "web") (globalThis as any).print?.(); else Share.share({ message: text });
  };
  if (error) return <Message text={error} />;
  if (b && !list.length) return <Message text="No starts in the next week. Add them under Programme." />;
  return (
    <>
      <View style={[styles.row, { flexWrap: "wrap" }]}>{days.map((x) => <Chip key={x} label={dayLabel(x)} active={x === d} onPress={() => setDay(x)} />)}</View>
      {list.map((x) => {
        const fl = cv?.fleets.find((f) => f.cls === x.fleet); const axis = meanDir(x);
        return (
          <Card key={x.start + x.fleet}>
            <View style={styles.between}><H>{x.start} · {x.fleet_name}</H><CallPill call={x.call.call} /></View>
            <T>{pct(x.call.p_race)} chance of racing · {Math.round(x.call.wind_kn)} kn, gusts {Math.round(x.call.gust_max_kn ?? 0)}
              {fl ? ` · limits ${fl.min_kn}–${fl.max_gust_kn} kn${fl.club_limit ? " (club)" : ""}` : ""}</T>
            {x.call.p_blown_out != null && x.call.p_too_light != null &&
              <T muted size={13}>{pct(x.call.p_too_light)} too light · {pct(x.call.p_blown_out)} over the gust limit</T>}
            {x.hourly && <WindChart hours={x.hourly} limit={fl?.max_gust_kn} min={fl?.min_kn} tz={cv?.tz} />}
            <View style={{ backgroundColor: c.tint, borderRadius: 10, padding: 10, marginTop: 8 }}>
              <T bold size={14}>Course: windward mark at {Math.round(axis)}° ({compass(axis)})</T>
              <T size={14}>{x.shift?.kind === "shift" ? `${x.shift.advice} Consider setting the mark a little ${x.shift.side} of the axis and be ready to move it.` :
                x.shift?.kind === "unreliable" ? "Direction unreliable in light air: wait for it to settle before laying the course." : "Direction steady through the window."}</T>
            </View>
          </Card>
        );
      })}
      {today && list.length > 0 && (
        <Card>
          <H>Send the call to members</H>
          <T muted size={14}>Pushes to every member's phone and posts on the club notices. The race call for today's starts is added below your note.</T>
          <Field label="Note (optional)" value={note} onChangeText={setNote} multiline placeholder="e.g. Briefing 10:00, course 2" style={{ minHeight: 70 }} />
          <Button title="Send the call" busy={busy} onPress={() => send(true)} />
          <Button kind="ghost" title="Send the note only" disabled={!note} onPress={() => send(false)} />
          <Button kind="ghost" title={Platform.OS === "web" ? "Print the day" : "Share the call"} onPress={print} />
          {msg && <T style={{ marginTop: 8 }}>{msg}</T>}
        </Card>
      )}
    </>
  );
}

function Programme({ cv, onChange }: { cv: ClubView; onChange: () => void }) {
  const c = useColors();
  const tomorrow = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  const [date, setDate] = useState(tomorrow); const [time, setTime] = useState("11:00"); const [win, setWin] = useState("2.5");
  const [fleets, setFleets] = useState<string[]>([]); const [err, setErr] = useState<string | null>(null);
  const add = async () => {
    setErr(null);
    try { await api(`/clubs/${cv.slug}/starts`, { body: { date, time, fleets, window_h: Number(win) } }); setFleets([]); onChange(); }
    catch (e: any) { setErr(e.message); }
  };
  return (
    <>
      <Card>
        <H>Next two weeks</H>
        {cv.starts.length === 0 && <T muted>No starts yet.</T>}
        {cv.starts.map((s) => (
          <View key={s.id} style={[styles.between, { paddingVertical: 6, borderTopWidth: 1, borderTopColor: c.line }]}>
            <T style={{ flex: 1 }}>{dayLabel(s.date)} {s.time} · {s.fleets.map((f) => cv.fleets.find((x) => x.cls === f)?.name ?? f).join(", ")}</T>
            <Pressable onPress={async () => { await api(`/clubs/${cv.slug}/starts/${s.id}`, { method: "DELETE" }); onChange(); }}>
              <T style={{ color: c.off }}>Remove</T></Pressable>
          </View>
        ))}
      </Card>
      <Card>
        <H>Add a start</H>
        <View style={styles.row}>
          <View style={{ flex: 2, marginRight: 8 }}><Field label="Date (YYYY-MM-DD)" value={date} onChangeText={setDate} /></View>
          <View style={{ flex: 1, marginRight: 8 }}><Field label="First gun" value={time} onChangeText={setTime} /></View>
          <View style={{ flex: 1 }}><Field label="Window (h)" value={win} onChangeText={setWin} keyboardType="decimal-pad" /></View>
        </View>
        <T muted size={13} style={{ marginTop: 10 }}>Fleets</T>
        <View style={[styles.row, { flexWrap: "wrap" }]}>
          {cv.fleets.map((f) => <Chip key={f.cls} label={f.name} active={fleets.includes(f.cls)}
            onPress={() => setFleets(fleets.includes(f.cls) ? fleets.filter((x) => x !== f.cls) : [...fleets, f.cls])} />)}
        </View>
        {err && <T style={{ color: c.off, marginTop: 8 }}>{err}</T>}
        <Button title="Add start" disabled={!fleets.length} onPress={add} />
      </Card>
    </>
  );
}

function Limits({ cv, onChange }: { cv: ClubView; onChange: () => void }) {
  return (
    <>
      <Card><T muted size={14}>The race call uses these limits. Set your own for juniors or a sheltered course; blank keeps the class default.</T></Card>
      {cv.fleets.map((f) => <LimitRow key={f.cls} slug={cv.slug} f={f} onChange={onChange} />)}
    </>
  );
}

function LimitRow({ slug, f, onChange }: { slug: string; f: ClubView["fleets"][0]; onChange: () => void }) {
  const [label, setLabel] = useState(f.club_limit ? f.name : ""); const [min, setMin] = useState(String(f.min_kn)); const [gust, setGust] = useState(String(f.max_gust_kn));
  const [ok, setOk] = useState(false);
  const save = async () => {
    await api(`/clubs/${slug}/fleets/${f.cls}`, { method: "PUT", body: { label: label || null, min_kn: Number(min), max_gust_kn: Number(gust) } });
    setOk(true); onChange();
  };
  return (
    <Card>
      <H>{f.name}{f.club_limit ? " · club limits" : ""}</H>
      <View style={styles.row}>
        <View style={{ flex: 2, marginRight: 8 }}><Field label="Fleet name (optional)" value={label} onChangeText={(v) => { setLabel(v); setOk(false); }} placeholder="e.g. Juniors" /></View>
        <View style={{ flex: 1, marginRight: 8 }}><Field label="Min wind" value={min} onChangeText={(v) => { setMin(v); setOk(false); }} keyboardType="decimal-pad" /></View>
        <View style={{ flex: 1 }}><Field label="Max gust" value={gust} onChangeText={(v) => { setGust(v); setOk(false); }} keyboardType="decimal-pad" /></View>
      </View>
      <Button kind="ghost" title={ok ? "Saved" : "Save"} disabled={ok} onPress={save} />
    </Card>
  );
}

function Regattas({ cv, onChange }: { cv: ClubView; onChange: () => void }) {
  const c = useColors();
  const [name, setName] = useState(""); const [first, setFirst] = useState(""); const [last, setLast] = useState("");
  const [classes, setClasses] = useState<string[]>([]); const [entries, setEntries] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  if (cv.tier !== "pro") return <Message text="Regatta pages come with Club Pro: four a year, with race calls, tide times, notices and a QR code for the noticeboard." />;
  const add = async () => {
    setMsg(null);
    try {
      const r = await api<{ url: string }>(`/clubs/${cv.slug}/events`, { body: { name, first_day: first, last_day: last || first, classes, entries: entries ? Number(entries) : null } });
      setMsg(`Published at ${r.url}`); setName(""); onChange();
    } catch (e: any) { setMsg(e.message); }
  };
  return (
    <Card>
      <H>New regatta page</H>
      <Field label="Name" value={name} onChangeText={setName} placeholder="e.g. Spring Open" />
      <View style={styles.row}>
        <View style={{ flex: 1, marginRight: 8 }}><Field label="First day" value={first} onChangeText={setFirst} placeholder="YYYY-MM-DD" /></View>
        <View style={{ flex: 1, marginRight: 8 }}><Field label="Last day" value={last} onChangeText={setLast} placeholder="YYYY-MM-DD" /></View>
        <View style={{ flex: 1 }}><Field label="Entries" value={entries} onChangeText={setEntries} keyboardType="number-pad" /></View>
      </View>
      <T muted size={13} style={{ marginTop: 10 }}>Classes</T>
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {cv.fleets.map((f) => <Chip key={f.cls} label={f.name} active={classes.includes(f.cls)}
          onPress={() => setClasses(classes.includes(f.cls) ? classes.filter((x) => x !== f.cls) : [...classes, f.cls])} />)}
      </View>
      <Button title="Publish" disabled={!name || !first || !classes.length} onPress={add} />
      {msg && <T style={{ marginTop: 8, color: msg.startsWith("Published") ? c.on : c.off }}>{msg}</T>}
    </Card>
  );
}

function People({ slug }: { slug: string }) {
  const c = useColors();
  const [email, setEmail] = useState(""); const [msg, setMsg] = useState<string | null>(null);
  const set = async (role: string) => {
    setMsg(null);
    try { const r = await api<{ email: string; role: string }>(`/clubs/${slug}/roles`, { method: "PUT", body: { email, role } }); setMsg(`${r.email} is now ${r.role}.`); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <Card>
      <H>Officers and coaches</H>
      <T muted size={14}>They need a bluepuff account first. Coaches get Racer Pro (five seats on Club Pro).</T>
      <Field label="Their email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />
      <View style={[styles.row, { flexWrap: "wrap" }]}>
        {["officer", "coach", "admin", "member"].map((r) => <Chip key={r} label={`Make ${r}`} onPress={() => set(r)} />)}
      </View>
      {msg && <T style={{ marginTop: 8, color: msg.includes(" is now ") ? c.on : c.off }}>{msg}</T>}
    </Card>
  );
}
