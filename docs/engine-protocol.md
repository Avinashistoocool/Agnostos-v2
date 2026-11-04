# Agnostos desktop: engine protocol (v1)

The desktop app has three parts:

```
app/                Tauri 2 shell (Rust, app/src-tauri) + React/TypeScript UI (app/src)
desktop_engine/     Python engine, frozen with PyInstaller as `agnostos-engine.exe`
outreach/           existing CLI pipeline, called by the engine (unchanged behaviour)
```

Tauri starts `agnostos-engine.exe` as a **sidecar** and talks to it over
stdin/stdout using **newline-delimited JSON** (UTF-8, one object per line).
stderr is for diagnostics only. Nothing listens on a network port, except the
short-lived `127.0.0.1` loopback redirect during Google sign-in.

## Tauri bridge (frontend ↔ Rust)

- `invoke("engine_call", { method, params })` → resolves with `result`, or
  rejects with `{ code, message }` (the engine `error` object; Rust uses code
  `unavailable` if the engine process is not running).
- `listen("engine://event", e => e.payload)` where payload is `{ event, data }`.
- `invoke("engine_restart")` restarts the sidecar.
- File pickers: `@tauri-apps/plugin-dialog` `open({filters:[{name:"Resume",extensions:["pdf","docx"]}]})`.
- External links / OAuth browser: the engine opens the browser itself; the UI
  may use `@tauri-apps/plugin-opener` `openUrl()` for GitHub's verification URI.
- In plain browser dev (`npm run dev` without Tauri) `src/lib/engine.ts` falls
  back to an in-memory mock implementing the same methods, so screens can be
  built and tested without Rust or Python.

## Messages

Request (UI → engine, forwarded by Rust):
```json
{"id": 7, "method": "settings.get", "params": {}}
```
Response:
```json
{"id": 7, "result": {...}}
{"id": 7, "error": {"code": "not_signed_in", "message": "Sign in first"}}
```
Event (engine → UI, no id). Rust re-emits these as Tauri event `engine://event`:
```json
{"event": "job.log", "data": {"job_id": "j3", "line": "  [4/40] sent ..."}}
```

Error codes: `bad_request`, `not_signed_in`, `not_found`, `conflict`,
`confirmation_required`, `auth_failed`, `unavailable`, `internal`.

Long operations (OAuth, resume parse, test connections) may take seconds; the
UI must show progress. Pipeline work runs as **jobs** (see below) and returns
immediately with a `job_id`.

## Types (TypeScript)

```ts
type User = { id: string; name: string; email: string | null;
              provider: "guest" | "local" | "google" | "github";
              avatar_url?: string | null; gmail_connected: boolean };

type OnboardingStep = "resume" | "profile" | "interests" | "targets" |
                      "email" | "llm" | "funding" | "limits";
type Onboarding = { completed: OnboardingStep[]; done: boolean };

type Profile = { name: string; email: string; degree: string; institution: string;
                 research_interests: string[]; skills: string[];
                 projects: { title: string; summary: string }[];
                 resume_file: string | null };

type Settings = Record<string, string>;     // .env-style keys; secrets come back masked "••••abcd"

type CommandField = { name: string; type: "bool" | "int" | "float" | "str" | "choice";
                      label: string; help?: string; default?: unknown;
                      choices?: string[]; min?: number; max?: number };
type CommandSpec = { name: string; title: string; group: string; description: string;
                     fields: CommandField[]; live_field?: string;   // field that makes it send real mail
                     confirmation?: string };                       // text user must type when live

type Job = { id: string; command: string; options: Record<string, unknown>;
             status: "running" | "waiting_input" | "done" | "failed" | "cancelled" | "interrupted";
             started: string; finished?: string | null; exit_code?: number | null;
             live: boolean; prompt?: string | null };

type Stats = { total: number; with_email: number; drafted: number; sent: number;
               replied: number; bounced: number; resends: number;
               sent_per_day: { date: string; count: number }[] };

type Professor = { row: number; sheet: string; name: string; email: string;
                   institution: string; country: string; probability: number;
                   send_status: string; reply_status: string; subject: string;
                   draft: string; version: string };            // version = optimistic-lock token

type ReplyDraft = { index: number; name: string; email: string; subject: string;
                    their_message: string; summary: string; action: string;
                    body: string; approved: boolean; sent_at: string | null };
```

## Methods

| Method | Params | Result |
|---|---|---|
| `app.info` | – | `{version, engine_version, data_dir, user: User\|null, onboarding: Onboarding}` |
| `auth.status` | – | `{user: User\|null}` |
| `auth.guest` | `{name?}` | `{user}` |
| `auth.register` | `{name, email, password}` | `{user}` (local account, PBKDF2-hashed) |
| `auth.login` | `{email, password}` | `{user}` |
| `auth.google` | `{connect_gmail: bool}` | `{user}` — opens system browser, loopback redirect, PKCE. With `connect_gmail`, also stores a refresh token for Gmail SMTP/IMAP (XOAUTH2) |
| `auth.github.start` | – | `{user_code, verification_uri, device_code, interval, expires_in}` (device flow) |
| `auth.github.poll` | `{device_code}` | `{status: "pending"\|"slow_down"\|"done"\|"expired"\|"denied", user?}` |
| `auth.logout` | – | `{ok}` |
| `onboarding.get` | – | `Onboarding` |
| `onboarding.complete` | `{step}` | `Onboarding` |
| `resume.import` | `{path}` | `{profile: Profile}` — copies file into the user's workspace and parses it |
| `profile.get` / `profile.update` | – / `{profile}` | `{profile}` |
| `settings.get` | – | `{settings, secrets: string[]}` |
| `settings.update` | `{values}` | `{settings}` — masked values are ignored, empty string clears |
| `email.test` | `{kind: "smtp"\|"imap"}` | `{ok, detail}` |
| `llm.test` | – | `{ok, detail, models?: string[]}` |
| `stats.get` | – | `Stats` |
| `professors.list` | `{query?, status?, offset?, limit?}` | `{items: Professor[], total}` |
| `drafts.update` | `{sheet, row, version, subject?, draft}` | `{professor}` — refuses sent rows / stale version (`conflict`) |
| `replies.list` | – | `{items: ReplyDraft[], version}` |
| `replies.update` | `{index, version, body, approved}` | `{version}` |
| `conversations.get` | – | `{html, modified}` |
| `commands.list` | – | `{commands: CommandSpec[]}` — every CLI command, safe fields only |
| `jobs.start` | `{command, options, confirmation?}` | `{job: Job}` — live mail requires exact `confirmation` text |
| `jobs.list` | – | `{jobs: Job[]}` |
| `jobs.log` | `{job_id, offset?}` | `{lines: string[], offset}` |
| `jobs.answer` | `{job_id, answer: "y"\|"n"}` | `{ok}` — answers the CLI's own `[Y/N]` prompt |
| `jobs.cancel` | `{job_id}` | `{ok}` — refused for live jobs mid-delivery |
| `dialog.none` | – | – (file pickers are done in Tauri, paths passed to `resume.import`) |

Events: `job.log {job_id, line}`, `job.status {job: Job}`, `job.prompt {job_id, text}`,
`auth.progress {stage, detail}`.

## Data layout

Per-user data lives in `%LOCALAPPDATA%\Agnostos\users\<user_id>\` with
`workspace\.env`, `workspace\output\`, `workspace\resume.*`. Secrets in `.env`
are written by the engine only; OAuth refresh tokens are DPAPI-encrypted in
`tokens.bin`. A user can instead point the app at an existing v2 checkout
(`settings.update {"_workspace": "C:\\path"}`), which keeps existing outreach
data and scheduled CLI tasks working.

## OAuth configuration

Client IDs are not secrets for desktop apps but are not committed either; the
engine reads `%LOCALAPPDATA%\Agnostos\oauth.json`:
```json
{"google": {"client_id": "...apps.googleusercontent.com", "client_secret": "..."},
 "github": {"client_id": "Iv1...."}}
```
If a provider is not configured, `auth.google`/`auth.github.start` return
`unavailable` with setup instructions, and the UI hides or disables the button.

## UI notes (frontend agent)

No contract changes. Things the engine/shell should know so the UI behaves well:

- **Extra settings keys** written via `settings.update` (plain `.env` keys; please persist/return them
  in `settings.get` even if the CLI ignores them for now): `TARGET_UNIVERSITIES` (`;`-separated),
  `SEND_WEEKDAYS` (`mon,tue,...`; default weekdays), plus the existing `DISCOVER_COUNTRIES`
  (comma ISO codes, or `europe`), `GEOGRAPHY`, `POSITION`, `FOCUS_KEYWORDS` (`;`-joined interests),
  `CAN_SELF_FUND` (`true`/`false`), `SELF_FUND_NOTE`, `DAILY_SEND_CAP`, `SEND_DELAY_MIN/MAX`,
  `SEND_LOCAL_WINDOW` (`9-11` or empty), `LLM_PROVIDER`, `GROQ_API_KEY`/`OPENAI_API_KEY`,
  `DRAFT_MODEL`, `SMTP_*`, `IMAP_*`. `_workspace` is shown/edited in Settings → Workspace, so
  `settings.get` should include it.
- `email.test` / `llm.test` are called right after `settings.update`, so they must read fresh values.
- `professors.list` `status` values the UI sends: `""` (all), `unsent`, `sent`, `replied`, `failed`
  (failed sends + bounces). Sent rows are detected client-side as `send_status` in `sent`/`review-sent`.
- `jobs.log` is called with `offset: 0` when a job is opened; live lines then come from `job.log`
  events. `job.status` events should carry the full `Job` (incl. `prompt` when `waiting_input`).
- A `CommandSpec` with `live_field` renders that field inside a red "Danger zone"; when on, the UI
  requires typing `confirmation` exactly (falls back to `SEND` if missing) and passes it to `jobs.start`.
  Other fields are rendered by `type`; `default`, `min`, `max`, `choices`, `help` are honoured.
- `conversations.get.html` is rendered in `<iframe sandbox="" srcdoc>` (no scripts, no same-origin).
- `auth.progress` `detail` is shown under the Google button while `auth.google` is pending.
- **Shell (Tauri capabilities)**: the UI uses `core:event` listen (`engine://event`),
  `dialog:allow-open`, `opener:allow-open-url` (github.com/login/device, console.groq.com,
  platform.openai.com), and `getCurrentWebview().onDragDropEvent` for native resume drops (keep
  `dragDropEnabled` on). Vite dev server: `http://localhost:1420`, build output `app/dist`.
