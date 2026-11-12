# Changelog

This file records all important changes to Agnostos. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project uses
[Semantic Versioning](https://semver.org/): MAJOR for changes to the CLI/workbook that are not compatible,
MINOR for new commands or options, and PATCH for fixes.

## [Unreleased]

### Added
- A native PySide6 Windows application with guided controls for all v2 CLI
  commands. It also has local settings, review of first emails and reply drafts, job logs and
  progress. The existing CLI stays the internal engine, and it can still run
  scheduled automation.
- An offline Windows ZIP build with the packaged CLI, Qt widgets and discovery
  resources. It does not contain user credentials, workbooks or mail.

### Fixed
- Legacy live sends now require verified recipients in the focus. They also obey
  weekday/local windows, funding rules, a shared daily cap and the removal of duplicate addresses in each run.
  The desktop also rejects live-send limits of zero. It refuses raw flags that bypass safety in its packaged worker.

## [2.2.0] - 2026-11-04

### Added
- Windows Python 3.15 support for the CLI without C++ Build Tools. This includes a
  Windows CI job that uses only wheels, and Python 3.15 tests.
- A standalone Windows desktop reviewer for existing v2 workbooks,
  conversations and reply drafts that you approve one by one. Only the CLI sends mail.
  The packaged application contains no credentials or user data.

### Fixed
- The required PyYAML (no wheel for Windows 3.15) is replaced with a YAML
  reader in pure Python for scraping sources. The build now includes `tzdata`, so that recipient-local
  send windows work in a new Windows virtual environment.
- IMAP reply scans connect again after a temporary loss of the session. The cap on first emails
  stays correct after the sender starts again. The tool blocks reply greetings with an incorrect name.
- Resume configuration errors now identify the cause: a missing/placeholder path, a directory,
  an extension that is not supported or a missing `.env` dependency. Before, the tool failed
  later with errors that gave incorrect information.

## [2.1.0] - 2026-11-01

### Added
- `agnostos --version`. The version is defined one time, in `outreach/__init__.py`.
- A Docker image (`Dockerfile`, `compose.yaml`) and a release workflow. For each `v*` tag, the workflow
  publishes a wheel, an sdist, a GitHub Release and `ghcr.io/avinashistoocool/agnostos`.
- A single-instance lock for live `send`, `resend` and `replies --send`. A
  scheduled task and a manual run can no longer send email to the same people two times.
- `ddgs` (email lookup) is now a declared dependency. There is also a `calendar` extra
  for the Google Calendar integration.

### Fixed
- `send` stopped with `BadZipFile` when a different process saved
  `professors.xlsx` at the same time. Now, reads try again, and saves are atomic
  (the tool writes to a temporary file, then replaces the workbook).
- `verify --repair` could stop permanently on a web search that did not respond. Now each search
  has a hard time limit. There is also a new `yahoo` backend that works.
- Countdown timers wrote a line each second into piped logs (40 MB+). Now, when
  the output is not a terminal, they write one time each minute.
- The tool also reads `.env` from the working directory. Thus, pip and Docker installations
  find it.

## [2.0.0] - 2026-10-30

### Added
- `discover`: `--top-universities`, `--also-universities`, `--list-universities`.
- `verify`: `--only-missing`, extraction of addresses from arXiv/PDF, confirmation across sites.
- `resend`: sends the original email again from a second account (`--prioritize-top`).
- `replies`: funding follow-ups, meeting requests with Google Calendar holds,
  follow-ups that know the thread, `--approve-all`, recipient-local send windows, and
  automatic CV attachment.
- `conversations` (HTML view of each thread) and `archive-sent` (IMAP Sent copies).
- `legacy`: letters to leading researchers in your field.
- `replace-failed`: replaces a bounced professor with a colleague from the same institution.
- The `FOCUS` / `FOCUS_KEYWORDS` filter, the `CAN_SELF_FUND` guard, a live dashboard,
  and resend/reply counts in `stats`.
- Technical report, MkDocs site and citation metadata.

### Fixed
- Many incorrect "invalid" results on Windows during `verify`.
- `run` never writes new drafts for rows that the tool already sent.
- Matches with the wrong person (conflicts of given name and country).

## [1.0.0] - 2026-10-13

- First public release: resume parsing, local matcher, OpenAlex enrichment,
  LLM drafts with a de-slop pass, SMTP sends at controlled intervals, Excel round trip.

[Unreleased]: https://github.com/Avinashistoocool/Agnostos-v2/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/Avinashistoocool/Agnostos-v2/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Avinashistoocool/Agnostos-v2/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Avinashistoocool/Agnostos-v2/releases/tag/v2.0.0
