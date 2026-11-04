// In-memory engine used when the UI runs outside Tauri (plain browser dev, tests, e2e).
// Implements the same methods as docs/engine-protocol.md with realistic fake data.
import type {
  CommandSpec,
  EngineEvent,
  Job,
  Onboarding,
  OnboardingStep,
  Professor,
  Profile,
  ReplyDraft,
  Settings,
  Stats,
  User,
} from "./types";
import { ONBOARDING_STEPS } from "./types";

type Err = { code: string; message: string };
const err = (code: string, message: string): Err => ({ code, message });

export type MockOptions = {
  latency?: number;
  logInterval?: number;
  unavailable?: ("google" | "github")[];
  /** Start already signed-in and onboarded (handy for component tests). */
  signedIn?: boolean;
};

const SECRET_KEYS = ["GROQ_API_KEY", "OPENAI_API_KEY", "SMTP_PASSWORD", "IMAP_PASSWORD", "OPENALEX_API_KEY"];

function mask(v: string) {
  return v ? "••••" + v.slice(-4) : "";
}

function today(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

function nowStamp() {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

const PROFS: Omit<Professor, "row" | "sheet" | "version">[] = [
  {
    name: "Prof. Dr. Lena Hartmann",
    email: "lena.hartmann@physik.uni-heidelberg.de",
    institution: "Heidelberg University",
    country: "Germany",
    probability: 0.82,
    send_status: "",
    reply_status: "",
    subject: "Summer research on ATLAS trigger studies",
    draft:
      "Dear Professor Hartmann,\n\nI read your group's recent paper on the ATLAS Level-1 topological trigger and was struck by how the timing constraints shaped the algorithm design. I'm a second-year physics student at IIT Madras, and last semester I wrote a small FPGA-style trigger emulator in Python for a course project.\n\nWould you have room for a summer intern (May–July) in your group? I'd be glad to help with simulation or analysis work, and I can share my code and transcript.\n\nBest regards,\nAarav Sharma",
  },
  {
    name: "Dr. Matteo Rossi",
    email: "matteo.rossi@cern.ch",
    institution: "CERN",
    country: "Switzerland",
    probability: 0.74,
    send_status: "sent",
    reply_status: "replied",
    subject: "Question about your LHCb flavour-tagging work",
    draft:
      "Dear Dr. Rossi,\n\nYour talk on graph-neural-network flavour tagging at LHCb was the clearest introduction to the topic I've found...\n\nBest,\nAarav",
  },
  {
    name: "Prof. Sophie Laurent",
    email: "s.laurent@ens.psl.eu",
    institution: "École Normale Supérieure",
    country: "France",
    probability: 0.69,
    send_status: "",
    reply_status: "",
    subject: "Internship inquiry: neutrino phenomenology",
    draft:
      "Dear Professor Laurent,\n\nI have been working through your lecture notes on sterile-neutrino oscillation fits and tried reproducing Figure 3 from your 2024 paper...\n\nKind regards,\nAarav Sharma",
  },
  {
    name: "Prof. James Whitaker",
    email: "j.whitaker@imperial.ac.uk",
    institution: "Imperial College London",
    country: "United Kingdom",
    probability: 0.61,
    send_status: "sent",
    reply_status: "",
    subject: "Summer project on detector calibration",
    draft: "Dear Professor Whitaker,\n\nI'm writing about possible summer projects on calorimeter calibration...\n\nBest,\nAarav",
  },
  {
    name: "Dr. Anna Kowalska",
    email: "anna.kowalska@fuw.edu.pl",
    institution: "University of Warsaw",
    country: "Poland",
    probability: 0.55,
    send_status: "failed: SMTPRecipientsRefused",
    reply_status: "bounced",
    subject: "Research internship in ML for HEP",
    draft: "Dear Dr. Kowalska,\n\n...",
  },
  {
    name: "Prof. Erik Lindqvist",
    email: "erik.lindqvist@fysik.su.se",
    institution: "Stockholm University",
    country: "Sweden",
    probability: 0.48,
    send_status: "",
    reply_status: "",
    subject: "Interest in dark-matter direct detection",
    draft:
      "Dear Professor Lindqvist,\n\nI came across the XENONnT background-modelling note your group posted and had a question about the radon emanation estimates...\n\nBest regards,\nAarav Sharma",
  },
  {
    name: "Prof. Chiara Bianchi",
    email: "chiara.bianchi@unimi.it",
    institution: "University of Milan",
    country: "Italy",
    probability: 0.44,
    send_status: "dry-run",
    reply_status: "",
    subject: "Summer research: lattice QCD numerics",
    draft: "Dear Professor Bianchi,\n\n...",
  },
  {
    name: "Dr. Pieter de Vries",
    email: "p.devries@nikhef.nl",
    institution: "Nikhef",
    country: "Netherlands",
    probability: 0.39,
    send_status: "",
    reply_status: "",
    subject: "",
    draft: "",
  },
];

const REPLIES: ReplyDraft[] = [
  {
    index: 0,
    name: "Dr. Matteo Rossi",
    email: "matteo.rossi@cern.ch",
    subject: "Re: Question about your LHCb flavour-tagging work",
    their_message:
      "Dear Aarav,\n\nThanks for your thoughtful note. We do occasionally host summer students, but funding is tight this year. Could you tell me whether you'd be able to cover your own living costs in Geneva? If so, I'd be happy to have a short call next week.\n\nBest,\nMatteo",
    summary: "Interested; asks whether you can self-fund living costs and offers a call next week.",
    action: "answer funding question + propose call",
    body:
      "Dear Dr. Rossi,\n\nThank you for getting back to me. Yes, I can cover my own living costs for the summer, so funding wouldn't be a blocker. I'd be glad to talk next week; Tuesday or Thursday afternoon (CET) works well for me.\n\nBest regards,\nAarav",
    approved: false,
    sent_at: null,
  },
  {
    index: 1,
    name: "Prof. Kenji Watanabe",
    email: "watanabe@hep.phys.s.u-tokyo.ac.jp",
    subject: "Re: Summer internship inquiry",
    their_message:
      "Dear Mr. Sharma,\n\nUnfortunately our group has no open positions for this summer. I suggest applying to the UTRIP programme, which opens in January.\n\nRegards,\nK. Watanabe",
    summary: "Polite decline; suggests applying to the UTRIP programme in January.",
    action: "thank + acknowledge",
    body:
      "Dear Professor Watanabe,\n\nThank you for letting me know, and for the UTRIP pointer. I'll apply when it opens in January.\n\nBest regards,\nAarav Sharma",
    approved: true,
    sent_at: null,
  },
];

const COMMANDS: CommandSpec[] = [
  {
    name: "discover",
    title: "Discover professors",
    group: "Find",
    description: "Search OpenAlex for active researchers matching your interests and target countries.",
    fields: [
      { name: "count", type: "int", label: "How many", default: 40, min: 5, max: 400, help: "New professors to add to the sheet." },
      { name: "countries", type: "str", label: "Countries", default: "europe", help: "Region name or ISO codes like de,ch,gb." },
      { name: "since", type: "int", label: "Active since (year)", default: 2021, min: 2000, max: 2030 },
    ],
  },
  {
    name: "verify",
    title: "Verify email addresses",
    group: "Find",
    description: "Check addresses with DNS/MX and optionally repair them from staff pages.",
    fields: [{ name: "dry_run", type: "bool", label: "Report only", default: true }],
  },
  {
    name: "run",
    title: "Match & draft",
    group: "Draft",
    description: "Score professors against your profile and draft honest, specific cold emails with the LLM.",
    fields: [
      { name: "max_professors", type: "int", label: "Max professors", default: 25, min: 1, max: 500, help: "Cap on LLM-evaluated professors (controls cost)." },
      { name: "position", type: "choice", label: "Position", default: "summer internship", choices: ["summer internship", "research assistant", "thesis project", "PhD inquiry"] },
    ],
  },
  {
    name: "send",
    title: "Send emails",
    group: "Send",
    description: "Dispatch drafted emails, paced and capped. Dry run by default: nothing leaves your outbox.",
    fields: [
      { name: "limit", type: "int", label: "Max emails this run", default: 10, min: 1, max: 100 },
      { name: "min_probability", type: "float", label: "Min match score", default: 0.4, min: 0, max: 1 },
      { name: "live", type: "bool", label: "Send for real", default: false, help: "Off = dry run. On = real emails to real professors." },
    ],
    live_field: "live",
    confirmation: "SEND LIVE",
  },
  {
    name: "check-replies",
    title: "Check replies",
    group: "Replies",
    description: "Scan your inbox for replies and bounces, then draft responses for review.",
    fields: [{ name: "dry_run", type: "bool", label: "Report only", default: false }],
  },
  {
    name: "replies",
    title: "Send approved replies",
    group: "Replies",
    description: "Send the replies you approved on the Replies screen.",
    fields: [{ name: "live", type: "bool", label: "Send for real", default: false }],
    live_field: "live",
    confirmation: "SEND REPLIES",
  },
  {
    name: "stats",
    title: "Statistics",
    group: "Maintain",
    description: "Count rows drafted, sent, replied and skipped (and why).",
    fields: [],
  },
];

const DEFAULT_PROFILE: Profile = {
  name: "",
  email: "",
  degree: "",
  institution: "",
  research_interests: [],
  skills: [],
  projects: [],
  resume_file: null,
};

const PARSED_PROFILE: Profile = {
  name: "Aarav Sharma",
  email: "aarav.sharma@smail.iitm.ac.in",
  degree: "B.S. Physics (2nd year)",
  institution: "IIT Madras",
  research_interests: ["particle physics", "machine learning"],
  skills: ["Python", "C++", "ROOT", "PyTorch", "LaTeX"],
  projects: [
    { title: "Trigger emulator", summary: "Python emulator of a Level-1 calorimeter trigger with latency budget checks." },
    { title: "Jet tagging with GNNs", summary: "Course project: graph neural network for b-jet tagging on open CMS data." },
  ],
  resume_file: null,
};

type MockJob = Job & { lines: string[]; timer?: ReturnType<typeof setTimeout>; script: string[]; pos: number; promptAt?: number };

export class MockEngine {
  latency: number;
  logInterval: number;
  unavailable: Set<string>;
  user: User | null = null;
  onboarding: Onboarding = { completed: [], done: false };
  profile: Profile = { ...DEFAULT_PROFILE };
  settings: Settings = {
    LLM_PROVIDER: "groq",
    GROQ_API_KEY: "",
    OPENAI_API_KEY: "",
    DRAFT_MODEL: "",
    SMTP_HOST: "",
    SMTP_PORT: "587",
    SMTP_SECURITY: "starttls",
    SMTP_USER: "",
    SMTP_PASSWORD: "",
    SMTP_FROM: "",
    SMTP_FROM_NAME: "",
    IMAP_HOST: "",
    IMAP_PORT: "993",
    IMAP_USER: "",
    IMAP_PASSWORD: "",
    POSITION: "summer research internship (undergraduate)",
    GEOGRAPHY: "Europe (EU + Switzerland + UK)",
    DISCOVER_COUNTRIES: "europe",
    CAN_SELF_FUND: "",
    SELF_FUND_NOTE: "",
    DAILY_SEND_CAP: "25",
    SEND_DELAY_MIN: "90",
    SEND_DELAY_MAX: "240",
    SEND_LOCAL_WINDOW: "9-11",
    FOCUS_KEYWORDS: "",
    _workspace: "C:\\Users\\student\\AppData\\Local\\Agnostos\\users\\u1\\workspace",
  };
  professors: Professor[];
  replies: ReplyDraft[];
  repliesVersion = 1;
  jobs: MockJob[] = [];
  private seq = 0;
  private listeners = new Set<(e: EngineEvent) => void>();
  private githubPolls = 0;
  private accounts = new Map<string, { name: string; password: string }>();
  down = false;

  constructor(opts: MockOptions = {}) {
    this.latency = opts.latency ?? 250;
    this.logInterval = opts.logInterval ?? 140;
    this.unavailable = new Set(opts.unavailable ?? []);
    this.professors = PROFS.map((p, i) => ({ ...p, row: i + 2, sheet: "Professors", version: `v${i}-1` }));
    this.replies = REPLIES.map((r) => ({ ...r }));
    if (opts.signedIn) {
      this.user = { id: "u1", name: "Aarav Sharma", email: "aarav@example.com", provider: "local", gmail_connected: false };
      this.onboarding = { completed: [...ONBOARDING_STEPS], done: true };
      this.profile = { ...PARSED_PROFILE };
    }
    // a finished historical job
    this.jobs.push({
      id: "j0",
      command: "discover",
      options: { count: 40 },
      status: "done",
      started: `${today(-1)} 18:02:11`,
      finished: `${today(-1)} 18:04:40`,
      exit_code: 0,
      live: false,
      prompt: null,
      lines: ["Searching OpenAlex for 'particle physics' in europe…", "  + 40 candidates, 31 with verified email", "Done."],
      script: [],
      pos: 0,
    });
  }

  subscribe(fn: (e: EngineEvent) => void) {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private emit(e: EngineEvent) {
    this.listeners.forEach((l) => l(e));
  }

  restart() {
    this.down = false;
  }

  private publicJob(j: MockJob): Job {
    const { lines: _l, timer: _t, script: _s, pos: _p, promptAt: _pa, ...rest } = j;
    void _l, _t, _s, _p, _pa;
    return { ...rest };
  }

  private requireUser() {
    if (!this.user) throw err("not_signed_in", "Sign in first");
  }

  private maskedSettings(): Settings {
    const out: Settings = {};
    for (const [k, v] of Object.entries(this.settings)) out[k] = SECRET_KEYS.includes(k) ? mask(v) : v;
    return out;
  }

  private stats(): Stats {
    const p = this.professors;
    const sent = p.filter((x) => x.send_status === "sent").length + 19;
    const days = Array.from({ length: 14 }, (_, i) => {
      const d = today(i - 13);
      const count = [0, 3, 5, 0, 0, 8, 12, 6, 4, 0, 0, 9, 11, 7][i];
      return { date: d, count };
    });
    return {
      total: 128,
      with_email: 104,
      drafted: p.filter((x) => x.draft).length + 52,
      sent,
      replied: 6,
      bounced: 2,
      resends: 1,
      sent_per_day: days,
    };
  }

  async handle(method: string, params: unknown): Promise<unknown> {
    if (this.latency) await new Promise((r) => setTimeout(r, this.latency));
    if (this.down) throw err("unavailable", "Engine process is not running");
    const p = (params ?? {}) as Record<string, any>;
    switch (method) {
      case "app.info":
        return {
          version: "0.1.0",
          engine_version: "0.1.0-mock",
          data_dir: "C:\\Users\\student\\AppData\\Local\\Agnostos",
          user: this.user,
          onboarding: this.onboarding,
        };
      case "auth.status":
        return { user: this.user };
      case "auth.guest":
        this.user = { id: "guest", name: p.name || "Guest", email: null, provider: "guest", gmail_connected: false };
        return { user: this.user };
      case "auth.register": {
        if (!p.email || !p.password) throw err("bad_request", "Email and password are required");
        if (String(p.password).length < 8) throw err("bad_request", "Password must be at least 8 characters");
        if (this.accounts.has(p.email)) throw err("conflict", "An account with that email already exists");
        this.accounts.set(p.email, { name: p.name, password: p.password });
        this.user = { id: "u-" + p.email, name: p.name || p.email, email: p.email, provider: "local", gmail_connected: false };
        return { user: this.user };
      }
      case "auth.login": {
        const a = this.accounts.get(p.email);
        if (!a || a.password !== p.password) throw err("auth_failed", "Wrong email or password");
        this.user = { id: "u-" + p.email, name: a.name, email: p.email, provider: "local", gmail_connected: false };
        return { user: this.user };
      }
      case "auth.google": {
        if (this.unavailable.has("google"))
          throw err("unavailable", "Google sign-in is not configured. Add a client ID to %LOCALAPPDATA%\\Agnostos\\oauth.json.");
        this.emit({ event: "auth.progress", data: { stage: "browser", detail: "Opened your browser…" } });
        await new Promise((r) => setTimeout(r, this.latency * 2));
        this.emit({ event: "auth.progress", data: { stage: "token", detail: "Exchanging code…" } });
        this.user = {
          id: "g1",
          name: "Aarav Sharma",
          email: "aarav.sharma@gmail.com",
          provider: "google",
          avatar_url: null,
          gmail_connected: !!p.connect_gmail,
        };
        return { user: this.user };
      }
      case "auth.github.start":
        if (this.unavailable.has("github"))
          throw err("unavailable", "GitHub sign-in is not configured. Add a client ID to %LOCALAPPDATA%\\Agnostos\\oauth.json.");
        this.githubPolls = 0;
        return { user_code: "WDJB-MJHT", verification_uri: "https://github.com/login/device", device_code: "dev-123", interval: 1, expires_in: 900 };
      case "auth.github.poll":
        this.githubPolls += 1;
        if (this.githubPolls < 3) return { status: "pending" };
        this.user = { id: "gh1", name: "aarav-s", email: "aarav@users.noreply.github.com", provider: "github", gmail_connected: false };
        return { status: "done", user: this.user };
      case "auth.logout":
        this.user = null;
        return { ok: true };
      case "onboarding.get":
        this.requireUser();
        return this.onboarding;
      case "onboarding.complete": {
        this.requireUser();
        const step = p.step as OnboardingStep;
        if (!ONBOARDING_STEPS.includes(step)) throw err("bad_request", "Unknown step " + step);
        if (!this.onboarding.completed.includes(step)) this.onboarding.completed.push(step);
        this.onboarding.done = ONBOARDING_STEPS.every((s) => this.onboarding.completed.includes(s));
        return { ...this.onboarding, completed: [...this.onboarding.completed] };
      }
      case "resume.import": {
        this.requireUser();
        if (!p.path) throw err("bad_request", "path is required");
        await new Promise((r) => setTimeout(r, this.latency * 2));
        const name = String(p.path).split(/[\\/]/).pop() || "resume.pdf";
        this.profile = { ...PARSED_PROFILE, resume_file: "resume." + (name.split(".").pop() || "pdf") };
        return { profile: this.profile };
      }
      case "profile.get":
        this.requireUser();
        return { profile: this.profile };
      case "profile.update":
        this.requireUser();
        this.profile = { ...this.profile, ...(p.profile as Profile) };
        return { profile: this.profile };
      case "settings.get":
        this.requireUser();
        return { settings: this.maskedSettings(), secrets: SECRET_KEYS };
      case "settings.update": {
        this.requireUser();
        const values = (p.values ?? {}) as Settings;
        for (const [k, v] of Object.entries(values)) {
          if (typeof v === "string" && v.startsWith("••••")) continue;
          this.settings[k] = v;
        }
        return { settings: this.maskedSettings() };
      }
      case "email.test": {
        this.requireUser();
        await new Promise((r) => setTimeout(r, this.latency * 2));
        const kind = p.kind === "imap" ? "IMAP" : "SMTP";
        if (this.user?.gmail_connected) return { ok: true, detail: `${kind} OK via Gmail (XOAUTH2)` };
        const host = this.settings[p.kind === "imap" ? "IMAP_HOST" : "SMTP_HOST"];
        if (!host) return { ok: false, detail: `${kind} host is not set` };
        return { ok: true, detail: `${kind} login OK at ${host}` };
      }
      case "llm.test": {
        this.requireUser();
        await new Promise((r) => setTimeout(r, this.latency * 2));
        const prov = this.settings.LLM_PROVIDER || "groq";
        const key = prov === "openai" ? this.settings.OPENAI_API_KEY : this.settings.GROQ_API_KEY;
        if (!key) return { ok: false, detail: `No ${prov} API key set` };
        return {
          ok: true,
          detail: `Connected to ${prov}`,
          models: prov === "openai" ? ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"] : ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
        };
      }
      case "stats.get":
        this.requireUser();
        return this.stats();
      case "professors.list": {
        this.requireUser();
        const q = String(p.query ?? "").toLowerCase();
        const st = String(p.status ?? "");
        let items = this.professors.filter(
          (x) => !q || [x.name, x.email, x.institution, x.country].some((f) => f.toLowerCase().includes(q)),
        );
        if (st === "unsent") items = items.filter((x) => x.send_status !== "sent");
        else if (st === "sent") items = items.filter((x) => x.send_status === "sent");
        else if (st === "replied") items = items.filter((x) => !!x.reply_status && x.reply_status !== "bounced");
        else if (st === "failed") items = items.filter((x) => x.send_status.startsWith("failed") || x.reply_status === "bounced");
        const off = p.offset ?? 0;
        const lim = p.limit ?? 200;
        return { items: items.slice(off, off + lim).map((x) => ({ ...x })), total: items.length };
      }
      case "drafts.update": {
        this.requireUser();
        const prof = this.professors.find((x) => x.sheet === p.sheet && x.row === p.row);
        if (!prof) throw err("not_found", "Row not found");
        if (prof.send_status === "sent") throw err("conflict", "This email was already sent; it can't be edited");
        if (prof.version !== p.version) throw err("conflict", "The sheet changed since you opened this draft");
        prof.draft = String(p.draft);
        if (typeof p.subject === "string") prof.subject = p.subject;
        const [base, n] = prof.version.split("-");
        prof.version = `${base}-${Number(n) + 1}`;
        return { professor: { ...prof } };
      }
      case "replies.list":
        this.requireUser();
        return { items: this.replies.map((r) => ({ ...r })), version: String(this.repliesVersion) };
      case "replies.update": {
        this.requireUser();
        if (String(p.version) !== String(this.repliesVersion)) throw err("conflict", "Reply queue changed; reload and try again");
        const r = this.replies.find((x) => x.index === p.index);
        if (!r) throw err("not_found", "Reply not found");
        if (r.sent_at) throw err("conflict", "Already sent");
        r.body = String(p.body);
        r.approved = !!p.approved;
        this.repliesVersion += 1;
        return { version: String(this.repliesVersion) };
      }
      case "conversations.get":
        this.requireUser();
        return { html: CONVO_HTML, modified: nowStamp() };
      case "commands.list":
        this.requireUser();
        return { commands: COMMANDS };
      case "jobs.start":
        this.requireUser();
        return { job: this.publicJob(this.startJob(p.command, p.options ?? {}, p.confirmation)) };
      case "jobs.list":
        this.requireUser();
        return { jobs: [...this.jobs].reverse().map((j) => this.publicJob(j)) };
      case "jobs.log": {
        const j = this.jobs.find((x) => x.id === p.job_id);
        if (!j) throw err("not_found", "No such job");
        const off = p.offset ?? 0;
        return { lines: j.lines.slice(off), offset: j.lines.length };
      }
      case "jobs.answer": {
        const j = this.jobs.find((x) => x.id === p.job_id);
        if (!j) throw err("not_found", "No such job");
        if (j.status !== "waiting_input") throw err("bad_request", "Job is not waiting for input");
        this.pushLine(j, `> ${p.answer === "y" ? "Y" : "N"}`);
        j.prompt = null;
        if (p.answer === "y") {
          j.status = "running";
          this.emit({ event: "job.status", data: { job: this.publicJob(j) } });
          this.tick(j);
        } else {
          this.pushLine(j, "Aborted by user.");
          this.finish(j, "cancelled", 1);
        }
        return { ok: true };
      }
      case "jobs.cancel": {
        const j = this.jobs.find((x) => x.id === p.job_id);
        if (!j) throw err("not_found", "No such job");
        if (j.live && j.status === "running") throw err("conflict", "Live sending can't be cancelled mid-delivery");
        if (j.status === "running" || j.status === "waiting_input") {
          if (j.timer) clearTimeout(j.timer);
          this.pushLine(j, "Cancelled.");
          this.finish(j, "cancelled", null);
        }
        return { ok: true };
      }
      default:
        throw err("bad_request", `Unknown method ${method}`);
    }
  }

  private startJob(command: string, options: Record<string, unknown>, confirmation?: string): MockJob {
    const spec = COMMANDS.find((c) => c.name === command);
    if (!spec) throw err("bad_request", `Unknown command ${command}`);
    const live = !!(spec.live_field && options[spec.live_field]);
    if (live && confirmation !== spec.confirmation)
      throw err("confirmation_required", `Type "${spec.confirmation}" to confirm sending real email`);
    if (this.jobs.some((j) => j.status === "running" || j.status === "waiting_input"))
      throw err("conflict", "Another job is already running");
    const id = "j" + ++this.seq;
    const script = scriptFor(command, options, live);
    const job: MockJob = {
      id,
      command,
      options,
      status: "running",
      started: nowStamp(),
      finished: null,
      exit_code: null,
      live,
      prompt: null,
      lines: [],
      script: script.lines,
      pos: 0,
      promptAt: script.promptAt,
    };
    this.jobs.push(job);
    setTimeout(() => {
      this.emit({ event: "job.status", data: { job: this.publicJob(job) } });
      this.tick(job);
    }, 0);
    return job;
  }

  private pushLine(j: MockJob, line: string) {
    j.lines.push(line);
    this.emit({ event: "job.log", data: { job_id: j.id, line } });
  }

  private finish(j: MockJob, status: Job["status"], code: number | null) {
    j.status = status;
    j.exit_code = code;
    j.finished = nowStamp();
    j.prompt = null;
    this.emit({ event: "job.status", data: { job: this.publicJob(j) } });
  }

  private tick(j: MockJob) {
    j.timer = setTimeout(() => {
      if (j.status !== "running") return;
      if (j.pos >= j.script.length) {
        this.finish(j, "done", 0);
        return;
      }
      const line = j.script[j.pos++];
      this.pushLine(j, line);
      if (j.promptAt !== undefined && j.pos === j.promptAt) {
        j.status = "waiting_input";
        j.prompt = line;
        this.emit({ event: "job.prompt", data: { job_id: j.id, text: line } });
        this.emit({ event: "job.status", data: { job: this.publicJob(j) } });
        return;
      }
      this.tick(j);
    }, this.logInterval);
  }
}

function scriptFor(command: string, options: Record<string, unknown>, live: boolean): { lines: string[]; promptAt?: number } {
  if (command === "send") {
    const n = Math.min(Number(options.limit ?? 5), 6);
    const lines = [
      live ? "LIVE MODE: real emails will be sent." : "DRY RUN: nothing will leave your outbox.",
      `Daily cap 25 · delay 90–240 s · window 9–11 recipient-local`,
      `${n} drafts eligible (min score ${options.min_probability ?? 0.4}).`,
      `Proceed with ${n} emails? [Y/N]`,
    ];
    const names = ["Hartmann", "Laurent", "Lindqvist", "Bianchi", "de Vries", "Novak"];
    for (let i = 0; i < n; i++) lines.push(`  [${i + 1}/${n}] ${live ? "sent" : "dry-run"} → Prof. ${names[i]}`);
    lines.push(`Finished: ${n} ${live ? "sent" : "dry-run"}, 0 failed.`);
    return { lines, promptAt: 4 };
  }
  if (command === "run") {
    return {
      lines: [
        "Parsing resume… ok",
        "Loaded 128 professors (104 with email)",
        "Local pre-score: 61 above threshold",
        `LLM will evaluate ${options.max_professors ?? 25} professors (est. $0.04). Continue? [Y/N]`,
        "  scoring 1/25 Hartmann 0.82",
        "  scoring 2/25 Laurent 0.69",
        "  drafting Hartmann…",
        "  drafting Laurent…",
        "Wrote 2 drafts to output/professors.xlsx",
      ],
      promptAt: 4,
    };
  }
  return {
    lines: [`Running ${command} ${JSON.stringify(options)}`, "  working…", "  working…", "Done."],
  };
}

const CONVO_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>
body{font-family:Segoe UI,system-ui,sans-serif;background:#16171b;color:#f4efe6;margin:0;padding:24px}
.t{border:1px solid #2a2d35;border-radius:12px;padding:16px;margin-bottom:16px;background:#1e2026}
h2{font-size:15px;margin:0 0 8px}.m{color:#8b93a1;font-size:12px}.o{border-left:3px solid #b5452e;padding-left:10px;margin:10px 0}
.i{border-left:3px solid #7fa37a;padding-left:10px;margin:10px 0}p{white-space:pre-wrap;margin:4px 0;font-size:13px;line-height:1.5}
</style></head><body>
<div class="t"><h2>Dr. Matteo Rossi · CERN</h2>
<div class="o"><div class="m">You · 3 days ago</div><p>Dear Dr. Rossi, your talk on GNN flavour tagging…</p></div>
<div class="i"><div class="m">Matteo Rossi · yesterday</div><p>Thanks for your thoughtful note. Could you cover your own living costs?</p></div></div>
<div class="t"><h2>Prof. Kenji Watanabe · University of Tokyo</h2>
<div class="o"><div class="m">You · 5 days ago</div><p>Dear Professor Watanabe…</p></div>
<div class="i"><div class="m">K. Watanabe · 2 days ago</div><p>Unfortunately our group has no open positions…</p></div></div>
<script>document.title='conversations'</script>
</body></html>`;
