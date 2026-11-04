import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { FolderOpen, Info, KeyRound, LogOut, Mail, SlidersHorizontal, Target, UserRound, Wallet } from "lucide-react";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import type { Profile, Settings } from "../lib/types";
import { Badge, Button, Card, ConfirmDialog, Field, Input, PageHeader, Skeleton, Toggle } from "../components/ui";
import { useDevMode } from "../lib/dev";
import { useToast } from "../components/Toast";
import { cn } from "../lib/util";
import { diffSettings, EmailForm, FundingForm, LimitsForm, LlmForm, ProfileForm, TargetsForm } from "../components/forms";
import { Avatar } from "../components/Layout";

const TABS = [
  { id: "profile", label: "Profile", icon: UserRound },
  { id: "account", label: "Account", icon: KeyRound },
  { id: "targets", label: "Targets", icon: Target },
  { id: "email", label: "Email", icon: Mail },
  { id: "llm", label: "AI model", icon: SlidersHorizontal },
  { id: "funding", label: "Funding", icon: Wallet },
  { id: "limits", label: "Sending limits", icon: SlidersHorizontal },
  { id: "workspace", label: "Workspace", icon: FolderOpen },
  { id: "about", label: "About", icon: Info },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function SettingsScreen() {
  const { engine, user, info, signOut } = useSession();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("profile");
  const [orig, setOrig] = useState<Settings | null>(null);
  const [s, setS] = useState<Settings>({});
  const [profile, setProfile] = useState<Profile | null>(null);
  const [origProfile, setOrigProfile] = useState<Profile | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmOut, setConfirmOut] = useState(false);
  const [dev, setDev] = useDevMode();

  useEffect(() => {
    void Promise.all([engine.call("settings.get"), engine.call("profile.get")])
      .then(([st, p]) => {
        setOrig(st.settings);
        setS(st.settings);
        setProfile(p.profile);
        setOrigProfile(p.profile);
      })
      .catch((e) => toast.error("Couldn't load settings", toEngineError(e).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine]);

  const set = useCallback((patch: Settings) => setS((x) => ({ ...x, ...patch })), []);
  const dirtySettings = orig ? Object.keys(diffSettings(orig, s)).length > 0 : false;
  const dirtyProfile = profile && origProfile ? JSON.stringify(profile) !== JSON.stringify(origProfile) : false;
  const dirty = dirtySettings || dirtyProfile;

  const save = useCallback(async () => {
    if (!orig) return false;
    setSaving(true);
    try {
      if (dirtyProfile && profile) {
        const r = await engine.call("profile.update", { profile });
        setProfile(r.profile);
        setOrigProfile(r.profile);
      }
      const values = diffSettings(orig, s);
      if (Object.keys(values).length) {
        const r = await engine.call("settings.update", { values });
        const merged = { ...s, ...r.settings };
        setOrig(merged);
        setS(merged);
      }
      return true;
    } catch (e) {
      toast.error("Couldn't save", toEngineError(e).message);
      return false;
    } finally {
      setSaving(false);
    }
  }, [engine, orig, s, profile, dirtyProfile, toast]);

  const loaded = !!orig && !!profile;

  let body: ReactNode;
  if (!loaded) body = <div className="space-y-3"><Skeleton className="h-10" /><Skeleton className="h-10 w-2/3" /><Skeleton className="h-28" /></div>;
  else if (tab === "profile") body = <ProfileForm profile={profile!} onChange={setProfile} />;
  else if (tab === "account")
    body = (
      <div className="space-y-5">
        <div className="flex items-center gap-4">
          <Avatar name={user?.name ?? "?"} url={user?.avatar_url} size={48} />
          <div>
            <div className="text-base text-cream">{user?.name}</div>
            <div className="text-sm text-slate">{user?.email ?? "No email"}</div>
          </div>
          <Badge className="ml-auto capitalize">{user?.provider === "local" ? "Email & password" : user?.provider}</Badge>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-line bg-ink/40 px-4 py-3">
          <div>
            <div className="text-sm text-cream">Gmail</div>
            <div className="text-xs text-slate">{user?.gmail_connected ? "Connected for sending and replies" : "Not connected"}</div>
          </div>
          {user?.gmail_connected ? <Badge tone="sage">Connected</Badge> : <Button size="sm" onClick={() => setTab("email")}>Set up email</Button>}
        </div>
        {user?.provider === "guest" && (
          <p className="rounded-lg border border-amber/30 bg-amber-soft px-3 py-2 text-xs text-amber">
            You're using a guest profile. Your data is kept on this computer, but there's no password protecting it.
          </p>
        )}
        <Button variant="secondary" onClick={() => setConfirmOut(true)} icon={<LogOut className="h-4 w-4" />}>
          Sign out
        </Button>
      </div>
    );
  else if (tab === "targets") body = <TargetsForm s={s} set={set} />;
  else if (tab === "email") body = <EmailForm s={s} set={set} save={save} />;
  else if (tab === "llm") body = <LlmForm s={s} set={set} save={save} />;
  else if (tab === "funding") body = <FundingForm s={s} set={set} />;
  else if (tab === "limits") body = <LimitsForm s={s} set={set} />;
  else if (tab === "workspace")
    body = (
      <div className="space-y-5">
        <Field
          label="Workspace folder"
          htmlFor="ws"
          hint="Where your sheet, drafts and logs live. Point this at an existing Agnostos v2 folder to keep using its data and scheduled tasks."
        >
          <Input id="ws" className="font-mono text-xs" value={s._workspace ?? ""} onChange={(e) => set({ _workspace: e.target.value })} placeholder="C:\\Users\\you\\Agnostos" />
        </Field>
        <Field label="App data" htmlFor="dd">
          <Input id="dd" className="font-mono text-xs" value={info?.data_dir ?? ""} readOnly />
        </Field>
      </div>
    );
  else
    body = (
      <div className="space-y-5">
        <div className="flex items-center gap-4">
          <img src="/agnostos-icon.png" alt="" className="h-14 w-14 rounded-2xl" />
          <div>
            <div className="font-serif text-2xl text-cream">Agnostos</div>
            <div className="text-sm italic text-slate">research outreach, done honestly</div>
          </div>
        </div>
        <dl className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
          <dt className="text-slate">App version</dt>
          <dd className="font-mono text-cream" data-testid="app-version">{info?.version ?? "?"}</dd>
          <dt className="text-slate">Engine version</dt>
          <dd className="font-mono text-cream">{info?.engine_version ?? "?"}</dd>
          <dt className="text-slate">Mode</dt>
          <dd className="text-cream">{engine.isMock ? "Browser demo (mock engine)" : "Desktop"}</dd>
        </dl>
        <p className="text-xs leading-relaxed text-slate">
          Agnostos never invents achievements, never sends without your say-so, and keeps every credential on this computer.
        </p>
        <Toggle id="dev-mode" checked={dev} onChange={setDev} label="Developer mode" description="Show raw engine logs on the Activity page (for testing and troubleshooting)." />
      </div>
    );

  const showSave = loaded && !["account", "about"].includes(tab);

  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6 md:grid-cols-[200px_1fr]">
        <nav aria-label="Settings sections" className="space-y-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
              className={cn(
                "focus-ring flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                tab === t.id ? "bg-surface-2 text-cream" : "text-slate hover:bg-surface hover:text-cream",
              )}
            >
              <t.icon className="h-4 w-4" />
              {t.label}
            </button>
          ))}
        </nav>
        <Card className="p-6">
          <div key={tab} className="animate-fade-in">{body}</div>
          {showSave && (
            <div className="mt-8 flex items-center justify-end gap-3 border-t border-line pt-4">
              {dirty && <span className="text-xs text-amber">Unsaved changes</span>}
              <Button
                variant="ghost"
                disabled={!dirty || saving}
                onClick={() => {
                  if (orig) setS(orig);
                  if (origProfile) setProfile(origProfile);
                }}
              >
                Discard
              </Button>
              <Button variant="primary" disabled={!dirty} loading={saving} onClick={() => void save().then((ok) => ok && toast.success("Settings saved"))}>
                Save changes
              </Button>
            </div>
          )}
        </Card>
      </div>
      <ConfirmDialog open={confirmOut} title="Sign out?" confirmLabel="Sign out" onCancel={() => setConfirmOut(false)} onConfirm={() => void signOut()}>
        Your data stays on this computer. Sign back in any time to pick up where you left off.
      </ConfirmDialog>
    </>
  );
}
