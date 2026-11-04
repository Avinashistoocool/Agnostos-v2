import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CircleCheck, CircleX, ExternalLink, FileText, FolderOpen, Plus, Trash2, Upload } from "lucide-react";
import { useSession } from "../lib/session";
import { toEngineError } from "../lib/engine";
import type { Profile, Settings } from "../lib/types";
import { Button, Chip, ChipInput, Field, Input, Select, Spinner, Textarea, Toggle } from "./ui";
import { useToast } from "./Toast";
import { cn, parseWindow } from "../lib/util";
import { GoogleMark } from "../screens/SignIn";

export type SetS = (patch: Settings) => void;

/* ------------------------------------------------------------------ resume */

export function ResumeDrop({ profile, onImported }: { profile: Profile; onImported: (p: Profile) => void }) {
  const { engine } = useSession();
  const toast = useToast();
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const importPath = async (path: string) => {
    setBusy(true);
    try {
      const r = await engine.call("resume.import", { path });
      onImported(r.profile);
      toast.success("Resume imported", "Check the details on the next step.");
    } catch (e) {
      toast.error("Couldn't read that resume", toEngineError(e).message);
    } finally {
      setBusy(false);
    }
  };

  const browse = async () => {
    if (engine.isMock) {
      fileInput.current?.click();
      return;
    }
    const p = await engine.pickResume();
    if (p) await importPath(p);
  };

  const importRef = useRef(importPath);
  importRef.current = importPath;
  useEffect(
    () =>
      engine.onFileDrop((e) => {
        if (e.type === "enter" || e.type === "over") setOver(true);
        else if (e.type === "leave") setOver(false);
        else {
          setOver(false);
          const p = e.paths?.find((x) => /\.(pdf|docx)$/i.test(x));
          if (p) void importRef.current(p);
          else if (e.paths?.length) toast.warning("Use a PDF or DOCX file");
        }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [engine],
  );

  return (
    <div>
      <div
        data-testid="resume-drop"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const f = e.dataTransfer.files[0] as (File & { path?: string }) | undefined;
          if (!f) return;
          if (!/\.(pdf|docx)$/i.test(f.name)) return toast.warning("Use a PDF or DOCX file");
          // In Tauri the native onFileDrop handler above delivers real paths; the HTML drop only matters in the browser.
          if (!engine.isMock) return;
          void importPath(f.path ?? f.name);
        }}
        className={cn(
          "flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          over ? "border-rust bg-rust-soft" : "border-line-strong bg-ink/40 hover:border-slate-dim",
        )}
      >
        {busy ? (
          <>
            <Spinner className="h-7 w-7" />
            <p className="mt-4 text-sm text-cream">Reading your resume…</p>
            <p className="mt-1 text-xs text-slate">This takes a few seconds.</p>
          </>
        ) : (
          <>
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2 text-slate">
              <Upload className="h-5 w-5" />
            </div>
            <p className="mt-4 text-sm text-cream">Drop your resume here</p>
            <p className="mt-1 text-xs text-slate">PDF or DOCX · stays on this computer</p>
            <Button variant="primary" className="mt-5" onClick={() => void browse()} icon={<FolderOpen className="h-4 w-4" />}>
              Choose file…
            </Button>
          </>
        )}
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          data-testid="resume-input"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void importPath(f.name);
            e.target.value = "";
          }}
        />
      </div>
      {profile.resume_file && !busy && (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-sage/30 bg-sage-soft px-4 py-3 text-sm">
          <FileText className="h-4 w-4 text-sage" />
          <span className="flex-1 text-cream">{profile.resume_file}</span>
          <span className="text-xs text-sage">Imported</span>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- profile */

export function ProfileForm({ profile, onChange }: { profile: Profile; onChange: (p: Profile) => void }) {
  const set = (k: keyof Profile, v: unknown) => onChange({ ...profile, [k]: v });
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name" htmlFor="pf-name">
          <Input id="pf-name" value={profile.name} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="Email" htmlFor="pf-email">
          <Input id="pf-email" type="email" value={profile.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label="Degree / year" htmlFor="pf-degree">
          <Input id="pf-degree" placeholder="B.Sc. Physics, 2nd year" value={profile.degree} onChange={(e) => set("degree", e.target.value)} />
        </Field>
        <Field label="Institution" htmlFor="pf-inst">
          <Input id="pf-inst" value={profile.institution} onChange={(e) => set("institution", e.target.value)} />
        </Field>
      </div>
      <Field label="Research interests">
        <ChipInput label="Add research interest" value={profile.research_interests} onChange={(v) => set("research_interests", v)} placeholder="Type and press Enter" />
      </Field>
      <Field label="Skills">
        <ChipInput label="Add skill" value={profile.skills} onChange={(v) => set("skills", v)} placeholder="Python, C++, ROOT…" />
      </Field>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="label mb-0">Projects</span>
          <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => set("projects", [...profile.projects, { title: "", summary: "" }])}>
            Add project
          </Button>
        </div>
        {profile.projects.length === 0 && <p className="rounded-lg border border-dashed border-line px-4 py-5 text-center text-xs text-slate">No projects yet. Concrete projects make emails far more convincing.</p>}
        <div className="space-y-3">
          {profile.projects.map((pr, i) => (
            <div key={i} className="rounded-xl border border-line bg-ink/40 p-3">
              <div className="flex gap-2">
                <Input
                  aria-label={`Project ${i + 1} title`}
                  placeholder="Title"
                  value={pr.title}
                  onChange={(e) => set("projects", profile.projects.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
                />
                <Button
                  variant="ghost"
                  aria-label={`Remove project ${i + 1}`}
                  onClick={() => set("projects", profile.projects.filter((_, j) => j !== i))}
                  icon={<Trash2 className="h-4 w-4" />}
                />
              </div>
              <Textarea
                aria-label={`Project ${i + 1} summary`}
                className="mt-2 min-h-[64px]"
                placeholder="One or two sentences: what you built and what you learned."
                value={pr.summary}
                onChange={(e) => set("projects", profile.projects.map((x, j) => (j === i ? { ...x, summary: e.target.value } : x)))}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- interests */

export const INTEREST_SUGGESTIONS = [
  "particle physics",
  "HEP / CERN",
  "machine learning",
  "robotics",
  "mathematics",
  "mechanical engineering",
  "astrophysics",
  "quantum computing",
  "condensed matter",
  "computational biology",
  "control systems",
  "climate science",
];

export function InterestsForm({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div>
      <ChipInput label="Add field" value={value} onChange={onChange} suggestions={INTEREST_SUGGESTIONS} placeholder="e.g. neutrino physics, then Enter" />
      <p className="mt-4 text-xs text-slate">Specific beats broad: "jet tagging with GNNs" finds better matches than "physics".</p>
    </div>
  );
}

/* ----------------------------------------------------------------- targets */

const COUNTRIES: [string, string, string][] = [
  ["de", "Germany", "Europe"],
  ["ch", "Switzerland", "Europe"],
  ["fr", "France", "Europe"],
  ["it", "Italy", "Europe"],
  ["nl", "Netherlands", "Europe"],
  ["be", "Belgium", "Europe"],
  ["at", "Austria", "Europe"],
  ["se", "Sweden", "Europe"],
  ["dk", "Denmark", "Europe"],
  ["fi", "Finland", "Europe"],
  ["no", "Norway", "Europe"],
  ["es", "Spain", "Europe"],
  ["pt", "Portugal", "Europe"],
  ["pl", "Poland", "Europe"],
  ["cz", "Czechia", "Europe"],
  ["ie", "Ireland", "Europe"],
  ["gb", "United Kingdom", "UK"],
  ["us", "United States", "USA"],
  ["ca", "Canada", "North America"],
  ["jp", "Japan", "Asia-Pacific"],
  ["sg", "Singapore", "Asia-Pacific"],
  ["kr", "South Korea", "Asia-Pacific"],
  ["au", "Australia", "Asia-Pacific"],
  ["il", "Israel", "Middle East"],
];
const REGIONS = ["Europe", "UK", "USA", "North America", "Asia-Pacific", "Middle East"];
const EUROPE_ALIAS = new Set(["europe", "eu"]);

export function parseCountries(v: string | undefined): string[] {
  const out = new Set<string>();
  for (const raw of (v ?? "").split(/[,;\s]+/)) {
    const t = raw.trim().toLowerCase();
    if (!t) continue;
    if (EUROPE_ALIAS.has(t)) COUNTRIES.filter((c) => c[2] === "Europe" || c[0] === "gb").forEach((c) => out.add(c[0]));
    else out.add(t);
  }
  return [...out];
}

export function TargetsForm({ s, set }: { s: Settings; set: SetS }) {
  const sel = parseCountries(s.DISCOVER_COUNTRIES);
  const update = (codes: string[]) => {
    const names = COUNTRIES.filter((c) => codes.includes(c[0])).map((c) => c[1]);
    set({ DISCOVER_COUNTRIES: codes.join(","), GEOGRAPHY: names.length > 6 ? describeRegions(codes) : names.join(", ") });
  };
  const toggle = (code: string) => update(sel.includes(code) ? sel.filter((c) => c !== code) : [...sel, code]);
  const regionCodes = (r: string) => COUNTRIES.filter((c) => c[2] === r).map((c) => c[0]);
  const regionOn = (r: string) => regionCodes(r).every((c) => sel.includes(c));
  const toggleRegion = (r: string) => {
    const codes = regionCodes(r);
    update(regionOn(r) ? sel.filter((c) => !codes.includes(c)) : [...new Set([...sel, ...codes])]);
  };
  const unis = (s.TARGET_UNIVERSITIES ?? "").split(";").map((x) => x.trim()).filter(Boolean);
  return (
    <div className="space-y-6">
      <div>
        <span className="label">Regions</span>
        <div className="flex flex-wrap gap-2">
          {REGIONS.map((r) => (
            <Chip key={r} active={regionOn(r)} onClick={() => toggleRegion(r)}>
              {r}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <span className="label">Countries {sel.length > 0 && <span className="normal-case text-slate-dim">· {sel.length} selected</span>}</span>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {COUNTRIES.map(([code, name]) => {
            const on = sel.includes(code);
            return (
              <button
                key={code}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(code)}
                className={cn(
                  "focus-ring flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                  on ? "border-rust/50 bg-rust-soft text-cream" : "border-line bg-ink/40 text-cream-dim hover:border-line-strong",
                )}
              >
                <span className="font-mono text-[10px] uppercase text-slate">{code}</span>
                {name}
              </button>
            );
          })}
        </div>
      </div>
      <Field label="Specific universities (optional)" hint="Agnostos will favour these when discovering professors.">
        <ChipInput label="Add university" value={unis} onChange={(v) => set({ TARGET_UNIVERSITIES: v.join("; ") })} placeholder="ETH Zürich, then Enter" />
      </Field>
      <Field label="Position you're asking for" htmlFor="position">
        <Input id="position" value={s.POSITION ?? ""} onChange={(e) => set({ POSITION: e.target.value })} placeholder="summer research internship (undergraduate)" />
      </Field>
    </div>
  );
}

function describeRegions(codes: string[]) {
  const regs = REGIONS.filter((r) => COUNTRIES.filter((c) => c[2] === r).every((c) => codes.includes(c[0])));
  return regs.length ? regs.join(" + ") : codes.join(", ").toUpperCase();
}

/* ------------------------------------------------------------------- email */

const PRESETS: Record<string, Settings> = {
  Gmail: { SMTP_HOST: "smtp.gmail.com", SMTP_PORT: "587", SMTP_SECURITY: "starttls", IMAP_HOST: "imap.gmail.com", IMAP_PORT: "993" },
  Outlook: { SMTP_HOST: "smtp.office365.com", SMTP_PORT: "587", SMTP_SECURITY: "starttls", IMAP_HOST: "outlook.office365.com", IMAP_PORT: "993" },
  University: { SMTP_HOST: "", SMTP_PORT: "587", SMTP_SECURITY: "starttls", IMAP_HOST: "", IMAP_PORT: "993" },
};

export function TestResult({ r }: { r: { ok: boolean; detail: string } | null }) {
  if (!r) return null;
  return (
    <div
      role="status"
      className={cn(
        "mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
        r.ok ? "border-sage/30 bg-sage-soft text-sage" : "border-rust/30 bg-rust-soft text-[#f0a08b]",
      )}
    >
      {r.ok ? <CircleCheck className="mt-px h-3.5 w-3.5 shrink-0" /> : <CircleX className="mt-px h-3.5 w-3.5 shrink-0" />}
      <span>{r.detail}</span>
    </div>
  );
}

export function EmailForm({ s, set, save }: { s: Settings; set: SetS; save: () => Promise<boolean> }) {
  const { engine, user, signIn } = useSession();
  const toast = useToast();
  const [mode, setMode] = useState<"gmail" | "smtp">(user?.gmail_connected ? "gmail" : "smtp");
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; detail: string } | null>>({});
  const [connecting, setConnecting] = useState(false);

  const test = async (kind: "smtp" | "imap") => {
    setTesting(kind);
    try {
      if (!(await save())) return;
      const r = await engine.call("email.test", { kind });
      setResults((x) => ({ ...x, [kind]: r }));
    } catch (e) {
      setResults((x) => ({ ...x, [kind]: { ok: false, detail: toEngineError(e).message } }));
    } finally {
      setTesting(null);
    }
  };

  const connectGmail = async () => {
    setConnecting(true);
    try {
      const r = await engine.call("auth.google", { connect_gmail: true });
      await signIn(r.user);
      toast.success("Gmail connected");
    } catch (e) {
      toast.error("Couldn't connect Gmail", toEngineError(e).message);
    } finally {
      setConnecting(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Email method">
        {(
          [
            ["gmail", "Gmail (recommended)", "One click, no passwords. Uses Google sign-in."],
            ["smtp", "SMTP / IMAP", "Outlook, university mail, or any provider."],
          ] as const
        ).map(([k, t, d]) => (
          <button
            key={k}
            role="radio"
            aria-checked={mode === k}
            onClick={() => setMode(k)}
            className={cn(
              "focus-ring rounded-xl border p-4 text-left transition-colors",
              mode === k ? "border-rust/60 bg-rust-soft" : "border-line bg-ink/40 hover:border-line-strong",
            )}
          >
            <div className="text-sm font-medium text-cream">{t}</div>
            <div className="mt-1 text-xs text-slate">{d}</div>
          </button>
        ))}
      </div>

      {mode === "gmail" ? (
        <div className="rounded-xl border border-line bg-ink/40 p-5">
          {user?.gmail_connected ? (
            <div className="flex items-center gap-3">
              <CircleCheck className="h-5 w-5 text-sage" />
              <div className="flex-1">
                <div className="text-sm text-cream">Gmail connected</div>
                <div className="text-xs text-slate">{user.email}</div>
              </div>
              <Button size="sm" onClick={() => void test("smtp")} loading={testing === "smtp"}>
                Test connection
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex-1 text-sm text-slate">Sign in with Google and grant mail access so Agnostos can send from your address and read replies.</div>
              <Button variant="primary" icon={<GoogleMark className="h-4 w-4" />} onClick={() => void connectGmail()} loading={connecting}>
                Connect Gmail
              </Button>
            </div>
          )}
          <TestResult r={results.smtp ?? null} />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate">Presets:</span>
            {Object.keys(PRESETS).map((p) => (
              <Chip key={p} onClick={() => set(PRESETS[p])} active={!!PRESETS[p].SMTP_HOST && s.SMTP_HOST === PRESETS[p].SMTP_HOST}>
                {p}
              </Chip>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-6">
            <Field label="SMTP host" htmlFor="smtp-host" className="sm:col-span-3">
              <Input id="smtp-host" value={s.SMTP_HOST ?? ""} onChange={(e) => set({ SMTP_HOST: e.target.value })} placeholder="smtp.university.edu" />
            </Field>
            <Field label="Port" htmlFor="smtp-port" className="sm:col-span-1">
              <Input id="smtp-port" inputMode="numeric" value={s.SMTP_PORT ?? ""} onChange={(e) => set({ SMTP_PORT: e.target.value })} />
            </Field>
            <Field label="Security" htmlFor="smtp-sec" className="sm:col-span-2">
              <Select id="smtp-sec" value={s.SMTP_SECURITY || "starttls"} onChange={(e) => set({ SMTP_SECURITY: e.target.value })}>
                <option value="starttls">STARTTLS</option>
                <option value="ssl">SSL/TLS</option>
                <option value="none">None</option>
              </Select>
            </Field>
            <Field label="Username" htmlFor="smtp-user" className="sm:col-span-3">
              <Input
                id="smtp-user"
                autoComplete="off"
                value={s.SMTP_USER ?? ""}
                onChange={(e) => set({ SMTP_USER: e.target.value, IMAP_USER: e.target.value, SMTP_FROM: s.SMTP_FROM || e.target.value })}
              />
            </Field>
            <Field label="Password / app password" htmlFor="smtp-pass" className="sm:col-span-3">
              <SecretInput id="smtp-pass" value={s.SMTP_PASSWORD ?? ""} onChange={(v) => set({ SMTP_PASSWORD: v, IMAP_PASSWORD: v })} />
            </Field>
            <Field label="From name" htmlFor="smtp-fromname" className="sm:col-span-3">
              <Input id="smtp-fromname" value={s.SMTP_FROM_NAME ?? ""} onChange={(e) => set({ SMTP_FROM_NAME: e.target.value })} />
            </Field>
            <Field label="IMAP host (for replies)" htmlFor="imap-host" className="sm:col-span-3">
              <Input id="imap-host" value={s.IMAP_HOST ?? ""} onChange={(e) => set({ IMAP_HOST: e.target.value })} placeholder="imap.university.edu" />
            </Field>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void test("smtp")} loading={testing === "smtp"}>
              Test sending
            </Button>
            <Button onClick={() => void test("imap")} loading={testing === "imap"}>
              Test inbox
            </Button>
          </div>
          <TestResult r={results.smtp ?? null} />
          <TestResult r={results.imap ?? null} />
          <p className="text-xs text-slate">Gmail/Outlook with 2-step verification need an app password, not your normal one.</p>
        </div>
      )}
    </div>
  );
}

export function SecretInput({ id, value, onChange, placeholder }: { id?: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const masked = value.startsWith("••••");
  return (
    <Input
      id={id}
      type="password"
      autoComplete="off"
      value={masked ? "" : value}
      placeholder={masked ? `Saved (${value})` : placeholder}
      onChange={(e) => onChange(e.target.value === "" && masked ? value : e.target.value)}
    />
  );
}

/* --------------------------------------------------------------------- llm */

const LLM: Record<string, { label: string; key: string; url: string; models: string[] }> = {
  groq: { label: "Groq (free tier)", key: "GROQ_API_KEY", url: "https://console.groq.com/keys", models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"] },
  openai: { label: "OpenAI", key: "OPENAI_API_KEY", url: "https://platform.openai.com/api-keys", models: ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"] },
};

export function LlmForm({ s, set, save }: { s: Settings; set: SetS; save: () => Promise<boolean> }) {
  const { engine } = useSession();
  const prov = s.LLM_PROVIDER === "openai" ? "openai" : "groq";
  const meta = LLM[prov];
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [models, setModels] = useState<string[] | null>(null);
  const test = async () => {
    setTesting(true);
    try {
      if (!(await save())) return;
      const r = await engine.call("llm.test");
      setResult(r);
      if (r.models?.length) setModels(r.models);
    } catch (e) {
      setResult({ ok: false, detail: toEngineError(e).message });
    } finally {
      setTesting(false);
    }
  };
  const modelList = models ?? meta.models;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="LLM provider">
        {(Object.keys(LLM) as (keyof typeof LLM)[]).map((k) => (
          <button
            key={k}
            role="radio"
            aria-checked={prov === k}
            onClick={() => {
              set({ LLM_PROVIDER: k, DRAFT_MODEL: "" });
              setModels(null);
              setResult(null);
            }}
            className={cn(
              "focus-ring rounded-xl border p-4 text-left text-sm transition-colors",
              prov === k ? "border-rust/60 bg-rust-soft text-cream" : "border-line bg-ink/40 text-cream-dim hover:border-line-strong",
            )}
          >
            {LLM[k].label}
          </button>
        ))}
      </div>
      <Field
        label="API key"
        htmlFor="llm-key"
        hint={
          <button type="button" className="focus-ring inline-flex items-center gap-1 rounded text-rust-hover hover:underline" onClick={() => void engine.openUrl(meta.url)}>
            Get a {prov === "groq" ? "free Groq" : "OpenAI"} key <ExternalLink className="h-3 w-3" />
          </button>
        }
      >
        <SecretInput id="llm-key" value={s[meta.key] ?? ""} onChange={(v) => set({ [meta.key]: v })} placeholder={prov === "groq" ? "gsk_…" : "sk-…"} />
      </Field>
      <Field label="Model" htmlFor="llm-model" hint="Leave on default unless you know you want something else.">
        <Select id="llm-model" value={s.DRAFT_MODEL ?? ""} onChange={(e) => set({ DRAFT_MODEL: e.target.value })}>
          <option value="">Provider default</option>
          {modelList.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </Select>
      </Field>
      <div>
        <Button onClick={() => void test()} loading={testing}>
          Test
        </Button>
        <TestResult r={result} />
      </div>
      <Field
        label="OpenAlex API key (for finding professors)"
        htmlFor="openalex-key"
        hint={
          <button type="button" className="focus-ring inline-flex items-center gap-1 rounded text-rust-hover hover:underline" onClick={() => void engine.openUrl("https://openalex.org/settings/api")}>
            Free key; without it searches get rate-limited <ExternalLink className="h-3 w-3" />
          </button>
        }
      >
        <SecretInput id="openalex-key" value={s.OPENALEX_API_KEY ?? ""} onChange={(v) => set({ OPENALEX_API_KEY: v })} />
      </Field>
    </div>
  );
}

/* ----------------------------------------------------------------- funding */

export function FundingForm({ s, set }: { s: Settings; set: SetS }) {
  const v = (s.CAN_SELF_FUND ?? "").toLowerCase();
  const val = v === "true" || v === "yes" ? "yes" : v === "false" || v === "no" ? "no" : "";
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-line bg-ink/40 p-4 text-sm leading-relaxed text-slate">
        Many professors like a student but have no budget for an intern. If they ask about money, Agnostos drafts an honest answer based on this.
        It never offers to pay unless you say you can, and it never mentions money in a first email.
      </div>
      <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Can you self-fund">
        {(
          [
            ["yes", "Yes, I can self-fund", "Living costs / travel covered by me or a scholarship."],
            ["no", "No, I need funding", "Only paid or funded positions."],
          ] as const
        ).map(([k, t, d]) => (
          <button
            key={k}
            role="radio"
            aria-checked={val === k}
            onClick={() => set({ CAN_SELF_FUND: k === "yes" ? "true" : "false" })}
            className={cn(
              "focus-ring rounded-xl border p-4 text-left transition-colors",
              val === k ? "border-rust/60 bg-rust-soft" : "border-line bg-ink/40 hover:border-line-strong",
            )}
          >
            <div className="text-sm font-medium text-cream">{t}</div>
            <div className="mt-1 text-xs text-slate">{d}</div>
          </button>
        ))}
      </div>
      <Field label="Note (optional)" htmlFor="fund-note" hint="e.g. 'I have a KVPY scholarship covering travel'. Used verbatim-ish in replies.">
        <Textarea id="fund-note" className="min-h-[80px]" value={s.SELF_FUND_NOTE ?? ""} onChange={(e) => set({ SELF_FUND_NOTE: e.target.value })} />
      </Field>
    </div>
  );
}

/* ------------------------------------------------------------------ limits */

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export function LimitsForm({ s, set }: { s: Settings; set: SetS }) {
  const cap = Number(s.DAILY_SEND_CAP || 25);
  const dmin = Number(s.SEND_DELAY_MIN || 90);
  const dmax = Number(s.SEND_DELAY_MAX || 240);
  const win = parseWindow(s.SEND_LOCAL_WINDOW);
  const days = (s.SEND_WEEKDAYS || "mon,tue,wed,thu,fri").split(",").filter(Boolean);
  return (
    <div className="space-y-7">
      <Row label="Daily send cap" value={`${cap} emails / day`} hint="20–25 a day looks like a real person. More risks spam filters.">
        <input
          type="range"
          aria-label="Daily send cap"
          min={5}
          max={100}
          step={1}
          value={cap}
          onChange={(e) => set({ DAILY_SEND_CAP: e.target.value })}
          className="w-full"
        />
        {cap > 40 && <p className="mt-2 text-xs text-amber">That's a lot for a new address. Consider staying under 40.</p>}
      </Row>
      <Row label="Delay between emails" value={`${fmtSec(dmin)} – ${fmtSec(dmax)}`} hint="A random pause in this range before each email.">
        <div className="grid grid-cols-2 gap-4">
          <label className="text-xs text-slate">
            Minimum
            <input
              type="range"
              aria-label="Minimum delay"
              min={10}
              max={900}
              step={10}
              value={dmin}
              onChange={(e) => {
                const v = Number(e.target.value);
                set({ SEND_DELAY_MIN: String(v), SEND_DELAY_MAX: String(Math.max(v, dmax)) });
              }}
              className="mt-1 w-full"
            />
          </label>
          <label className="text-xs text-slate">
            Maximum
            <input
              type="range"
              aria-label="Maximum delay"
              min={10}
              max={1200}
              step={10}
              value={dmax}
              onChange={(e) => {
                const v = Number(e.target.value);
                set({ SEND_DELAY_MAX: String(v), SEND_DELAY_MIN: String(Math.min(v, dmin)) });
              }}
              className="mt-1 w-full"
            />
          </label>
        </div>
      </Row>
      <Row label="Recipient-local send window" value={win ? `${win[0]}:00 – ${win[1]}:00 their time` : "Any time"} hint="Emails land when the professor is likely at their desk, in their own timezone.">
        <div className="mb-3">
          <Toggle checked={!!win} onChange={(on) => set({ SEND_LOCAL_WINDOW: on ? "9-11" : "" })} label="Only send inside a window" />
        </div>
        {win && (
          <div className="flex items-center gap-3">
            <Select aria-label="Window start" className="w-28" value={win[0]} onChange={(e) => set({ SEND_LOCAL_WINDOW: `${e.target.value}-${Math.max(Number(e.target.value) + 1, win[1])}` })}>
              {Array.from({ length: 23 }, (_, h) => (
                <option key={h} value={h}>
                  {h}:00
                </option>
              ))}
            </Select>
            <span className="text-slate">to</span>
            <Select aria-label="Window end" className="w-28" value={win[1]} onChange={(e) => set({ SEND_LOCAL_WINDOW: `${win[0]}-${e.target.value}` })}>
              {Array.from({ length: 24 }, (_, h) => h + 1)
                .filter((h) => h > win[0])
                .map((h) => (
                  <option key={h} value={h}>
                    {h}:00
                  </option>
                ))}
            </Select>
          </div>
        )}
      </Row>
      <Row label="Send on" value={days.length === 5 && !days.includes("sat") && !days.includes("sun") ? "Weekdays" : `${days.length} days`}>
        <div className="flex flex-wrap gap-1.5">
          {DAYS.map((d) => (
            <Chip
              key={d}
              active={days.includes(d)}
              onClick={() => {
                const next = days.includes(d) ? days.filter((x) => x !== d) : DAYS.filter((x) => x === d || days.includes(x));
                set({ SEND_WEEKDAYS: next.join(",") });
              }}
            >
              {d[0].toUpperCase() + d.slice(1)}
            </Chip>
          ))}
        </div>
      </Row>
    </div>
  );
}

function Row({ label, value, hint, children }: { label: string; value: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <span className="text-sm font-medium text-cream">{label}</span>
        <span className="font-mono text-xs text-rust-hover">{value}</span>
      </div>
      {children}
      {hint && <p className="mt-2 text-xs text-slate">{hint}</p>}
    </div>
  );
}

function fmtSec(n: number) {
  return n >= 60 ? `${Math.floor(n / 60)}m${n % 60 ? ` ${n % 60}s` : ""}` : `${n}s`;
}

/** Diff helper: only send keys that actually changed (masked secrets are skipped by the engine anyway). */
export function diffSettings(orig: Settings, next: Settings): Settings {
  const out: Settings = {};
  for (const [k, v] of Object.entries(next)) if (orig[k] !== v) out[k] = v;
  return out;
}
