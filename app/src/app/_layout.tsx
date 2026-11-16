import React from "react";
import { ActivityIndicator, View } from "react-native";
import { Slot } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { SessionProvider, useSession } from "../lib/session";
import { useColors } from "../lib/theme";
import SignIn from "../components/SignIn";

function Gate() {
  const { ready, me } = useSession(); const c = useColors();
  if (!ready) return <View style={{ flex: 1, backgroundColor: c.bg, justifyContent: "center" }}><ActivityIndicator color={c.blue} /></View>;
  return me ? <Slot /> : <SignIn />;
}

export default function Root() {
  return (
    <SafeAreaProvider>
      <SessionProvider><StatusBar style="auto" /><Gate /></SessionProvider>
    </SafeAreaProvider>
  );
}
