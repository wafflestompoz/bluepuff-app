import React from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View, ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { CALLS, useColors } from "../lib/theme";
import { useSession } from "../lib/session";

export function Screen({ title, sub, children, refreshing, onRefresh }: {
  title: string; sub?: string; children: React.ReactNode; refreshing?: boolean; onRefresh?: () => void;
}) {
  const c = useColors();
  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40, maxWidth: 760, width: "100%", alignSelf: "center" }}
        refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined}>
        <Text style={{ color: c.fg, fontSize: 28, fontWeight: "700" }}>{title}</Text>
        {sub ? <Text style={{ color: c.muted, marginTop: 2, marginBottom: 8 }}>{sub}</Text> : <View style={{ height: 8 }} />}
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const c = useColors();
  return <View style={[{ backgroundColor: c.card, borderColor: c.line, borderWidth: 1, borderRadius: 14, padding: 16, marginTop: 12 }, style]}>{children}</View>;
}

export function H({ children }: { children: React.ReactNode }) {
  const c = useColors();
  return <Text style={{ color: c.fg, fontSize: 17, fontWeight: "700", marginBottom: 6 }}>{children}</Text>;
}

export function T({ children, muted, size, bold, style }: { children: React.ReactNode; muted?: boolean; size?: number; bold?: boolean; style?: any }) {
  const c = useColors();
  return <Text style={[{ color: muted ? c.muted : c.fg, fontSize: size ?? 15, fontWeight: bold ? "700" : "400", lineHeight: (size ?? 15) * 1.4 }, style]}>{children}</Text>;
}

export function CallPill({ call, big }: { call: string; big?: boolean }) {
  const c = useColors(); const k = CALLS[call] ?? CALLS.marginal;
  return (
    <View style={{ backgroundColor: c[k.key], borderRadius: 999, paddingHorizontal: big ? 14 : 9, paddingVertical: big ? 6 : 3, alignSelf: "flex-start" }}>
      <Text style={{ color: "#fff", fontWeight: "800", fontSize: big ? 16 : 12 }}>{k.word.toUpperCase()}</Text>
    </View>
  );
}

export function Button({ title, onPress, kind = "primary", disabled, busy }: {
  title: string; onPress: () => void; kind?: "primary" | "ghost" | "danger" | "light"; disabled?: boolean; busy?: boolean;
}) {
  const c = useColors();
  const bg = kind === "primary" ? c.blue : "transparent";
  const fg = kind === "primary" || kind === "light" ? "#fff" : kind === "danger" ? c.off : c.blue;
  return (
    <Pressable onPress={onPress} disabled={disabled || busy} accessibilityRole="button"
      style={({ pressed }) => ({ backgroundColor: bg, borderColor: kind === "primary" ? bg : kind === "light" ? "rgba(255,255,255,0.6)" : c.line, borderWidth: 1, borderRadius: 10,
        paddingVertical: 12, paddingHorizontal: 16, alignItems: "center", opacity: disabled ? 0.5 : pressed ? 0.8 : 1, marginTop: 10 })}>
      {busy ? <ActivityIndicator color={fg} /> : <Text style={{ color: fg, fontWeight: "700", fontSize: 15 }}>{title}</Text>}
    </Pressable>
  );
}

export function Field(props: React.ComponentProps<typeof TextInput> & { label: string }) {
  const c = useColors();
  return (
    <View style={{ marginTop: 10 }}>
      <Text style={{ color: c.muted, fontSize: 13, marginBottom: 4 }}>{props.label}</Text>
      <TextInput placeholderTextColor={c.muted} {...props}
        style={[{ borderColor: c.line, borderWidth: 1, borderRadius: 10, padding: 12, color: c.fg, backgroundColor: c.card, fontSize: 16 }, props.style]} />
    </View>
  );
}

export function Chip({ label, active, onPress }: { label: string; active?: boolean; onPress: () => void }) {
  const c = useColors();
  return (
    <Pressable onPress={onPress} style={{ borderRadius: 999, borderWidth: 1, borderColor: active ? c.blue : c.line,
      backgroundColor: active ? c.blue : c.card, paddingHorizontal: 12, paddingVertical: 6, marginRight: 8, marginTop: 8 }}>
      <Text style={{ color: active ? "#fff" : c.fg, fontWeight: "600" }}>{label}</Text>
    </Pressable>
  );
}

/** Followed clubs as chips; picks which club the tab shows. */
export function ClubSwitcher() {
  const { me, club, setClubSlug } = useSession();
  if (!me || me.clubs.length < 2) return null;
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
      {me.clubs.map((k) => <Chip key={k.slug} label={k.name} active={club?.slug === k.slug} onPress={() => setClubSlug(k.slug)} />)}
    </View>
  );
}

export function Message({ text, action }: { text: string; action?: React.ReactNode }) {
  return <Card><T muted>{text}</T>{action}</Card>;
}

export function Upsell({ what }: { what: string }) {
  const c = useColors();
  return (
    <View style={{ backgroundColor: c.tint, borderRadius: 12, padding: 12, marginTop: 12 }}>
      <T size={14}><T bold size={14}>Racer</T> adds {what}. Free if your club has a bluepuff licence: join with its club code.</T>
    </View>
  );
}

export const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center" },
  between: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
});
