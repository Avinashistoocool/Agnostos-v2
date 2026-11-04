import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Check, Copy, ExternalLink, Mail, UserRound } from "lucide-react";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import type { GithubStart } from "../lib/types";
import { Button, Checkbox, Field, Input, Modal, Spinner, Tooltip } from "../components/ui";
import { useToast } from "../components/Toast";
import { cn } from "../lib/util";

export function GoogleMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.24 1.4-1.7 4.1-5.5 4.1-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.5 14.6 2.5 12 2.5 6.8 2.5 2.6 6.7 2.6 12s4.2 9.5 9.4 9.5c5.4 0 9-3.8 9-9.2 0-.6-.07-1.1-.16-1.6H12z" />
    </svg>
  );
}

export function GithubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden fill="currentColor">
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.42c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.75.11 3.04.74.8 1.19 1.83 1.19 3.08 0 4.41-2.69 5.38-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z" />
    </svg>
  );
}

function ProviderButton({
  icon,
  children,
  onClick,
  loading,
  unavailable,
  testId,
}: {
  icon: ReactNode;
  children: ReactNode;
  onClick: () => void;
  loading?: boolean;
  unavailable?: string | null;
  testId?: string;
}) {
  const btn = (
    <Button
      size="lg"
      variant="secondary"
      className="w-full justify-start"
      icon={icon}
      onClick={onClick}
      loading={loading}
      disabled={!!unavailable}
      data-testid={testId}
      aria-describedby={unavailable ? `${testId}-why` : undefined}
    >
      <span className="flex-1 text-left">{children}</span>
      {unavailable && <span className="text-[11px] font-normal text-slate">Not set up</span>}
    </Button>
  );
  if (!unavailable) return btn;
  return (
    <Tooltip content={unavailable}>
      <span tabIndex={0} className="focus-ring block w-full rounded-lg">
        {btn}
        <span id={`${testId}-why`} className="sr-only">
          {unavailable}
        </span>
      </span>
    </Tooltip>
  );
}

export function SignIn() {
  const { engine, signIn } = useSession();
  const toast = useToast();
  const [connectGmail, setConnectGmail] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<{ google?: string; github?: string }>({});
  const [tab, setTab] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [gh, setGh] = useState<GithubStart | null>(null);

  useEffect(
    () =>
      engine.on((ev) => {
        if (ev.event === "auth.progress") setProgress(ev.data.detail);
      }),
    [engine],
  );

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setProgress(null);
    try {
      await fn();
    } catch (e) {
      const err = toEngineError(e);
      if (err.code === "unavailable" && (key === "google" || key === "github")) {
        setUnavailable((u) => ({ ...u, [key]: err.message }));
        toast.warning(`${key === "google" ? "Google" : "GitHub"} sign-in isn't set up`, err.message);
      } else if (key === "local") {
        setFormError(err.message);
      } else {
        toast.error("Sign-in failed", err.message);
      }
    } finally {
      setBusy(null);
      setProgress(null);
    }
  };

  const google = () =>
    run("google", async () => {
      const r = await engine.call("auth.google", { connect_gmail: connectGmail });
      await signIn(r.user);
    });

  const github = () =>
    run("github", async () => {
      setGh(await engine.call("auth.github.start"));
    });

  const guest = () =>
    run("guest", async () => {
      const r = await engine.call("auth.guest", {});
      await signIn(r.user);
    });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!form.email || !form.password) return setFormError("Enter your email and password.");
    if (tab === "register" && form.password.length < 8) return setFormError("Use at least 8 characters for your password.");
    void run("local", async () => {
      const r =
        tab === "login"
          ? await engine.call("auth.login", { email: form.email, password: form.password })
          : await engine.call("auth.register", { name: form.name || form.email.split("@")[0], email: form.email, password: form.password });
      await signIn(r.user);
    });
  };

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-auto bg-ink px-6 py-10">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{ background: "radial-gradient(800px 400px at 50% -10%, rgba(181,69,46,0.18), transparent 70%)" }}
      />
      <div className="relative w-full max-w-[440px] animate-fade-in">
        <div className="mb-8 text-center">
          <img src="/agnostos-banner.png" alt="Agnostos" className="mx-auto w-full max-w-[400px] rounded-xl" />
          <p className="mt-4 font-serif text-lg italic text-cream-dim">research outreach, done honestly</p>
        </div>

        <div className="card p-6">
          <div className="space-y-2.5">
            <ProviderButton
              testId="google"
              icon={<GoogleMark className="h-4 w-4" />}
              onClick={google}
              loading={busy === "google"}
              unavailable={unavailable.google}
            >
              Continue with Google
            </ProviderButton>
            <div className={cn("pl-1 pt-0.5", unavailable.google && "opacity-50")}>
              <Checkbox checked={connectGmail} onChange={setConnectGmail}>
                <span className="text-xs">Also connect Gmail for sending &amp; replies</span>
              </Checkbox>
            </div>
            {busy === "google" && (
              <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2 text-xs text-slate">
                <Spinner className="h-3.5 w-3.5" /> {progress ?? "Finish signing in in your browser…"}
              </div>
            )}
            <ProviderButton
              testId="github"
              icon={<GithubMark className="h-4 w-4" />}
              onClick={github}
              loading={busy === "github"}
              unavailable={unavailable.github}
            >
              Continue with GitHub
            </ProviderButton>
          </div>

          <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wider text-slate-dim">
            <div className="h-px flex-1 bg-line" /> or with email <div className="h-px flex-1 bg-line" />
          </div>

          <div role="tablist" className="mb-4 grid grid-cols-2 rounded-lg border border-line bg-ink/60 p-1 text-sm">
            {(["login", "register"] as const).map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                onClick={() => {
                  setTab(t);
                  setFormError(null);
                }}
                className={cn(
                  "focus-ring rounded-md py-1.5 transition-colors",
                  tab === t ? "bg-surface-3 text-cream shadow" : "text-slate hover:text-cream",
                )}
              >
                {t === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-3" noValidate>
            {tab === "register" && (
              <Field label="Name" htmlFor="name">
                <Input id="name" autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
            )}
            <Field label="Email" htmlFor="email">
              <Input id="email" type="email" autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </Field>
            <Field label="Password" htmlFor="password" hint={tab === "register" ? "At least 8 characters. Stored hashed on this computer only." : undefined}>
              <Input
                id="password"
                type="password"
                autoComplete={tab === "login" ? "current-password" : "new-password"}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </Field>
            {formError && (
              <p role="alert" className="rounded-lg border border-rust/30 bg-rust-soft px-3 py-2 text-xs text-[#f0a08b]">
                {formError}
              </p>
            )}
            <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy === "local"} icon={<Mail className="h-4 w-4" />}>
              {tab === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
        </div>

        <div className="mt-5 text-center">
          <Button variant="ghost" onClick={guest} loading={busy === "guest"} icon={<UserRound className="h-4 w-4" />}>
            Continue as guest
          </Button>
          <p className="mt-2 text-xs text-slate-dim">Everything stays on this computer. You can connect accounts later.</p>
        </div>
      </div>

      {gh && (
        <GithubDeviceModal
          start={gh}
          onClose={() => setGh(null)}
          onDone={(u) => {
            setGh(null);
            void signIn(u);
          }}
        />
      )}
    </div>
  );
}

function GithubDeviceModal({
  start,
  onClose,
  onDone,
}: {
  start: GithubStart;
  onClose: () => void;
  onDone: (u: import("../lib/types").User) => void;
}) {
  const { engine } = useSession();
  const [copied, setCopied] = useState(false);
  const [state, setState] = useState<"pending" | "expired" | "denied" | "error">("pending");
  const [msg, setMsg] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let interval = Math.max(1, start.interval) * 1000;
    const deadline = Date.now() + start.expires_in * 1000;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!alive.current) return;
      if (Date.now() > deadline) return setState("expired");
      try {
        const r = await engine.call("auth.github.poll", { device_code: start.device_code });
        if (!alive.current) return;
        if (r.status === "done" && r.user) return onDone(r.user);
        if (r.status === "expired" || r.status === "denied") return setState(r.status);
        if (r.status === "slow_down") interval += 5000;
      } catch (e) {
        setState("error");
        setMsg(toEngineError(e).message);
        return;
      }
      timer = setTimeout(poll, interval);
    };
    timer = setTimeout(poll, interval);
    return () => {
      alive.current = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start.device_code]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(start.user_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard may be blocked; code is selectable anyway */
    }
  };

  return (
    <Modal open onClose={onClose} title="Sign in with GitHub">
      <p className="text-sm text-slate">Open GitHub and enter this one-time code to authorise Agnostos.</p>
      <div className="my-6 flex items-center justify-center gap-3">
        <code data-testid="gh-code" className="select-all rounded-xl border border-line bg-ink px-6 py-4 font-mono text-3xl font-semibold tracking-[0.25em] text-cream">
          {start.user_code}
        </code>
        <Button variant="secondary" onClick={copy} aria-label="Copy code" icon={copied ? <Check className="h-4 w-4 text-sage" /> : <Copy className="h-4 w-4" />}>
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <Button variant="primary" className="w-full" icon={<ExternalLink className="h-4 w-4" />} onClick={() => void engine.openUrl(start.verification_uri)}>
        Open GitHub
      </Button>
      <div className="mt-4 flex items-center justify-center gap-2 text-xs text-slate" aria-live="polite">
        {state === "pending" && (
          <>
            <Spinner className="h-3.5 w-3.5" /> Waiting for you to approve on github.com…
          </>
        )}
        {state === "expired" && "The code expired. Close this and try again."}
        {state === "denied" && "Access was denied on GitHub."}
        {state === "error" && (msg ?? "Something went wrong.")}
      </div>
    </Modal>
  );
}
