import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, loadToken, setToken, Me, ClubLink } from "./api";
import { registerForPush } from "./push";

type Ctx = {
  ready: boolean; me: Me | null; club: ClubLink | null;
  setClubSlug: (slug: string) => void; refresh: () => Promise<void>;
  signIn: (email: string, password: string, signup: boolean) => Promise<void>; signOut: () => Promise<void>;
};
const SessionCtx = createContext<Ctx>(null as any);
export const useSession = () => useContext(SessionCtx);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [slug, setClubSlug] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setMe(await api<Me>("/me")); } catch { setMe(null); await setToken(null); }
  }, []);

  useEffect(() => {
    (async () => { if (await loadToken()) await refresh(); setReady(true); })();
  }, [refresh]);

  useEffect(() => { if (me) registerForPush().catch(() => {}); }, [me?.id]);

  const signIn = async (email: string, password: string, signup: boolean) => {
    const r = await api<{ token: string; user: Me }>(signup ? "/auth/signup" : "/auth/login", { body: { email, password } });
    await setToken(r.token); setMe(r.user);
  };
  const signOut = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    await setToken(null); setMe(null); setClubSlug(null);
  };

  const club = me?.clubs.find((c) => c.slug === slug) ?? me?.clubs.find((c) => c.home) ?? me?.clubs[0] ?? null;
  return (
    <SessionCtx.Provider value={{ ready, me, club, setClubSlug, refresh, signIn, signOut }}>{children}</SessionCtx.Provider>
  );
}
