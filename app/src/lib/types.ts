// Types mirror docs/engine-protocol.md (v1). Do not diverge from the contract.

export type Provider = "guest" | "local" | "google" | "github";

export type User = {
  id: string;
  name: string;
  email: string | null;
  provider: Provider;
  avatar_url?: string | null;
  gmail_connected: boolean;
};

export type OnboardingStep = "resume" | "profile" | "interests" | "targets" | "email" | "llm" | "funding" | "limits";
export type Onboarding = { completed: OnboardingStep[]; done: boolean };

export type Project = { title: string; summary: string };
export type Profile = {
  name: string;
  email: string;
  degree: string;
  institution: string;
  research_interests: string[];
  skills: string[];
  projects: Project[];
  resume_file: string | null;
};

export type Settings = Record<string, string>;

export type CommandField = {
  name: string;
  type: "bool" | "int" | "float" | "str" | "choice";
  label: string;
  help?: string;
  default?: unknown;
  choices?: string[];
  min?: number;
  max?: number;
};

export type CommandSpec = {
  name: string;
  title: string;
  group: string;
  description: string;
  fields: CommandField[];
  live_field?: string;
  confirmation?: string;
};

export type JobStatus = "running" | "waiting_input" | "done" | "failed" | "cancelled" | "interrupted";
export type Job = {
  id: string;
  command: string;
  options: Record<string, unknown>;
  status: JobStatus;
  started: string;
  finished?: string | null;
  exit_code?: number | null;
  live: boolean;
  prompt?: string | null;
};

export type Stats = {
  total: number;
  with_email: number;
  drafted: number;
  sent: number;
  replied: number;
  bounced: number;
  resends: number;
  sent_per_day: { date: string; count: number }[];
};

export type Professor = {
  row: number;
  sheet: string;
  name: string;
  email: string;
  institution: string;
  country: string;
  probability: number;
  send_status: string;
  reply_status: string;
  subject: string;
  draft: string;
  version: string;
};

export type ReplyDraft = {
  index: number;
  name: string;
  email: string;
  subject: string;
  their_message: string;
  summary: string;
  action: string;
  body: string;
  approved: boolean;
  sent_at: string | null;
};

export type AppInfo = {
  version: string;
  engine_version: string;
  data_dir: string;
  user: User | null;
  onboarding: Onboarding;
};

export type GithubStart = {
  user_code: string;
  verification_uri: string;
  device_code: string;
  interval: number;
  expires_in: number;
};

export type GithubPoll = { status: "pending" | "slow_down" | "done" | "expired" | "denied"; user?: User };

export type ErrorCode =
  | "bad_request"
  | "not_signed_in"
  | "not_found"
  | "conflict"
  | "confirmation_required"
  | "auth_failed"
  | "unavailable"
  | "internal";

type NoParams = Record<string, never> | undefined;

/** Method name → [params, result]. */
export interface Methods {
  "app.info": [NoParams, AppInfo];
  "auth.status": [NoParams, { user: User | null }];
  "auth.guest": [{ name?: string } | undefined, { user: User }];
  "auth.register": [{ name: string; email: string; password: string }, { user: User }];
  "auth.login": [{ email: string; password: string }, { user: User }];
  "auth.google": [{ connect_gmail: boolean }, { user: User }];
  "auth.github.start": [NoParams, GithubStart];
  "auth.github.poll": [{ device_code: string }, GithubPoll];
  "auth.logout": [NoParams, { ok: boolean }];
  "onboarding.get": [NoParams, Onboarding];
  "onboarding.complete": [{ step: OnboardingStep }, Onboarding];
  "resume.import": [{ path: string }, { profile: Profile }];
  "profile.get": [NoParams, { profile: Profile }];
  "profile.update": [{ profile: Profile }, { profile: Profile }];
  "settings.get": [NoParams, { settings: Settings; secrets: string[] }];
  "settings.update": [{ values: Settings }, { settings: Settings }];
  "email.test": [{ kind: "smtp" | "imap" }, { ok: boolean; detail: string }];
  "llm.test": [NoParams, { ok: boolean; detail: string; models?: string[] }];
  "stats.get": [NoParams, Stats];
  "professors.list": [
    { query?: string; status?: string; offset?: number; limit?: number } | undefined,
    { items: Professor[]; total: number },
  ];
  "drafts.update": [
    { sheet: string; row: number; version: string; subject?: string; draft: string },
    { professor: Professor },
  ];
  "replies.list": [NoParams, { items: ReplyDraft[]; version: string }];
  "replies.update": [{ index: number; version: string; body: string; approved: boolean }, { version: string }];
  "conversations.get": [NoParams, { html: string; modified: string | null }];
  "commands.list": [NoParams, { commands: CommandSpec[] }];
  "jobs.start": [{ command: string; options: Record<string, unknown>; confirmation?: string }, { job: Job }];
  "jobs.list": [NoParams, { jobs: Job[] }];
  "jobs.log": [{ job_id: string; offset?: number }, { lines: string[]; offset: number }];
  "jobs.answer": [{ job_id: string; answer: "y" | "n" }, { ok: boolean }];
  "jobs.cancel": [{ job_id: string }, { ok: boolean }];
}

export type MethodName = keyof Methods;
export type ParamsOf<M extends MethodName> = Methods[M][0];
export type ResultOf<M extends MethodName> = Methods[M][1];

export type EngineEvent =
  | { event: "job.log"; data: { job_id: string; line: string } }
  | { event: "job.status"; data: { job: Job } }
  | { event: "job.prompt"; data: { job_id: string; text: string } }
  | { event: "auth.progress"; data: { stage: string; detail: string } };

export const ONBOARDING_STEPS: OnboardingStep[] = [
  "resume",
  "profile",
  "interests",
  "targets",
  "email",
  "llm",
  "funding",
  "limits",
];
