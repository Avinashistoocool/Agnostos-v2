# Changelog

All notable changes to Agnostos are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/): MAJOR for breaking CLI/workbook
changes, MINOR for new commands or options, PATCH for fixes.

## [Unreleased]

## [2.2.0] - 2026-11-04

### Added
- Windows Python 3.15 support for the CLI without C++ Build Tools, with a
  wheel-only Windows CI job and Python 3.15 tests.
- A standalone Windows desktop reviewer for existing v2 workbooks,
  conversations and selectively approved reply drafts. Sending remains in
  the CLI; the packaged application contains no credentials or user data.

### Fixed
- Replace required PyYAML (no Windows 3.15 wheel) with a pure-Python YAML
  reader for scraping sources and include `tzdata` so recipient-local
  sending windows work in a fresh Windows virtual environment.
- IMAP reply scans reconnect after transient session loss; the first-email
  cap survives sender restarts; wrongly named reply greetings are blocked.
- Resume configuration errors identify a missing/placeholder path, directory,
  unsupported extension or missing `.env` dependency rather than failing
  later with misleading errors.

## [2.1.0] - 2026-11-01

### Added
- `agnostos --version`. The version is defined once in `outreach/__init__.py`.
- Docker image (`Dockerfile`, `compose.yaml`) and a release workflow that
  publishes a wheel, an sdist, a GitHub Release and `ghcr.io/avinashistoocool/agnostos`
  for every `v*` tag.
- Single-instance lock for live `send`, `resend` and `replies --send`. A
  scheduled task and a manual run can no longer mail the same people twice.
- `ddgs` (email lookup) is now a declared dependency, plus a `calendar` extra
  for the Google Calendar integration.

### Fixed
- `send` crashed with `BadZipFile` when another process was saving
  `professors.xlsx` at the same moment. Reads now retry, and saves are atomic
  (written to a temp file, then swapped in).
- `verify --repair` could hang forever on a stuck web search. Each search now
  has a hard deadline, and a working `yahoo` backend was added.
- Countdown timers wrote a line every second into piped logs (40 MB+). When
  output is not a terminal, they now update once a minute.
- `.env` is also read from the working directory, so pip and Docker installs
  pick it up.

## [2.0.0] - 2026-10-30

### Added
- `discover`: `--top-universities`, `--also-universities`, `--list-universities`.
- `verify`: `--only-missing`, arXiv/PDF address extraction, cross-site confirmation.
- `resend`: re-deliver the original email from a second account (`--prioritize-top`).
- `replies`: funding follow-ups, meeting requests with Google Calendar holds,
  thread-aware follow-ups, `--approve-all`, recipient-local send windows, and
  automatic CV attachment.
- `conversations` (HTML view of every thread) and `archive-sent` (IMAP Sent copies).
- `legacy`: letters to leading researchers in your field.
- `replace-failed`: swaps a bounced professor for a same-institution colleague.
- `FOCUS` / `FOCUS_KEYWORDS` filter, `CAN_SELF_FUND` guard, a live dashboard,
  and resend/reply counts in `stats`.
- Technical report, MkDocs site and citation metadata.

### Fixed
- Mass "invalid" results on Windows during `verify`.
- `run` never redrafts rows that were already sent.
- Wrong-person matches (given-name and country conflicts).

## [1.0.0] - 2026-10-13

- First public release: resume parsing, local matcher, OpenAlex enrichment,
  LLM drafting with de-slop pass, throttled SMTP sending, Excel round-trip.

[Unreleased]: https://github.com/Avinashistoocool/Agnostos-v2/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/Avinashistoocool/Agnostos-v2/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Avinashistoocool/Agnostos-v2/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Avinashistoocool/Agnostos-v2/releases/tag/v2.0.0
