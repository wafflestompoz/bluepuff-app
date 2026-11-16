import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useSession } from "../lib/session";
import { useColors } from "../lib/theme";
import { Button, Field, T } from "./ui";

export default function SignIn() {
  const { signIn } = useSession(); const c = useColors();
  const [mode, setMode] = useState<"login" | "signup">("signup");
  const [email, setEmail] = useState(""); const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    setBusy(true); setErr(null);
    try { await signIn(email.trim(), pw, mode === "signup"); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.blue }}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "center", padding: 20 }}>
        <View style={{ maxWidth: 420, width: "100%", alignSelf: "center" }}>
          <Text style={{ color: "#fff", fontSize: 40, fontWeight: "800" }}>bluepuff</Text>
          <Text style={{ color: "#CFE0FF", fontSize: 17, marginBottom: 20 }}>Know the breeze before the gun.</Text>
          <View style={{ backgroundColor: c.card, borderRadius: 16, padding: 16 }}>
            <T bold size={18}>{mode === "signup" ? "Create your account" : "Sign in"}</T>
            <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoComplete="email" />
            <Field label={mode === "signup" ? "Password (8 characters or more)" : "Password"} value={pw} onChangeText={setPw} secureTextEntry
              autoComplete={mode === "signup" ? "new-password" : "current-password"} onSubmitEditing={go} />
            {err && <T style={{ color: c.off, marginTop: 10 }}>{err}</T>}
            <Button title={mode === "signup" ? "Create account" : "Sign in"} onPress={go} busy={busy} disabled={!email || pw.length < 8} />
            <Button kind="ghost" title={mode === "signup" ? "I already have an account" : "New here? Create an account"}
              onPress={() => setMode(mode === "signup" ? "login" : "signup")} />
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
