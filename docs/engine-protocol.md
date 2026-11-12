# Agnostos desktop: engine protocol (v1)

The desktop app has three parts:

```
app/                Tauri 2 shell (Rust, app/src-tauri) + React/TypeScript UI (app/src)
desktop_engine/     Python engine, frozen with PyInstaller as `agnostos-engine.exe`
outreach/           existing CLI pipeline, called by the engine (unchanged behaviour)
```

Tauri starts `agnostos-engine.exe` as a **sidecar**. It communicates with the sidecar over
stdin/stdout with **newline-delimited JSON** (UTF-8, one object on each line).
stderr is only for diagnostics. No process listens on a network port. The only exception is the
short `127.0.0.1` loopback redirect during the Google sign-in.

## Tauri bridge (frontend ↔ Rust)

- `invoke("engine_call", { method, params })` → resolves with `result`, or
  rejects with `{ code, message }` (the engine `error` object). If the engine process is not active, Rust uses the code
  `unavailable`.
- `listen("engine://event", e => e.payload)`, where the payload is `{ event, data }`.
- `invoke("engine_restart")` starts the sidecar again.
- File pickers: `@tauri-apps/plugin-dialog` `open({filters:[{name:"Resume",extensions:["pdf","docx"]}]})`.
- External links / OAuth browser: the engine opens the browser itself. The UI
  can use `@tauri-apps/plugin-opener` `openUrl()` for the verification URI of GitHub.
- In plain browser dev mode (`npm run dev` without Tauri), `src/lib/engine.ts` uses
  an in-memory mock that has the same methods. Thus, you can build and test the screens without Rust or Python.

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
Event (engine → UI, no id). Rust sends these again as the Tauri event `engine://event`:
```json
{"event": "job.log", "data": {"job_id": "j3", "line": "  [4/40] sent ..."}}
```

Error codes: `bad_request`, `not_signed_in`, `not_found`, `conflict`,
`confirmation_required`, `auth_failed`, `unavailable`, `internal`.

Long operations (OAuth, resume parse, connection tests) can take some seconds. The
UI must show the progress. Pipeline work runs as **jobs** (see below). A job request returns
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
| `auth.google` | `{connect_gmail: bool}` | `{user}`. Opens the system browser, loopback redirect, PKCE. With `connect_gmail`, it also stores a refresh token for Gmail SMTP/IMAP (XOAUTH2) |
| `auth.github.start` | – | `{user_code, verification_uri, device_code, interval, expires_in}` (device flow) |
| `auth.github.poll` | `{device_code}` | `{status: "pending"\|"slow_down"\|"done"\|"expired"\|"denied", user?}` |
| `auth.logout` | – | `{ok}` |
| `onboarding.get` | – | `Onboarding` |
| `onboarding.complete` | `{step}` | `Onboarding` |
| `resume.import` | `{path}` | `{profile: Profile}`. Copies the file into the workspace of the user and parses it |
| `profile.get` / `profile.update` | – / `{profile}` | `{profile}` |
| `settings.get` | – | `{settings, secrets: string[]}` |
| `settings.update` | `{values}` | `{settings}`. The engine ignores masked values; an empty string clears the value |
| `email.test` | `{kind: "smtp"\|"imap"}` | `{ok, detail}` |
| `llm.test` | – | `{ok, detail, models?: string[]}` |
| `stats.get` | – | `Stats` |
| `professors.list` | `{query?, status?, offset?, limit?}` | `{items: Professor[], total}` |
| `drafts.update` | `{sheet, row, version, subject?, draft}` | `{professor}`. Refuses sent rows and a stale version (`conflict`) |
| `replies.list` | – | `{items: ReplyDraft[], version}` |
| `replies.update` | `{index, version, body, approved}` | `{version}` |
| `conversations.get` | – | `{html, modified}` |
| `commands.list` | – | `{commands: CommandSpec[]}`. Each CLI command, with safe fields only |
| `jobs.start` | `{command, options, confirmation?}` | `{job: Job}`. Live mail requires the exact `confirmation` text |
| `jobs.list` | – | `{jobs: Job[]}` |
| `jobs.log` | `{job_id, offset?}` | `{lines: string[], offset}` |
| `jobs.answer` | `{job_id, answer: "y"\|"n"}` | `{ok}`. Answers the `[Y/N]` prompt of the CLI |
| `jobs.cancel` | `{job_id}` | `{ok}`. Refused for live jobs during delivery |
| `dialog.none` | – | – (Tauri shows the file pickers, and gives the paths to `resume.import`) |

Events: `job.log {job_id, line}`, `job.status {job: Job}`, `job.prompt {job_id, text}`,
`auth.progress {stage, detail}`.

## Data layout

The data of each user is in `%LOCALAPPDATA%\Agnostos\users\<user_id>\`, with
`workspace\.env`, `workspace\output\` and `workspace\resume.*`. Only the engine writes the secrets in `.env`.
DPAPI encrypts the OAuth refresh tokens in `tokens.bin`. Alternatively, a user can point the app to an existing v2 checkout
(`settings.update {"_workspace": "C:\\path"}`). This keeps the existing outreach
data and the scheduled CLI tasks in operation.

## OAuth configuration

For desktop apps, client IDs are not secrets, but the repository does not contain them. The
engine reads `%LOCALAPPDATA%\Agnostos\oauth.json`:
```json
{"google": {"client_id": "...apps.googleusercontent.com", "client_secret": "..."},
 "github": {"client_id": "Iv1...."}}
```
If a provider is not configured, `auth.google`/`auth.github.start` return
`unavailable` with setup instructions. The UI then hides or disables the button.

## UI notes (frontend agent)

There are no changes to the contract. The engine and the shell must know these items, so that the UI operates correctly:

- **Extra settings keys** that the UI writes through `settings.update` (plain `.env` keys). Keep them and return them
  in `settings.get`, also if the CLI ignores them at this time: `TARGET_UNIVERSITIES` (separated by `;`),
  `SEND_WEEKDAYS` (`mon,tue,...`; default weekdays). The list also includes these existing keys:
  `DISCOVER_COUNTRIES`
  (ISO codes separated by commas, or `europe`), `GEOGRAPHY`, `POSITION`, `FOCUS_KEYWORDS` (interests joined by `;`),
  `CAN_SELF_FUND` (`true`/`false`), `SELF_FUND_NOTE`, `DAILY_SEND_CAP`, `SEND_DELAY_MIN/MAX`,
  `SEND_LOCAL_WINDOW` (`9-11` or empty), `LLM_PROVIDER`, `GROQ_API_KEY`/`OPENAI_API_KEY`,
  `DRAFT_MODEL`, `SMTP_*` and `IMAP_*`. The UI shows and edits `_workspace` in Settings → Workspace. Thus,
  `settings.get` must include it.
- The UI calls `email.test` / `llm.test` immediately after `settings.update`. Thus, they must read the new values.
- The `status` values of `professors.list` that the UI sends: `""` (all), `unsent`, `sent`, `replied`, `failed`
  (failed sends + bounces). The client identifies sent rows by `send_status` in `sent`/`review-sent`.
- When the user opens a job, the UI calls `jobs.log` with `offset: 0`. After that, live lines come from `job.log`
  events. `job.status` events must contain the full `Job` (including `prompt` when the status is `waiting_input`).
- For a `CommandSpec` with `live_field`, the UI shows that field in a red "Danger zone". When the field is on, the UI
  requires the user to type `confirmation` exactly (`SEND` if `confirmation` is missing). It gives the text to `jobs.start`.
  The UI shows other fields by `type`. It obeys `default`, `min`, `max`, `choices` and `help`.
- The UI shows `conversations.get.html` in `<iframe sandbox="" srcdoc>` (no scripts, no same-origin).
- While `auth.google` is pending, the UI shows the `auth.progress` `detail` below the Google button.
- **Shell (Tauri capabilities)**: the UI uses `core:event` listen (`engine://event`),
  `dialog:allow-open`, `opener:allow-open-url` (github.com/login/device, console.groq.com,
  platform.openai.com), and `getCurrentWebview().onDragDropEvent` for native resume drops (keep
  `dragDropEnabled` on). Vite dev server: `http://localhost:1420`, build output `app/dist`.
