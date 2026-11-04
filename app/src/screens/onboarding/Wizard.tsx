import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ArrowRight, Check, ChevronLeft, LogOut, PartyPopper } from "lucide-react";
import { useSession } from "../../lib/session";
import { toEngineError } from "../../lib/engine";
import { ONBOARDING_STEPS, type OnboardingStep, type Profile, type Settings } from "../../lib/types";
import { Button, Skeleton } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { cn } from "../../lib/util";
import {
  diffSettings,
  EmailForm,
  FundingForm,
  InterestsForm,
  LimitsForm,
  LlmForm,
  ProfileForm,
  ResumeDrop,
  TargetsForm,
} from "../../components/forms";

const META: Record<OnboardingStep, { title: string; subtitle: string; short: string; skippable?: boolean }> = {
  resume: { short: "Resume", title: "Start with your resume", subtitle: "We read it once to learn what you've actually done, so emails can be specific and honest.", skippable: true },
  profile: { short: "Profile", title: "Does this look right?", subtitle: "Fix anything we got wrong. Drafts only ever use what's here." },
  interests: { short: "Interests", title: "What do you want to work on?", subtitle: "Pick a few fields. We'll match professors whose recent papers fit." },
  targets: { short: "Targets", title: "Where would you like to go?", subtitle: "Choose countries or whole regions. You can change this any time." },
  email: { short: "Email", title: "Connect your email", subtitle: "Emails go out from your own address, and replies come back to you.", skippable: true },
  llm: { short: "AI model", title: "Choose a writing model", subtitle: "Used to draft emails and summarise replies. Groq's free tier is plenty.", skippable: true },
  funding: { short: "Funding", title: "Can you fund yourself?", subtitle: "This only matters when a professor asks. Honesty here saves everyone time." },
  limits: { short: "Pacing", title: "How fast should we send?", subtitle: "Slow and steady keeps you out of spam folders and looks human." },
};

export function OnboardingWizard() {
  const { engine, onboarding, setOnboarding, user, signOut } = useSession();
  const toast = useToast();
  const firstTodo = ONBOARDING_STEPS.findIndex((s) => !onboarding.completed.includes(s));
  const [idx, setIdx] = useState(firstTodo === -1 ? ONBOARDING_STEPS.length - 1 : firstTodo);
  const [finished, setFinished] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [orig, setOrig] = useState<Settings>({});
  const [s, setS] = useState<Settings>({});
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void Promise.all([engine.call("profile.get"), engine.call("settings.get")])
      .then(([p, st]) => {
        setProfile(p.profile);
        setOrig(st.settings);
        setS(st.settings);
      })
      .catch((e) => toast.error("Couldn't load your settings", toEngineError(e).message))
      .finally(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine]);

  const step = ONBOARDING_STEPS[idx];
  const meta = META[step];
  const set = useCallback((patch: Settings) => setS((x) => ({ ...x, ...patch })), []);

  const saveSettings = useCallback(async () => {
    const values = diffSettings(orig, s);
    if (!Object.keys(values).length) return true;
    try {
      const r = await engine.call("settings.update", { values });
      setOrig({ ...s, ...r.settings });
      setS((cur) => ({ ...cur, ...r.settings }));
      return true;
    } catch (e) {
      toast.error("Couldn't save", toEngineError(e).message);
      return false;
    }
  }, [engine, orig, s, toast]);

  const saveProfile = async (p: Profile) => {
    try {
      const r = await engine.call("profile.update", { profile: p });
      setProfile(r.profile);
      return true;
    } catch (e) {
      toast.error("Couldn't save profile", toEngineError(e).message);
      return false;
    }
  };

  const canNext = useMemo(() => {
    if (!profile) return false;
    if (step === "profile") return !!profile.name.trim();
    if (step === "interests") return profile.research_interests.length > 0;
    if (step === "targets") return !!(s.DISCOVER_COUNTRIES ?? "").trim();
    if (step === "funding") return !!s.CAN_SELF_FUND;
    return true;
  }, [step, profile, s]);

  const next = async () => {
    if (!profile) return;
    setBusy(true);
    try {
      if (step === "profile" || step === "interests") {
        if (!(await saveProfile(profile))) return;
      }
      if (step !== "resume" && step !== "profile") {
        // the interests step also drives the pipeline's focus filter
        const extra: Settings = step === "interests" ? { FOCUS_KEYWORDS: profile.research_interests.join(";") } : {};
        const merged = { ...s, ...extra };
        const values = diffSettings(orig, merged);
        if (Object.keys(values).length) {
          const r = await engine.call("settings.update", { values });
          setOrig({ ...merged, ...r.settings });
          setS({ ...merged, ...r.settings });
        }
      }
      const ob = await engine.call("onboarding.complete", { step });
      if (idx === ONBOARDING_STEPS.length - 1) {
        // Hold the finish screen; the Gate flips to the main app when the user continues.
        setFinished(true);
      } else {
        setOnboarding({ ...ob, done: false });
        setIdx(idx + 1);
      }
    } catch (e) {
      toast.error("Couldn't save this step", toEngineError(e).message);
    } finally {
      setBusy(false);
    }
  };

  if (finished) {
    return (
      <Shell idx={ONBOARDING_STEPS.length} onSignOut={signOut}>
        <div className="flex flex-col items-center py-10 text-center animate-fade-in">
          <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-sage-soft text-sage">
            <PartyPopper className="h-6 w-6" />
          </div>
          <h1 className="font-serif text-3xl text-cream">You're all set{user?.name && user.provider !== "guest" ? `, ${user.name.split(" ")[0]}` : ""}.</h1>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-slate">
            Next: discover professors, let Agnostos draft emails, and read every one before anything is sent. Nothing goes out without you saying so.
          </p>
          <Button
            variant="primary"
            size="lg"
            className="mt-8"
            icon={<ArrowRight className="h-4 w-4" />}
            onClick={() => {
              setOnboarding({ completed: [...ONBOARDING_STEPS], done: true });
              window.location.hash = "#/dashboard";
            }}
          >
            Go to dashboard
          </Button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell idx={idx} onJump={(i) => i < idx && setIdx(i)} completed={onboarding.completed} onSignOut={signOut}>
      <div key={step} className="animate-fade-in">
        <div className="mb-1 text-xs font-medium uppercase tracking-wider text-rust-hover">
          Step {idx + 1} of {ONBOARDING_STEPS.length}
        </div>
        <h1 className="font-serif text-[30px] leading-tight text-cream">{meta.title}</h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate">{meta.subtitle}</p>
        <div className="mt-8">
          {!loaded || !profile ? (
            <div className="space-y-3">
              <Skeleton className="h-10" />
              <Skeleton className="h-10 w-2/3" />
              <Skeleton className="h-24" />
            </div>
          ) : step === "resume" ? (
            <ResumeDrop profile={profile} onImported={setProfile} />
          ) : step === "profile" ? (
            <ProfileForm profile={profile} onChange={setProfile} />
          ) : step === "interests" ? (
            <InterestsForm value={profile.research_interests} onChange={(v) => setProfile({ ...profile, research_interests: v })} />
          ) : step === "targets" ? (
            <TargetsForm s={s} set={set} />
          ) : step === "email" ? (
            <EmailForm s={s} set={set} save={saveSettings} />
          ) : step === "llm" ? (
            <LlmForm s={s} set={set} save={saveSettings} />
          ) : step === "funding" ? (
            <FundingForm s={s} set={set} />
          ) : (
            <LimitsForm s={s} set={set} />
          )}
        </div>
      </div>
      <div className="mt-10 flex items-center justify-between border-t border-line pt-5">
        <Button variant="ghost" onClick={() => setIdx(Math.max(0, idx - 1))} disabled={idx === 0 || busy} icon={<ChevronLeft className="h-4 w-4" />}>
          Back
        </Button>
        <div className="flex items-center gap-2">
          {meta.skippable && (
            <Button variant="ghost" onClick={() => void next()} disabled={busy} data-testid="skip">
              Skip for now
            </Button>
          )}
          <Button variant="primary" onClick={() => void next()} loading={busy} disabled={!canNext} data-testid="next" icon={idx === ONBOARDING_STEPS.length - 1 ? <Check className="h-4 w-4" /> : undefined}>
            {idx === ONBOARDING_STEPS.length - 1 ? "Finish" : "Continue"}
          </Button>
        </div>
      </div>
    </Shell>
  );
}

function Shell({
  idx,
  children,
  onJump,
  completed = [],
  onSignOut,
}: {
  idx: number;
  children: ReactNode;
  onJump?: (i: number) => void;
  completed?: OnboardingStep[];
  onSignOut: () => Promise<void>;
}) {
  return (
    <div className="flex h-full bg-ink">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-[#131418] px-5 py-6 md:flex">
        <div className="mb-8 flex items-center gap-2.5">
          <img src="/agnostos-icon.png" alt="" className="h-7 w-7 rounded-lg" />
          <span className="font-serif text-lg text-cream">Agnostos</span>
        </div>
        <ol className="space-y-1" aria-label="Setup progress">
          {ONBOARDING_STEPS.map((s, i) => {
            const done = i < idx || completed.includes(s);
            const cur = i === idx;
            return (
              <li key={s}>
                <button
                  disabled={!onJump || i >= idx}
                  onClick={() => onJump?.(i)}
                  aria-current={cur ? "step" : undefined}
                  className={cn(
                    "focus-ring flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                    cur ? "bg-surface-2 text-cream" : done ? "text-cream-dim hover:bg-surface" : "text-slate-dim",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-5 w-5 items-center justify-center rounded-full border text-[10px]",
                      cur ? "border-rust bg-rust text-cream" : done ? "border-sage/60 bg-sage-soft text-sage" : "border-line-strong",
                    )}
                  >
                    {done && !cur ? <Check className="h-3 w-3" /> : i + 1}
                  </span>
                  {META[s].short}
                </button>
              </li>
            );
          })}
        </ol>
        <div className="mt-auto">
          <button onClick={() => void onSignOut()} className="focus-ring flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-slate hover:text-cream">
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="h-1 bg-surface md:hidden">
          <div className="h-full bg-rust transition-all" style={{ width: `${(idx / ONBOARDING_STEPS.length) * 100}%` }} />
        </div>
        <div className="mx-auto max-w-2xl px-8 py-12">{children}</div>
      </main>
    </div>
  );
}
