# Agnostos: AI research internship outreach

![Agnostos — research outreach, done honestly](docs/assets/agnostos-banner.png)

[![tests](https://github.com/Avinashistoocool/Agnostos-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/Avinashistoocool/Agnostos-v2/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Avinashistoocool/Agnostos-v2)](https://github.com/Avinashistoocool/Agnostos-v2/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Agnostos** is a free, open-source tool that helps students get research internships. It does these tasks:

- It finds professors whose recent papers match your resume.
- It writes one honest cold email for each professor.
- It sends the emails slowly from your own inbox, during the working hours of each professor.
- It writes draft replies to the answers.

> Hosted web version: [Agnostos web app](https://github.com/Avinashistoocool/Agnostos-v3) · Guides: [Windows](docs/install-windows.md) · [macOS](docs/install-macos.md) · [Linux](docs/install-linux.md) · [FAQ](docs/faq.md)

Agnostos is an autonomous pipeline for research internship outreach, and it uses few tokens. It does these tasks:

1. It compares your CV with possible supervisors.
2. It gets their recent publications.
3. It calculates the probability of acceptance.
4. It writes a specific cold email for each supervisor, without generic LLM text.
5. It limits the speed of outbound SMTP delivery.

```
                 discover (OpenAlex, free) ─► verify --repair (web lookup, free)
                                   │
resume.pdf ─┐                      ▼
            ├─► local NLP filter (free) ─► [Y/N] cost gate ─► LLM ─► .xlsx ─► SMTP
targets ────┘        ▲ OpenAlex enrichment (free)            recheck ─┘
```

Give the tool your CV and a spreadsheet of professors. Then it does these steps:

1. It reads your resume.
2. It sorts the list by match with your resume, at no cost.
3. It finds the recent papers of each professor.
4. It writes a specific email for each person.
5. It removes the signs of AI text from the emails.
6. It sends the emails on a schedule that looks human.

During these steps, it writes each draft and each status back into your spreadsheet.

**It costs nothing.** The default provider is [Groq](https://console.groq.com/keys). The free tier of Groq is sufficient for a full run. You can also use OpenAI, or any gateway that is compatible with OpenAI.

**Documentation:** [avinashistoocool.github.io/Agnostos-v2](https://avinashistoocool.github.io/Agnostos-v2/) · [Technical report (PDF)](docs/Agnostos_Technical_Report.pdf). The report explains the architecture and each scoring rule (local matcher, discovery ranking, cost estimate, AI-tell score, address confidence, send windows). The LaTeX source is in [`docs/Agnostos_Technical_Report.tex`](docs/Agnostos_Technical_Report.tex).

---

## Native Windows desktop app (existing v2 workspace)

The standalone **PySide6/Qt widget application** includes **every public CLI command** under CLI
tools: profile, models, run (list/scrape), discover, verify, recheck, send,
resend, stats, check-replies, replies, conversations, archive-sent, legacy
(also legacy-researchers), replace-failed, calendar-auth and tls-check. The
application runs the **same v2 CLI code in an isolated subprocess**. It does
not use a separate v3 server or database. When you start the application for
the first time, select the folder of your existing repository. If the
application finds the current checkout, it suggests that folder. The
application saves only the selected path, in
`%LOCALAPPDATA%\Agnostos-v2-Review\workspace.json`.

The application uses these files:

- The dashboard reads `output\professors.xlsx`.
- The saved conversations show the text of `output\conversations.html`. The application does not run the embedded script of that file.
- The reply review edits the individual unsent bodies and approvals in `output\reply_queue.json`.
- The Setup tab reads `.env`, but does not change it.

The application keeps your UI overrides for each workspace in AppData. The UI
masks the secrets, and Windows DPAPI encrypts them. The CLI subprocess gets
these overrides. It uses the selected workspace as its working directory and
writes its usual output there. Job logs and job status are in AppData. After a
restart, the application shows an unfinished job as detached or interrupted.
It never runs that job again automatically.

The bundled subprocess validates each recorded command and its options again
before it starts the CLI. The desktop executable does not accept arbitrary raw
`--cli` flags.

**Live SMTP is off by default.** For each live GUI action, you must do these steps:

1. Select Live/Review.
2. Type the exact confirmation for that command.
3. Answer the visible `[Y/N]` prompt of the CLI in Jobs.

The GUI does not show `--yes`, blanket approval, no-focus, allow-unverified,
weekends, or send/resend bypasses. The GUI applies a recipient-local window,
the focus/robots rules, weekday defaults, paced delays and a daily cap of
40 or less for each job. Legacy live sending has more CLI guards: verified
addresses, focus, recipient-local weekdays/hours and a shared daily cap. The
GUI also requires the typed confirmation and the [Y/N] prompt of the CLI.

You cannot cancel a live job during delivery. This prevents a send that has
no record. You can cancel a job that is not live. If you cancel it during a
workbook write, examine the output.

A v2 CLI that runs on a different schedule can also send an approved unsent
reply later. Queue writes are atomic, and the application coordinates them
with the CLI. The application rejects edits that are stale or that occur when
the queue is busy. The First-email drafts tab edits individual **unsent**
workbook drafts. It uses a revision check and an atomic save, and it never
edits a sent row. If a CLI job is active or the workbook changed, reload
before you try again. If you select an older checkout that does not have
coordinated v2 queue support, you can view it, but you cannot edit reply
drafts.

This is a native Windows window (no WebView2 or localhost HTTP server).
Download the full distribution. Start `Agnostos-v2-Desktop.exe` next to its
`_internal` folder. To build your own ZIP from a Windows checkout with Python
3.13, use these commands:

```powershell
.\build-desktop-review.ps1 -Python "C:\Path\To\Python313\python.exe"
.\dist\Agnostos-v2-Desktop\Agnostos-v2-Desktop.exe --health-check
.\dist\Agnostos-v2-Desktop\Agnostos-v2-Desktop.exe
python tests\native_desktop_test.py
python tests\full_desktop_contract_test.py
.\tests\check_desktop_review_package.ps1
```

Output: `dist\Agnostos-v2-Desktop.zip`. The ZIP contains the executable folder
and headless Chromium. Chromium is for CLI directory scraping, *not* for the GUI.
At this time, this full native build is **local only**. GitHub access must be
available again, and these changes must be on `main`. Then the **Native Windows desktop**
GitHub Actions run can also supply this ZIP as an artifact for download (Actions
→ workflow run → Artifacts). Extract the inner ZIP from the downloaded artifact.
Artifacts expire after 14 days. They are not installer releases.
The native GUI uses Qt widgets and Windows system fonts, thus you can view data
offline. Discovery, models, mail and Calendar authorization require internet.
There is **no listening socket**. The ZIP contains only the executable,
Qt, CLI code, the public `sources.yaml` and the dependencies. It does not
contain `.env`, mailbox keys, workbooks, conversation HTML, the reply queue or
other user data.
The ZIP includes [third-party license notices](docs/licenses/THIRD_PARTY_NOTICES.md)
and the applicable Qt LGPL/GPL terms.
The application creates **no new v3 database**. It runs only while the PC is on.
Existing scheduled CLI tasks stay independent of the GUI.

## Quick start

```bash
git clone https://github.com/Avinashistoocool/Agnostos-v2
cd Agnostos-v2
pip install -r requirements.txt

cp .env.example .env                       # Windows: copy .env.example .env
```

Open `.env` and fill in only section 1:

- the path of your resume
- your target `.xlsx`
- a free [Groq key](https://console.groq.com/keys)
- your SMTP details.

On a different computer, set `RESUME_PATH` to **the actual resume file on that computer**.
Do not use the absolute path of a different person. Use a real PDF or DOCX
file, not an image or a folder with a changed name. In Windows Explorer, turn
on **File name extensions**. Then make sure that the file does not have a
hidden extra extension.
Install the dependencies on that computer also, with
`python -m pip install -r requirements.txt`. The CLI needs `python-dotenv` to
read `.env`. Run the CLI from this checkout. The CLI reads its own `.env`, not a
`.env` from an unrelated folder.

Then run these commands:

```bash
python -m outreach.cli profile             # sanity-check resume parsing
python -m outreach.cli models              # see what your key can run
python -m outreach.cli run --mode list     # score + draft into your xlsx
python -m outreach.cli send --dry-run      # preview the emails
python -m outreach.cli send --live --top 10 --local-window 9-11
python -m outreach.cli check-replies      # who answered?
python -m outreach.cli stats              # funnel: drafted / sent / replied / skipped (and why)
python -m outreach.cli replies            # read each thread, draft follow-ups -> output/reply_queue.json
python -m outreach.cli replies --send --live   # send the ones marked "approved": true
python -m outreach.cli replies --send --approve-all   # approve every unsent draft, then dry-run send
```

`stats` reads the workbook, also when the workbook is open in Excel. Each `send` adds each attempt to `output/send_log.csv`. Thus, the history stays available after later edits to the sheet.

Certificate errors (`CERTIFICATE_VERIFY_FAILED ... _ssl.c:...`) are frequent with python.org Python on macOS. To fix them, run `pip install -U truststore certifi`. Then run `python -m outreach.cli tls-check`. If you are behind a proxy that inspects TLS, set `SSL_CERT_FILE` to the root certificate of that proxy.

Step-by-step setup guides for each operating system: [Windows](docs/install-windows.md) · [macOS](docs/install-macos.md) · [Linux](docs/install-linux.md) · Questions: [FAQ](docs/faq.md) · Problems: [Diagnostics](docs/diagnostics.md)

You need SMTP only for the last step. You can write all the drafts without it. Mode A scraping is optional. The first section of `.env.example` is the only required section. All other settings have default values that work.

If you do not have a list of professors, you can make one from your research topic. You do not have to collect the names manually:

```bash
python -m outreach.cli discover --count 1000 --batches 4 --query "machine learning particle physics; geometric deep learning"
python -m outreach.cli verify --xlsx output/professors.xlsx --repair --apply
```

See [`discover`](#discover--build-a-target-list-of-n-professors-in-batches) below.

### Install a release / deploy

Each tagged release is on the [Releases page](https://github.com/Avinashistoocool/Agnostos-v2/releases) (wheel and sdist). Each tagged release is also on GHCR as a Docker image. [CHANGELOG.md](CHANGELOG.md) lists the changes.

```bash
pip install "agnostos[calendar] @ git+https://github.com/Avinashistoocool/Agnostos-v2@v2.1.0"
agnostos --version

# or run it in Docker. Put .env, the resume and the workbook in ./data
# (in data/.env, set RESUME_PATH=/data/... and TARGET_XLSX=/data/...)
docker run --rm -it --env-file data/.env -v "$PWD/data:/data" ghcr.io/avinashistoocool/agnostos stats
docker compose up -d        # sender + reply checker, weekdays, recipient-local 9-17
```

Live senders (`send --live`, `resend --live`, `replies --send --live`) hold a lock. Thus, a scheduled task and a manual run can never send email to the same people two times. For the release procedure, see [RELEASING.md](RELEASING.md).

### Your target spreadsheet

You can use any `.xlsx` file. The tool finds the header row automatically and maps about 25 usual column names. Thus, you usually need only these columns:

| Professor Name | Email | Institution | Research Area |
|---|---|---|---|
| Prof Jane Smith | jane.smith@uni.de | TU Munich | Graph neural networks for jet tagging |

If the workbook has the columns `Country`, `Department`, `Fit Reason`, `Funding`, `Eligibility` and `Application Route`, the tool uses them. The tool puts each unknown column into a notes field, and the model also reads that field. Research descriptions with more detail give better drafts.

---

## Commands

### `profile` — verify resume extraction

```bash
python -m outreach.cli profile [--resume PATH]
```

This command shows the name, programme, interests, skills and projects. It writes `output/profile.json`. It also shows the exact profile block that the tool puts in the LLM system prompt. Run this command first, because all the subsequent steps use its result.

### `models` — list what your key can actually reach

```bash
python -m outreach.cli models [--provider groq|openai]
```

This command sends a live query to the provider. It marks your current `DRAFT_MODEL` and shows the prices, if they are known. The catalogues of the providers change frequently. Trust the output of this command more than a table in a README, including the table below.

### `run` — the main pipeline

```bash
# Mode B (default): process your existing target list in place
python -m outreach.cli run --mode list

# Mode A: discover professors by scraping faculty directories
python -m outreach.cli run --mode scrape --sources sources.yaml
```

| Flag | Purpose |
|---|---|
| `--mode list\|scrape` | Mode B (existing xlsx) or Mode A (discovery) |
| `--xlsx PATH` | Target workbook (default: `TARGET_XLSX` from `.env`) |
| `--sheet NAME` | Use only one sheet |
| `--sources PATH` | YAML/JSON list of directories for Mode A |
| `--output PATH` | Write a new workbook, and do not edit the workbook in place |
| `--max-professors N` | Maximum number of professors that go to the LLM |
| `--min-score F` | Local match threshold, 0–1 (default `0.25`) |
| `--budget USD` | Hard limit of cost for the run |
| `--provider groq\|openai` | LLM provider (default: `LLM_PROVIDER` from `.env`) |
| `--model NAME` | Use a different model for drafts |
| `--no-enrich` | Skip the OpenAlex publication lookups (same as `--skip enrich`) |
| `--skip STEPS` | Skip optional steps, separated by commas: `enrich` (OpenAlex), `filter` (local score threshold; rows still need an email, and the `--max-professors` limit applies), `gate` (same as `--yes`). For example, `--skip enrich,filter` |
| `--no-profile-hop` | Mode A: do not open the profile pages of individual persons to find emails |
| `--no-backup` | Do not make a backup of the workbook before you edit it |
| `--yes` | Skip the `[Y/N]` cost gate (for scripts) |

### `discover` — build a target list of N professors, in batches

```bash
python -m outreach.cli discover --count 1000 --batches 4 \
    --query "machine learning particle physics; geometric deep learning; computational high energy physics; physics-informed machine learning"
python -m outreach.cli discover --count 200 --countries dach,nordics --since 2023
```

This command makes a large, sorted list of professors. You do not have to name a university. The command does these steps:

1. It searches the **paper** index of OpenAlex for your topics.
2. It keeps only recent papers from academic institutions in the selected countries.
3. It records the **first and last authors**, because these people lead the work.

The command discards papers with more than about 15 authors. A collaboration paper with 2,000 authors names all of them, and it does not tell you who works on which subject.

**How batches work.** The command divides `--count` equally between `--batches` (1000 / 4 = 250 each). Each batch uses one topic from `--query` (separate the topics with `;`). If there are fewer topics than batches, the command uses the topics again. A topic that is used again *continues from the page where the previous batch stopped*. Thus, it finds new people, not the same people. A batch reads pages until one of these conditions occurs:

- It has its quota of senior researchers.
- Its topic has no more relevant papers.
- It gets to `--max-pages`.

The next batch gets the shortfall.

- **The command never adds a person two times.** This applies across batches. It also applies to all persons already in the output workbook (compared by OpenAlex id, and by name without accents and word order).
- **The command saves each batch immediately when the batch is complete.** It keeps the progress in `<output>.batches.json`. If the run stops, run the same command again. The command continues at the first incomplete batch. `--fresh` makes a new plan (see below for the options that also do this).
- **The command removes results that are not on the topic.** A free-text search matches words, not meaning. For example, "geometric deep learning" also finds papers about tooth geometry. The best results of each topic define the broad fields of that topic. The command ignores papers from other fields, and papers far below the top relevance. The code contains no fixed list of subjects.

| Flag | Purpose |
|---|---|
| `--count N` | Total number of professors to find (default `DISCOVER_COUNT`, `1000`) |
| `--batches K` | Number of batches (default `DISCOVER_BATCHES`, `4`) |
| `--query "a; b; c"` | Topics, one for each batch, used again in rotation (default `DISCOVER_QUERIES`, then the interests from your resume) |
| `--countries` | `europe`, `eu`, `dach`, `nordics`, `uk`, `usa`, `northamerica`, `asia`, `anz`, or ISO codes such as `de,ch,gb` |
| `--since YEAR` | Count only papers from this year and later (default `2021`) |
| `--max-pages N` | Maximum number of pages for each batch, 100 papers for each page (default `40`) |
| `--min-h-index N` | Seniority gate (default `8`). It removes first-year PhD students |
| `--min-works N` | Minimum number of publications (default `20`) |
| `--output PATH` | Workbook that gets the new rows (default `output/professors.xlsx`) |
| `--verify-emails` | Find the current address of each person when each batch is complete (slow; see `verify`) |
| `--workers N` | Parallel email lookups (default `VERIFY_WORKERS`, `4`) |
| `--exclude XLSX` | Skip all persons already in this workbook (you can use it more than one time; a missing path shows a warning) |
| `--resume PATH` | Resume that supplies the default topics when you do not use `--query` |
| `--fresh` | Discard the saved progress of the batches |
| `--top-universities N` | Use only people at the N best universities of the region, and prefer the universities with a higher rank (default `DISCOVER_TOP_UNIVERSITIES`, `0` = off) |
| `--prestige-weight W` | With `--top-universities`: `0` = topic fit only, `1` = balanced (default), `3` = mostly prestige |
| `--list-universities` | Show the top universities of the region, then stop |

**Specified universities in all regions (for example, the Ivy League).** `--also-universities` accepts a list separated by `;`. It works without `--top-universities`. Use `--countries usa` (or the applicable region), so that the command does not remove papers from those universities. If you want more fields than physics, also use a wider `FOCUS_KEYWORDS`:

```bash
python -m outreach.cli discover --count 700 --batches 14 --countries usa --top-universities 0 \
    --also-universities "Harvard University; Yale University; Princeton University; Columbia University; University of Pennsylvania; Brown University; Cornell University; Dartmouth College; Massachusetts Institute of Technology; Stanford University; California Institute of Technology" \
    --query "machine learning particle physics; reinforcement learning; robotics motion planning; computational mechanics"
```

**Use the best universities.** `--top-universities N` sorts the universities in `--countries` by their number of papers with many citations (50+ citations) since `--since`. This approximation agrees closely with the usual league tables (for `dach`: ETH Zurich, TUM, LMU, Zurich, Heidelberg, Bern, EPFL...). It does not need a fixed list. Then the discovery searches only papers from those universities. It sorts people by topic fit, plus a prestige bonus for the rank of their university. Examine the list first:

```bash
python -m outreach.cli discover --list-universities --countries europe --top-universities 30
python -m outreach.cli discover --count 200 --countries europe --top-universities 30 --prestige-weight 2
```

If you change `--top-universities`, the command starts a new batch plan. If you change `--prestige-weight`, it does not.

The command saves the progress in `<output>.batches.json` after each batch. Thus, if you run the same command again, it continues. These changes start a new plan: the topics, the count, the batches, the countries, `--since`, `--min-h-index` or `--min-works`. You can change `--max-pages` and `--exclude`, and you keep the progress. If the output workbook is open in Excel when a batch is complete, the tool waits until you close it. It does not discard the batch.

You do not need an API key, and the command does not scrape. OpenAlex is a free public index. For large runs, set `OPENALEX_MAILTO` or `OPENALEX_API_KEY` to get a faster and more reliable quota. Discovered rows have a name, institution, country, research summary and OpenAlex id. They have **no email address**. Use `verify --repair` to find the addresses.

The full procedure:

```bash
python -m outreach.cli discover --count 1000 --batches 4 --query "..."
python -m outreach.cli verify --xlsx output/professors.xlsx --repair --apply --workers 6
python -m outreach.cli run --mode list --xlsx output/professors.xlsx
python -m outreach.cli send --live --top 10 --local-window 9-11
python -m outreach.cli check-replies      # who answered?
python -m outreach.cli stats
```

### `recheck` — is everyone still there, and is every address current?

```bash
python -m outreach.cli recheck --dry-run            # report only
python -m outreach.cli recheck --apply              # also replace stale addresses
python -m outreach.cli recheck --professors-only    # fast: OpenAlex only, no web search
```

For each row that did not get an email yet, the command gets the OpenAlex author record of the person. Then it writes one of these values in the **Profile Status** column:

- `active`
- `moved`: the person now publishes from a different institution. OpenAlex resolves acronyms such as KIT, EPFL or CERN; the code does not use a table.
- `inactive`: no papers for 3 or more years.
- `not found`: no author record matches both the name and the listed institution.

If a lookup fails (network error, rate limit), the previous status does not change. If the Institution cell or the OpenAlex ID cell is blank, the command fills it from the record. It never overwrites a cell that has a value. Then it runs the `verify --repair` email lookup again for the same rows.

| Flag | Purpose |
|---|---|
| `--apply` | Replace missing or failed addresses with the address found online |
| `--professors-only` / `--emails-only` | Do only one half of the check |
| `--include-sent` | Also check rows that have the status `sent`/`review-sent` (the command skips them by default) |
| `--dry-run` | Only show a report; never change the workbook |
| `--xlsx`, `--sheet`, `--workers`, `--no-dns`, `--no-backup` | Same as in `verify` |

### `verify` — check and repair email addresses

```bash
python -m outreach.cli verify --dry-run                  # report only
python -m outreach.cli verify --repair --apply           # find and write correct addresses
```

The command checks each address for these items:

- the syntax
- the domain: does it accept mail (MX/A records)?
- the local part: does it agree with the name of the professor?

With `--repair`, the command also searches the web for that person. It opens the pages of the person, and it extracts the address that *the person* publishes. The command trusts an address only when the name matches **and** the page with the address is on the same domain. The tool never guesses the spelling of the domain of a university, because such guesses give wrong addresses with high confidence.

| Flag | Purpose |
|---|---|
| `--xlsx PATH` / `--sheet NAME` | The workbook and the sheet to check |
| `--top N` | Check only the N rows with the highest probability (by `Probability of Acceptance`, or by a `Probability` column if that column is not available) |
| `--repair` | Search the web and read profile pages to find the real address |
| `--apply` | Write the found address into the Email column when the current address is missing or not `ok`. If the current address passes, the command keeps it and puts the other address in `Suggested Email` |
| `--include-sent` | Also check rows that have the status sent (the command skips them by default) |
| `--probe-smtp` | Ask the mail server if the mailbox exists (for information only) |
| `--no-dns` | Skip MX/A lookups |
| `--workers N` | Parallel lookups (default `VERIFY_WORKERS`, `4`) |
| `--dry-run` | Only show a report; never change the workbook |

Each row gets the result `ok`, `suspect` or `invalid`, with a confidence percentage. It also gets a note that tells where the command found the address. The command keeps the results in `output/email_lookup_cache.json`, thus a second run costs little. Repair is slow: 20–40 seconds for each professor, because it does real web searches. `--workers` runs more than one search at the same time (1,000 professors with 4 workers take about 2–3 hours). Thus, run it one time on a newly discovered list, not before each send.

### `send` — dispatch

```bash
python -m outreach.cli send --dry-run --preview 3
python -m outreach.cli send --live --top 10 --min-probability 60
```

| Flag | Purpose |
|---|---|
| `--live` | Send the emails (the default is a dry run) |
| `--dry-run` | Explicit dry run (the default) |
| `--review` | Send each draft to yourself (`SMTP_FROM`), not to the professor |
| `--review-to ADDR` | Same as `--review`, but to a different address |
| `--export` | Write `.eml` files, and do not send (`--export-dir DIR`, default `output/drafts`) |
| `--top N` | Send email only to the **N professors with the highest probability** |
| `--limit N` | Maximum number of real sends in this run (replaces `DAILY_SEND_CAP`) |
| `--min-probability N` | Send only to rows with a score of N% or more |
| `--allow-unverified` | Also send to rows that have the Email Status `invalid` |
| `--delay-min/--delay-max S` | Random interval between sends |
| `--resend` | Send again to rows that have the status sent |
| `--preview N` | Number of full drafts to show in a dry run |
| `--at TIME` | Wait (with a countdown), then start at `HH:MM` or `YYYY-MM-DD HH:MM`, in your local time |
| `--local-window H-H` | Send only in the local hours of the recipient, for example `9-11` (from the Country column; default `SEND_LOCAL_WINDOW`; `off` disables it) |
| `--wait` | With a local window, keep the command active until the window of each row opens. Without it, the command holds the row |
| `--weekends` | Permit the local window on Saturday/Sunday (by default, only weekdays) |
| `--yes` | Skip the `[Y/N]` prompt, for Task Scheduler / cron |
| `--xlsx PATH` / `--sheet NAME` / `--resume PATH` | Workbook, sheet and resume (for the signature) |

**Select the number of emails to send.** You can use these controls together:

- `--top N` sorts the rows that have drafts by acceptance probability, and sends email to the best N. Usually, this is the control that you need.
- `--min-probability N` sets a minimum quality, not a count.
- `--limit N` sets the maximum number of emails that this run sends. The command applies it after the `--top` sort.
- `DAILY_SEND_CAP` in `.env` is the default for `--limit`. The code limits cold first emails (`send`, `resend`, `legacy`) to 40 each day, also if `.env` or `--limit` asks for more.

**Persons who never get a cold email.** `send`, `resend` and `legacy` skip these addresses, and write the reason in the log:

- An address that bounced on one of the two accounts (`Reply Status` that starts with "bounced", bounce records in `send_log.csv`, `output/FAILURES.json`; reason `skipped: bounced before`).
- Persons and domains in `output/no_cold_email.json`.
- Student, alumni and shared mailboxes (`@postgrad.`, `@studenti.`, `@g.harvard.edu`, `name.20@ucl.ac.uk`, `lehre-`, `pec`).
- Addresses without the first initial plus the surname.
- `suspect` addresses (unless you use `--allow-unverified`).
- Drafts with the flag `REJECTED DRAFT`.
- Each institution domain that already got `MAX_PER_DOMAIN_WEEK` (3) cold emails in the last 7 days.

The command skips rows that have the status `sent` automatically. Thus, you can safely continue an interrupted run. Dry runs never stop a subsequent real send.

**Schedules.** Emails get the best results in the middle of the morning, in the time zone of the professor.

```bash
# Start at 12:30 IST (09:00 CEST); only mail people for whom it is 9-11 locally
python -m outreach.cli send --live --top 20 --at 12:30 --local-window 9-11
# Same, but keep running until every row's window opens (e.g. Finland, then UK)
python -m outreach.cli send --live --top 20 --local-window 9-11 --wait
```

The command does not change rows outside their window. A subsequent run sends them. The terminal must stay open and the PC must stay awake. To run the command automatically on each weekday, register a Windows scheduled task:

```powershell
schtasks /Create /TN AgnostosSend /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 12:30 `
  /TR "cmd /c cd /d C:\path\to\Agnostos-v2 && python -m outreach.cli send --live --yes --top 20 --local-window 9-11 --wait >> output\send.log 2>&1"
```

Each successful send also keeps its `Message ID`. `check-replies` uses it to find the answers.

**Local Windows recovery setup.** This workstation also uses the tasks
`Agnostos IITD sender` and `Agnostos Gmail legacy sender`. These tasks use the
local scripts `output\run_iitd_loop.ps1` and `output\run_gmail_loop.ps1`.
They start at login. If they are not active, they try again each hour. They
have no execution timeout. Each loop has a mutex that prevents duplicate
instances of the loop.
The weekday launcher uses the same scripts. It must not start identical
Gmail resends. The Gmail loop sends only approved legacy/CERN letters.
These are local operational files. A clone of the repository does not install them.
The PC must stay awake, online and signed in. All limits still apply: daily,
domain and recipient-local window. `MAX_PER_DOMAIN_WEEK=3` also limits
`cern.ch` to three cold emails in each rolling week, not three for each group.

**Deferred address verification.** The `send`, `resend` and `legacy --send`
paths do not do DNS probes or web searches. Unless you use
`send --allow-unverified`, the command skips these recipients:

- recipients without `Email Status = ok`
- missing addresses
- recipients that fail the identity check.

The command records each skipped recipient one time in
`output\verification_queue.json`. These recipients do not use delivery slots.
The command continues to send to verified recipients. Use separate commands
for legacy discovery/drafting and for legacy sending.

Later, run the verification queue as a separate step:

```powershell
python -m outreach.cli verify --deferred --dry-run
python -m outreach.cli verify --deferred --repair --apply --top 20
```

The preview does no network requests and no workbook writes. The second command
checks the addresses in the queue and updates their source workbook. If a
sender uses a workbook at that time, the command postpones that workbook. It
does not change it at the same time. The command does not do a completed check
again, unless the check needs review and you use `--repair`. The command does
not overwrite rows that changed or rows that have the status sent. If a legacy
address changes, the command removes its approval, so that you can review the
new recipient. Verification never sends mail.

### `check-replies` — who answered

```bash
python -m outreach.cli check-replies            # update Reply Status
python -m outreach.cli check-replies --dry-run  # report only
```

The command does these steps:

1. It logs in to your mailbox over IMAP. The access is read-only, and the command does not mark messages as read.
2. In `IMAP_FOLDERS`, it looks for mail from each professor with the status `sent`, or mail in the thread of the stored Message ID.
3. It classifies the mail as `replied`, `auto-reply` (out-of-office) or `bounced`.

The results go to **Reply Status** (for example, `replied 2026-10-16 14:02`). The command also writes a `[reply] subject | first lines` note in **Follow-up Notes**. It never overwrites notes that you typed. The default `IMAP_HOST` is `SMTP_HOST`, with `smtp.` changed to `imap.`. The login uses `SMTP_USER`/`SMTP_PASSWORD` again.

### `replies` — draft and send follow-ups

```bash
python -m outreach.cli replies                              # draft follow-ups -> output/reply_queue.json
python -m outreach.cli replies --approve-all                # approve every unsent reply/thank draft
python -m outreach.cli replies --send                       # dry run of approved drafts
python -m outreach.cli replies --send --live                 # really send approved drafts
python -m outreach.cli replies --send --live --approve-all  # approve everything and send in one go
python -m outreach.cli replies --send --live --local-window 9-17 --wait  # send in each professor's working hours
```

`--local-window`, `--wait` and `--weekends` work as they do for `send`. The time zone of each reply comes from the Country column of the workbook. If that column is empty, the time zone comes from the country TLD of the email (for example, `.es`). `SEND_LOCAL_WINDOW` in `.env` is the default, and `--local-window off` disables it. The command saves sent replies to the queue immediately. Thus, if you stop a `--wait` run, it never sends a reply again.

Review or edit the bodies in `output/reply_queue.json` before you send them. To approve items one by one, set `"approved": true` for each item. `--approve-all` approves each draft in the queue that agrees with these conditions:

- It has a body.
- It is not sent.
- Its action is not `none`.

This includes drafts from previous runs. `--redraft` writes the drafts in the queue again.

If a reply says that something is attached (for example, "I've attached my CV"), the command automatically attaches the files in `ATTACHMENTS`. The send log then shows `[attached: ...]`. If that file is missing, the reply fails. It does not go out without the promised CV. The command sends replies that do not mention an attachment without attachments.

If drafts fail with `403 ... model is not currently available upstream`, your provider does not supply that model any more. Run `python -m outreach.cli models`. Then set `DRAFT_MODEL` / `SCORE_MODEL` in `.env` to a model from the list.


### Funding follow-ups and meeting requests

A professor can say that they cannot fund you, or that they can pay only a part. In that case, `replies` does more than a thank-you. It writes a reply that keeps the possibility open: partial support, a remote project, a shorter visit, or a joint fellowship application. If the professor then does not answer, each `replies` run writes up to `FUNDING_FOLLOWUPS` (default 2) more follow-ups. The command sends them only after `FOLLOWUP_GAP_DAYS` (default 2) without an answer. When the professor writes back, the follow-ups stop.

**Meeting requests.** Your second message in a thread always asks for a short call (`MEET_MINUTES`, default 20). Each funding follow-up also asks for a call. Each request gives three time slots on different weekdays. Each slot is in the `MEET_THEIR_HOURS` of the professor and in your own `MEET_MY_HOURS` (in `MEET_MY_TZ`). The command never gives the same slot to two professors at the same time. When Google Calendar is connected, the slots also avoid times when you are busy. When the email goes out, the command adds each proposed slot to your calendar as a tentative "HOLD". When the professor selects a time, delete the other holds.

**Google Calendar (one-time setup).** Follow **[the calendar guide](docs/calendar.md)**. The guide tells you how to do these tasks:

- Make the Cloud project.
- Set the app to *External / Testing*. This prevents the frequent error `Error 403: org_internal`.
- Download `credentials.json`.
- Run `python -m outreach.cli calendar-auth`.
- Change accounts.
- Find and fix problems.

Without this setup, the meeting requests still go out. The command skips only the calendar check and the holds.

### `program-reminders`: internship deadline reminders

```bash
python -m outreach.cli program-reminders [--dry-run] [--calendar] [--now YYYY-MM-DD] [--programs PATH]
```

This command reads `output/programs/internship_programs.json` (CERN, EPFL, ITER, ...). It sends reminders only to the two fixed addresses of the owner. The mail goes out from the personal Gmail account (`RESEND_SMTP_*`).

- **Welcome digest.** The first run sends one digest that lists each programme, sorted by deadline.
- **Weekly digest.** After that, a digest goes out one time in each ISO week (usually on Monday). It includes all items with a deadline in the next 60 days.
- **Milestone reminders.** You get an email at these times: when applications open; 21 days before the deadline if `referees_needed > 0` ("ask referees now"); and 30/14/7/3/1 days before each deadline. Each email includes the checklist of documents, the link and the path of the tailored CV. The command looks for the CV first in `output/programs/cvs/<id>.pdf`, then in `Dynamic-CV/program_cvs/CV_<id>.pdf`.
- **Idempotency.** `output/programs/reminders_sent.json` records each (programme, milestone) pair. The command sends each reminder one time. If runs did not occur, you get only the most recent missed milestone. The command marks older milestones as "superseded".
- **Null deadlines.** Programmes without a deadline are only in the digest.
- **Phone notifications.** With `--calendar`, the command makes Google Calendar events. It makes an all-day event on each deadline, and a 09:00 IST event on each milestone day. All events have popup and email reminders. The Calendar app on your phone then tells you. The command keeps the event ids in `output/programs/calendar_events.json`. Thus, it updates changed events and does not make duplicates. If the token in `output/gcal_token.json` expired, run `python -m outreach.cli calendar-auth` again. Email continues to go out during this time.
- **Optional SMS.** To also send a text to +91 7023037566 through the REST API of Twilio, set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM` (env or `.env`). If they are not set, the command skips SMS and shows no message.
- **Daily run.** The Windows Scheduled Task "Agnostos program reminders" runs `output/run_program_reminders.ps1` each day at 09:00. Its log is `output/program_reminders.log`.

Tests: `python tests/program_reminders_test.py`.

### `coordinators`: one email per internship-programme office

```bash
python -m outreach.cli coordinators [--send] [--live] [--yes] [--only ID ...] [--local-window 9-17] [--wait] [--weekends] [--xlsx PATH]
```

This command reads `output/programs/coordinator_outreach.xlsx` (sheet `Outreach`: id, programme, contact name, role, email, source_url, subject, body, attachment path, approved, sent_at, notes, country, message_id). The script `output/programs/make_coordinator_outreach.py` makes the drafts and the `Skipped` sheet.

- The command uses only rows with `approved` = `yes` and an empty `sent_at`. Without `--send`, the command only lists them. `--send` makes each message (dry run). `--send --live` asks `[Y/N]` and sends.
- The mail goes out from the main IITD account (`SMTP_*`). Each message has only the CV in the `attachment path` of its row. The command ignores the `ATTACHMENTS` setting. If the file is missing, the command skips the row. The body already has its sign-off, thus the command does not add a signature.
- The command sends rows on weekdays between 9:00 and 17:00, in the local time of the office (`country` column). Outside that window, the command keeps the row for a subsequent run, or holds it with `--wait`. `--local-window any` disables this.
- The self-funding guard (`CAN_SELF_FUND`) stops each body that offers to pay for your own costs.
- After each real send, the command writes `sent_at` and `message_id` back to the row. Thus, a row never gets two emails.

Tests: `python tests/coordinators_test.py`.

### Reading every conversation

Mail that goes out over SMTP is not in the **Sent** folder of your mail app. Thus, the answer of a professor shows without the email that it answers. There are two solutions:

```bash
python -m outreach.cli conversations            # build output/conversations.html and open it
python -m outreach.cli archive-sent --live      # copy everything already sent into your IMAP Sent folder (one-off backfill)
```

- **`conversations`** makes one searchable page with each thread in sequence. The page includes these items:
  - your first email (exactly as sent) and the resends from the second account
  - the replies of the professor and the bounces
  - your replies and follow-ups
  - the drafts that did not go out yet.

  You can filter by state (`awaiting you`, `replied`, `bounced`, `draft pending`...). To update the page, run the command again at any time.
- **`archive-sent`** adds the old emails to the IITD **Sent** folder (with the original Message-ID and Date). Thus, Outlook, Thunderbird and webmail show full threads. The command records what it copied (`output/archived_sent.json`). Thus, a second run never makes duplicates. From now on, the tool also copies each email that it sends over SMTP to Sent automatically (`SAVE_TO_SENT=true`; Gmail does this itself).

### `legacy` — write to the leading researchers in your field

```bash
python -m outreach.cli legacy --find --include "Neil deGrasse Tyson; Fabiola Gianotti"   # build output/legacy.xlsx
python -m outreach.cli legacy --draft                     # one aspiring-scientist letter each
python -m outreach.cli legacy --send                      # dry run
python -m outreach.cli legacy --send --live               # send approved letters from RESEND_SMTP_* (your Gmail)
```

`legacy` finds researchers who have a high impact and who are still active in your topics (`--topics`, worldwide by default, `--min-h 60`). It also adds each person that you name with `--include`. It keeps only physicists. To also keep robotics/ML/interpretability people, use `--any-field`. To require a topic match, use `--match REGEX`. The command gets the papers of small teams of each person. Thus, a letter never gives them credit for a collaboration paper with 3,000 authors. The command skips each person already in `legacy.xlsx` or who already got an email (`professors.xlsx` / `send_log.csv`).

The addresses come from the same strict finder as `verify`. The command rejects an address at an unrelated institution or at a domain that is not academic. If a public figure has no published address, the list shows a note: use their official contact page.

Live legacy sends use `LEGACY_FOCUS_KEYWORDS` as their focus gate. If this setting is empty, they use `FOCUS_KEYWORDS`. Thus, the gate does not stop approved letters outside physics.

The letter is different from an internship request. It is a short, specific and humble note with these parts:

- one idea of the researcher that had an effect on your thinking
- one real project of yours
- a small request.

The request is a summer visit through a real route, or the name of a person who can help. Real routes are CERN/DESY summer student programmes, DAAD WISE, Mitacs, Charpak, EPFL/ETH summer programmes, Caltech SURF, or the group of the researcher. The letter never invents how you found their work.

Review `output/legacy.xlsx`. Set **Approved = yes** for each letter that you want to send. `--approve-all` applies only to addresses that the finder verified. You must approve each address that you typed manually, row by row. The command sends at intervals of 2-5 minutes, 10 for each run (`--limit`).

By default, letters have no attachments. Cold first emails include a link to `CV_URL`. To attach the global `ATTACHMENTS`, set `COLD_ATTACH_CV=true`. To send specified files with one letter, write a list of paths, separated by semicolons, in the **Attachment** column of that row. For example, a portfolio PDF and a CV for a specified programme. `none` sends that letter without attachments. If a file in the list is missing, the command holds the row and does not send it.

### `resend` — re-deliver the original email from a second account

```bash
python -m outreach.cli resend                                   # dry run: who would get it
python -m outreach.cli resend --live --local-window 9-17 --wait # send
python -m outreach.cli resend --who bounced --live              # only bounced ones
```

This command sends the **exact original subject and body** again (no new draft) through `RESEND_SMTP_*`. For example, this can be a Gmail account with an [app password](https://myaccount.google.com/apppasswords). It sends to these professors:

- professors who got an email but did not answer (`--who noreply`)
- professors whose email bounced (`--who bounced`)
- both groups (`all`, the default).

It skips each person who replied or sent an auto-reply. It also skips each person who already got a resend (recorded in `send_log.csv` and in a `Resent At` column). It also skips each person who got the first email less than `RESEND_MIN_DAYS` ago. Bounced rows go first, and `RESEND_DAILY_CAP` sets the maximum number of sends each day. The command never changes the original `Send Status`/`Sent At`/`Message ID`. A hard bounce means that the server rejected the address. Thus, verify those addresses again before you send again.

---

## The pipeline

**1. Resume parsing** (`resume_parser.py`): PDF through `pdfplumber`, DOCX through `python-docx`. The parser knows the sections of the resume. It does these tasks:

- It divides the text at headings.
- It extracts education, interests, projects and achievements.
- It repairs PDF text where words are joined together.
- It extracts a set of keywords from the vocabulary of the domain.

It can read project lists with bullets and project lists in plain text.

**2. Target acquisition**
- *Mode B* reads each sheet in your workbook that looks like a list of professors. It finds the header row automatically and maps about 25 header aliases. It puts unknown columns into a notes field, and it removes duplicates by email.
- *Mode A* scrapes faculty directories (see below).
- *`discover`* makes the workbook for you from a research topic. It uses the OpenAlex paper index, not a list of universities.
- *`verify`* then checks the addresses of those rows. With `--repair`, it also finds them.

**3. OpenAlex enrichment** (`enrich.py`): free API. This step does these tasks:

- It resolves each professor to an author ID (it uses the institution to find the correct person).
- It gets the topic concepts of the professor.
- It gets recent papers where the professor is the **first or last author**, with abstracts.
- It removes collaboration papers with 3000 authors, because they tell nothing about the PI.

The step keeps the results in `output/openalex_cache.json`. Thus, a second run costs nothing.

> The OpenAlex tier without a key shares a small daily budget across your full IP address. If you see `OpenAlex rate limit hit`, get a free key at [openalex.org](https://openalex.org/), and set `OPENALEX_API_KEY` in `.env`. If the limit occurs, the pipeline continues without enrichment.

**4. Local NLP filter** (`matcher.py`): **zero tokens**. This filter uses these methods:

- TF-IDF cosine similarity in pure Python, with bigrams.
- IDF calculated over the actual corpus. Thus, the filter gives less weight to frequent words such as "physics".
- A layer of synonyms (`HEP`→high-energy physics, `GNN`→graph neural network, `PINN`→SciML, …).
- A bonus for overlap of domain terms, with a maximum value.

Only professors above `--min-score` and within `--max-professors` go to the LLM.

The filter rejects professors with too little research context, whatever their score. An example is a short directory entry such as `"Research CMS 511b"`. A "personalised" email from no information is generic, and it uses tokens for no result. In Mode A, most scraped rows get this result. For this reason, enrichment is important. Use `sources.yaml` for **group pages with research descriptions**, not for simple staff tables.

**5. LLM evaluation + drafting** (`llm.py`): one Chat Completions call for each professor gives **both** the probability score and the email draft. It works with Groq, OpenAI, or any gateway that is compatible with OpenAI.

Token optimisations:
- The profile of the applicant is in a **stable prefix of the system prompt**. Providers with automatic prompt caching give a discount for it (≈4× cheaper) on each call after the first. The prompt is intentionally longer than the 1024-token minimum that caching requires.
- The user message for each professor has only a context block of about 250 tokens.
- **Structured Outputs** (`strict: true` JSON schema) make sure that the response can be parsed, where the provider supports it. This includes Groq.
- Rejected professors never cost anything.

Reliability:
- **Capability negotiation.** Gateways and proxies accept different fields. On a `400` error, the client removes the field that is most probably not supported, then tries again. The sequence is `json_schema` → `json_object` → `max_completion_tokens` → `temperature`. The client learns each downgrade one time and uses it for the remainder of the run. Downgrades do not use the retry budget.
- **Body repair.** If a draft has no salutation, or if it is one large block of text, the tool changes its format. The result is a greeting plus 3–4 paragraphs. Then the tool writes the draft.
- The tool reports truncated responses (`finish_reason: length`). It does not save them without a message.
- After three failures in sequence, the run stops. This prevents the loss of the full list.

The **estimation gate** shows the projected tokens and cost. It requires `[Y/N]` before each paid call. On a free provider, it tells you that the provider is free, and it asks you also:

```
 Model                : openai/gpt-oss-120b
 Professors to call   : 47
 System prompt        : ~1,115 tokens (identical prefix each call)
 Input tokens  (total): ~56,226
 Output tokens (total): ~28,435
 ESTIMATED COST       : $0.0000 (provider free tier)
 Proceed with the LLM calls? [Y/N]:
```

On a paid provider, a cost limit also stops the run before completion if the cost gets to `BUDGET_USD`.

**6. Humanising layer** (`humanize.py`): three stages. Two of them are free:

1. **Deslop**: regex substitutions that remove the usual LLM signs. Examples are "I hope this email finds you well", "delve", "leverage" and "I am writing to express". Other examples are too many em dashes, groups of three, and empty superlatives.
2. **Score**: an AI-tell rating of the cleaned draft. This stage also finds *hard claims* that you must check before you sign. Examples are invented publications, false grades and exaggerated results.
3. **Rewrite**: the draft goes back to the model for a rewrite only in two conditions. The score is still at or above `HUMANIZE_THRESHOLD`, or the tool found a hard claim. Most drafts never get to this stage.

The tool writes the score and the review flags into the spreadsheet. Thus, you can sort by them.

**7. Data management** (`excel_io.py`): Mode B adds result columns in place, after a backup with a timestamp. Mode A writes a new sorted workbook:

`Local Match Score` · `Probability of Acceptance` · `Probability Justification` · `Email Subject` · `Custom Email Draft` · `AI-Tell Score` · `Review Flags` · `Email Status` · `Email Confidence` · `Email Notes` · `Suggested Email` · `Profile Status` · `LLM Status` · `Send Status` · `Sent At` · `Reply Status` · `Follow-up Notes` (plus `OpenAlex ID` and `Institution`, filled in only when blank)

The tool can run again with the same result (idempotent). It updates the existing columns and never makes duplicate columns. Blank LLM results never overwrite cells that you edited manually. The humanised draft goes into `Custom Email Draft`. Thus, you can edit it in Excel, and the tool sends exactly the text that you read. `check-replies` fills `Reply Status` and `Follow-up Notes`, and it keeps the notes that you typed.

**8. Dispatch** (`mailer.py`): SMTP with STARTTLS/SSL/plain. It has these functions:

- a signature that the tool makes from your resume and adds automatically
- CV/transcript attachments
- random delays and a daily limit
- a minimum probability and top-N selection
- a live countdown between sends
- `--at` start times and recipient-local send windows
- `.eml` export and dry-run previews.

The tool writes the statuses and each Message-ID back to the workbook.

**9. Reply tracking** (`replies.py`): a read-only IMAP scan of your inbox and spam folders. It matches replies by sender address and by the stored Message-ID. It identifies real replies, out-of-office auto-replies and bounces.

---

## Mode A: scraping and anti-bot handling

Optional. It requires `pip install playwright && python -m playwright install chromium`.

`sources.yaml`:

```yaml
sources:
  - url: https://www.example.ac.uk/high-energy-physics/people/
    institution: Example University
    country: UK
    department: High Energy Physics
```

The scraper (`scraper.py`) uses Playwright Chromium with these functions:

- **Fingerprint stealth.** The scraper does these changes:
  - It deletes `navigator.webdriver` from the prototype chain (it does not only set it to `undefined`).
  - It supplies a real `PluginArray` with `MimeType` entries, and the full `chrome.runtime`/`loadTimes`/`csi` surface.
  - It patches the WebGL vendor/renderer, and keeps the locale, time zone and screen depth consistent.
  - It spoofs `Function.prototype.toString`, so that the patches look like native code.
- **Random context identity.** The scraper selects a new viewport, device scale factor, locale and time zone for each context.
- **Human-like interaction.** The scraper uses mouse paths with smoothstep easing, different dwell times, and scroll bursts before it reads the content.
- **Residential proxy support.** Set `PROXY_SERVER`/`PROXY_USERNAME`/`PROXY_PASSWORD`. A blocked page starts a new context, that is, a new proxy exit and a new fingerprint.
- **Challenge detection.** The scraper finds Cloudflare/Imperva/PerimeterX interstitials by hard markers plus a page-length heuristic. Thus, a long directory page that only mentions Cloudflare does not give a false positive. The scraper waits for a challenge one time, then tries again with a new identity.
- **Two-hop email resolution.** Some directories show names but hide the emails. For these directories, the scraper opens the profile page of each person, and it finds the email by surname.
- **Fallback.** If Playwright is not installed, the scraper uses a plain HTTP fetch.

The extraction has two passes: one starts from emails (including `[at]`/`(dot)` obfuscation), and one starts from titles (`Prof`/`Dr`/`Reader`/…). The scraper removes role suffixes from names. It discards generic addresses (`info@`, `office@`, `studies@`).

By default, the scraper obeys `robots.txt`. If you set `RESPECT_ROBOTS=false`, that is your decision and your responsibility. Keep the delays long, and do not send too many requests to a site. The scraper does not solve CAPTCHAs.

---

## Configuration (`.env`)

All settings are in `.env` (see `.env.example`). `.env.example` has one required section and six optional sections. The code has no fixed values for these settings. The tool has no personal paths, addresses or keys. The most important settings are:

| Key | Default | Notes |
|---|---|---|
| `RESUME_PATH` | — | Required; the tool personalises all output from this file |
| `TARGET_XLSX` | — | Required for Mode B |
| `LLM_PROVIDER` | `groq` | `groq` (free) or `openai` |
| `GROQ_API_KEY` / `OPENAI_API_KEY` | — | The key of the provider that you selected |
| `SMTP_HOST/USER/PASSWORD/FROM` | — | Required only for `send --live` |
| `SMTP_AUTH` | `password` | `password` (SMTP_PASSWORD) or `xoauth2` (Gmail OAuth, see below) |
| `GOOGLE_OAUTH_TOKEN_FILE` | — | Token JSON that "connect Gmail" in the app writes; used when `SMTP_AUTH=xoauth2` |
| `OPENAI_BASE_URL` | — | Optional: Azure/OpenRouter/proxy endpoint |
| `DRAFT_MODEL` | provider default | Keep it blank, unless you prefer a specified model |
| `SCORE_MODEL` | provider default | |
| `CAN_SELF_FUND` | blank | `yes`/`no`: can you pay your own travel/living costs? This changes `replies` drafts when a professor mentions funding (blank = the draft has a `[FILL]`) |
| `SELF_FUND_NOTE` | — | Optional detail for the setting above, for example "family covers travel and 3 months' rent" |
| `BUDGET_USD` | `5.0` | Hard limit for each run; ignored on free tiers |
| `MAX_PROFESSORS` | `50` | Maximum number of LLM calls |
| `MIN_LOCAL_SCORE` | `0.25` | Local filter threshold |
| `HUMANIZE_REWRITE` | `true` | Paid rewrite pass for drafts that keep a high AI-tell score |
| `HUMANIZE_THRESHOLD` | `10` | AI-tell score that starts a rewrite |
| `ATTACHMENTS` | — | Separated by semicolons; CV, transcript. Attached to replies that mention an attachment. Attached to cold first emails only with `COLD_ATTACH_CV=true` |
| `COLD_ATTACH_CV` | `false` | Attach `ATTACHMENTS` to cold first emails (send/resend/legacy) |
| `CV_URL` | `https://avinashistoocool.github.io/` | CV link in first emails. The tool adds it to the signature when there is no attachment |
| `MAX_PER_DOMAIN_WEEK` | `3` | Maximum number of cold first emails for each institution domain in each rolling 7 days (from `send_log.csv`) |
| `NAME_MATCH_STRICT` | `true` | Cold sends need the first initial + surname in the address |
| `NO_COLD_EMAIL_FILE` | `output/no_cold_email.json` | Persons/domains that never accept ad-hoc interns; skipped at send time |
| `CONFIRMED_FACTS_FILE` | `output/confirmed_facts.md` | Facts and numbers that the draft prompt can quote; the tool removes other numbers |
| `OPENALEX_API_KEY` | — | Free; prevents the shared rate limit for each IP address |
| `DISCOVER_COUNT` / `DISCOVER_BATCHES` | `1000` / `4` | Number of persons and number of batches for `discover` |
| `DISCOVER_QUERIES` | — | Topics separated by `;` (default: the interests from the resume) |
| `DISCOVER_COUNTRIES` / `DISCOVER_SINCE` | `europe` / `2021` | Region and minimum paper year |
| `DISCOVER_MAX_PAGES` | `40` | Maximum number of pages for each batch |
| `DISCOVER_TOP_UNIVERSITIES` | `0` | Use only the N best universities of the region for `discover` (0 = off) |
| `DISCOVER_PRESTIGE_WEIGHT` | `1.0` | Weight of the university rank compared with the topic fit |
| `VERIFY_WORKERS` | `4` | Parallel email lookups |
| `SEND_DELAY_MIN/MAX` | `90`/`240` | Seconds between emails |
| `DAILY_SEND_CAP` | `25` | Keep below the provider limits. The code limits cold first emails to 40 each day |
| `SEND_LOCAL_WINDOW` | — | Recipient-local hours for sends, for example `9-11` |
| `IMAP_HOST/PORT/USER/PASSWORD` | from SMTP | Mailbox for `check-replies` |
| `IMAP_FOLDERS` | `INBOX;SPAM;Junk;Junk Email` | Folders to scan for replies |
| `SEND_MIN_PROBABILITY` / `COLD_MIN_PROBABILITY` | `40` / `40` | Permanent minimum quality. Cold sends never go below `COLD_MIN_PROBABILITY`, unless you use `--min-probability` |
| `RESPECT_ROBOTS` | `true` | Mode A |

### Gmail through OAuth (no app password)

In the desktop app, **Sign in with Google + connect Gmail** stores a refresh token. Then the CLI sends and reads mail with SASL `XOAUTH2`, not with a password:

```
SMTP_AUTH=xoauth2
GOOGLE_OAUTH_TOKEN_FILE=C:\path\to\gmail_token.json
SMTP_HOST=smtp.gmail.com
SMTP_USER=you@gmail.com
SMTP_FROM=you@gmail.com
```

The token file is JSON: `{"client_id": "...", "client_secret": "...", "refresh_token": "...", "token_uri": "https://oauth2.googleapis.com/token"}` (`token_uri` is optional). The tool refreshes access tokens automatically. It keeps them in memory until one minute before they expire. SMTP, `check-replies`/`replies` (IMAP) and `tls-check` all use the token. They ignore `SMTP_PASSWORD`/`IMAP_PASSWORD`. If Google reports `invalid_grant` (access revoked or expired), connect Gmail again in the app. The `resend` account continues to use `RESEND_SMTP_PASSWORD`.

The tool finds missing files, missing keys, and placeholder values from `.env.example` before it starts. It reports them in one clear `CONFIG:` message. Thus, it does not fail later, deep inside an API or SMTP call. Never commit `.env`. Git ignores it.

---

## Cost

**Groq is free**, and it is the default. A full run for 47 professors costs nothing. This includes enrichment, scoring, drafts and humanising. For the current catalogue, run `python -m outreach.cli models --provider groq`. `openai/gpt-oss-120b` is the default, and it is the strongest of the free options.

To use OpenAI, set `LLM_PROVIDER=openai` and an `OPENAI_API_KEY`. These are the prices for each full run for 47 professors, with prompt caching on:

| Model | Est. cost |
|---|---|
| `gpt-4.1` | ~$0.26 |
| `gpt-5-mini` | ~$0.06 |
| `gpt-4.1-mini` | ~$0.05 |
| `gpt-4o-mini` | ~$0.02 |

To change the provider for one run, use `--provider openai --model gpt-4.1-mini`. The local filter and OpenAlex enrichment are always free. Thus, the tool sorts most of your target list before it uses a single token. For unknown model names, the estimate uses the `gpt-4.1` prices. For a correct estimate, add these names to `MODEL_PRICES` in `outreach/config.py`.

---

## Testing

```bash
python tests/make_fixtures.py       # optional; the suites build these on demand
python tests/smoke_test.py          # fully mocked, no network, no spend
python tests/openai_stub_test.py    # real OpenAI SDK against a local stub server
```

The two suites run on a new clone with **no `.env` and no API key**. They use synthetic fixtures (`tests/fixtures/`) that they make when necessary. If your `.env` points to real files, the tests use those files. Thus, the same tests also check your own setup. CI runs them on Python 3.10, 3.12 and 3.13.
Windows CI also checks Python 3.15, and it uses only prebuilt wheels. A
new 3.15 installation does not need Visual C++ Build Tools. The base
requirements use a YAML reader in pure Python, and they include `tzdata` for
recipient-local send windows. See the [Windows guide](docs/install-windows.md).

`smoke_test.py` tests these areas:

- resume parsing and Excel round trips
- filter behaviour
- cost calculation on free and paid providers
- a mocked LLM pass, and early stop after repeated API failures
- repair of the draft format, and the humanising layer
- idempotent column writes and attachment handling
- safe continuation of interrupted sends, and `.eml` export
- scraper extraction and block detection
- email verification
- the plan of discovery batches, and resume fingerprints
- workbook growth that only adds rows
- institution matching for `recheck`
- the skip of rows that have the status sent (also rows in the pending sidecar)
- the rule that `--apply` never replaces an address that passed.

`openai_stub_test.py` starts a local HTTP server and points the real `openai` SDK to it. It then checks these items:

- the shape of the request
- the count of cached tokens
- the omission of temperature for reasoning models
- truncation handling
- **capability downgrade with a restrictive gateway**
- the connection of the Groq provider.

---

## Sending etiquette

Cold emails to professors work when they are specific and few. Read each draft before you send it. The LLM uses real OpenAlex publications, but you sign the email. Models sometimes invent a credential, and the `Review Flags` column is there for this reason. Keep `DAILY_SEND_CAP` low, and send from your university address. Attach your CV, and use `--top 10`. Do not send email to a full faculty.

### When sends start failing

University relays apply strict limits. If a server refuses a message or the socket disconnects, the mailer connects again one time and tries again. After three failures in sequence, it stops the run, so that the remaining rows stay available for a send. The tool never marks failed rows as sent. Thus, if you run the same command again, it tries exactly those rows again and skips the successful rows.

If you see `SMTPSenderRefused` or repeated `SMTPServerDisconnected`, the relay almost certainly applies a rate limit. Do these steps:

1. Increase `SEND_DELAY_MIN`/`SEND_DELAY_MAX` (300/600 is safe for a university server).
2. Decrease `DAILY_SEND_CAP`.
3. Send in small batches with `--top 5`.
4. Make sure that `SMTP_FROM` is exactly the address that `SMTP_USER` can send as. Most relays refuse a mismatch.

### The spreadsheet is the database

There is no separate database. The workbook at `TARGET_XLSX` holds all the data. The `Send Status` column is the only record of the persons who got an email. The tool always skips rows that have the status `sent` or `review-sent`. All other rows (blank, `dry-run`, `failed: …`) can still get an email. Thus:

- `--top 50` after a `--top 10` run sends to the next 40, not to the first 10 again.
- If you edit or clear `Send Status` manually, you *will* change who gets an email. If you clear a `sent` cell, the tool sends that email again.
- If you add rows with a draft and an email address, you add new targets. If you delete rows, you remove them.
- `--resend` intentionally ignores `Send Status`, and sends to all rows that agree with the filters.

That column is the only safeguard. For this reason, `send --live` does not start if the workbook is open in Excel. If the file becomes locked during a run, the tool keeps the statuses in `<workbook>.xlsx.pending-status.json`. It applies them on the next run, so that they are not lost. The tool counts rows in that file as sent in all commands: `send`, `verify` and `recheck` skip them.

By default, `verify` and `recheck` do not change rows that already got an email (use `--include-sent` to change this). Thus, if you check a list that you partly used, the tool never changes the addresses that you used.

### Scaling up without mailing anyone twice

```bash
# 1. Grow a fresh list, skipping everyone already in your existing workbook(s)
python -m outreach.cli discover --count 500 --batches 4 \
    --query "physics; artificial intelligence; computational physics" \
    --output output/professors_500.xlsx --exclude path/to/your_current_list.xlsx

# 2. Find each person's current published address
python -m outreach.cli verify --xlsx output/professors_500.xlsx --repair --apply --workers 6

# 3. Score and draft, then send the best ones in small batches
python -m outreach.cli run --mode list --xlsx output/professors_500.xlsx
python -m outreach.cli send --xlsx output/professors_500.xlsx --live --top 10

# Later: is everyone still there, and are the addresses still current?
python -m outreach.cli recheck --xlsx output/professors_500.xlsx --apply
```

Each step can continue after an interruption: run the same command again. Close the workbook in Excel before each step that writes to it.

---

## Citing

If Agnostos helps your research or a report, cite it with the **Cite this repository** button of GitHub (from [`CITATION.cff`](CITATION.cff)).

---

## License

MIT — see [LICENSE](LICENSE).
