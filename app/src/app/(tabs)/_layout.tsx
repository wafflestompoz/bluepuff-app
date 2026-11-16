import React from "react";
import { ColorValue, Text } from "react-native";
import { Tabs } from "expo-router";
import { useSession } from "../../lib/session";
import { useColors } from "../../lib/theme";

const icon = (glyph: string) => ({ color }: { color: ColorValue }) => <Text style={{ color, fontSize: 18 }}>{glyph}</Text>;

export default function TabsLayout() {
  const c = useColors(); const { me } = useSession();
  const officer = !!me?.clubs.some((k) => k.role === "officer" || k.role === "admin");
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: c.blue, tabBarInactiveTintColor: c.muted,
      tabBarStyle: { backgroundColor: c.card, borderTopColor: c.line } }}>
      <Tabs.Screen name="index" options={{ title: "Race", tabBarIcon: icon("⛵") }} />
      <Tabs.Screen name="water" options={{ title: "Water", tabBarIcon: icon("≈") }} />
      <Tabs.Screen name="regatta" options={{ title: "Regatta", tabBarIcon: icon("⚑") }} />
      <Tabs.Screen name="club" options={{ title: "Club", tabBarIcon: icon("☰") }} />
      <Tabs.Screen name="office" options={{ title: "Race office", tabBarIcon: icon("⏱"), href: officer ? undefined : null }} />
    </Tabs>
  );
}
