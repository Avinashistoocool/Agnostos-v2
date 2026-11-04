import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { engine as defaultEngine, toEngineError, type EngineClient, type EngineError } from "./engine";
import type { AppInfo, Onboarding, User } from "./types";

type Session = {
  engine: EngineClient;
  info: AppInfo | null;
  status: "loading" | "ready" | "error";
  error: EngineError | null;
  user: User | null;
  onboarding: Onboarding;
  signIn: (u: User) => Promise<void>;
  setOnboarding: (o: Onboarding) => void;
  refresh: () => Promise<void>;
  restart: () => Promise<void>;
  signOut: () => Promise<void>;
};

const SessionCtx = createContext<Session | null>(null);

export function useSession() {
  const s = useContext(SessionCtx);
  if (!s) throw new Error("useSession outside provider");
  return s;
}

export function useEngine() {
  return useSession().engine;
}

export function SessionProvider({ children, engine = defaultEngine }: { children: ReactNode; engine?: EngineClient }) {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [status, setStatus] = useState<Session["status"]>("loading");
  const [error, setError] = useState<EngineError | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [onboarding, setOnboarding] = useState<Onboarding>({ completed: [], done: false });

  const refresh = useCallback(async () => {
    setStatus("loading");
    try {
      const i = await engine.call("app.info");
      setInfo(i);
      setUser(i.user);
      setOnboarding(i.onboarding);
      setError(null);
      setStatus("ready");
    } catch (e) {
      setError(toEngineError(e));
      setStatus("error");
    }
  }, [engine]);

  const restart = useCallback(async () => {
    setStatus("loading");
    try {
      await engine.restart();
    } catch {
      /* fall through to app.info which reports the real state */
    }
    await refresh();
  }, [engine, refresh]);

  const signOut = useCallback(async () => {
    try {
      await engine.call("auth.logout");
    } finally {
      setUser(null);
      setOnboarding({ completed: [], done: false });
    }
  }, [engine]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (u: User) => {
      try {
        setOnboarding(await engine.call("onboarding.get"));
      } catch {
        /* keep previous */
      }
      setUser(u);
    },
    [engine],
  );
  return (
    <SessionCtx.Provider
      value={{ engine, info, status, error, user, onboarding, signIn, setOnboarding, refresh, restart, signOut }}
    >
      {children}
    </SessionCtx.Provider>
  );
}
