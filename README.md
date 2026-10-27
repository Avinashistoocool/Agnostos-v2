# Agnostos: AI research internship outreach

**Agnostos** is a free, open-source tool that helps students land research internships. It finds professors whose recent papers match your resume, drafts one honest cold email per professor, sends them slowly from your own inbox during each professor's working hours, and drafts replies to the answers.

> Hosted web version: [Agnostos web app](https://github.com/Avinashistoocool/Agnostos-v3) · Guides: [Windows](Documentation-for%20Windows.md) · [macOS](Documentation-for%20Mac.md) · [Linux](Documentation-for%20Linux.md) · [FAQ](FAQ.md)

An autonomous, token-efficient pipeline for research internship outreach. Agnostos matches your CV against prospective supervisors, retrieves their recent publications, predicts acceptance probability, drafts tailored cold emails without generic LLM prose, and throttles outbound SMTP delivery.

```
                 discover (OpenAlex, free) ─► verify --repair (web lookup, free)
                                   │
resume.pdf ─┐                      ▼
            ├─► local NLP filter (free) ─► [Y/N] cost gate ─► LLM ─► .xlsx ─► SMTP
targets ────┘        ▲ OpenAlex enrichment (free)            recheck ─┘
```

Point it at your CV and a spreadsheet of professors. It reads your resume, ranks the list against it for free, looks up each professor's recent papers, writes a specific email per person, strips the AI tells out of the prose, and sends them on a human-looking schedule — writing every draft and status back into your spreadsheet as it goes.

**It costs nothing.** The default provider is [Groq](https://console.groq.com/keys), whose free tier comfortably covers a full run. OpenAI (or any OpenAI-compatible gateway) is supported if you prefer it.

---

## Quick start

```bash
git clone https://github.com/Avinashistoocool/Agnostos-v2
cd Agnostos-v2
pip install -r requirements.txt

cp .env.example .env                       # Windows: copy .env.example .env
```

Open `.env` and fill in section 1 only: your resume path, your target `.xlsx`, a free [Groq key](https://console.groq.com/keys), and your SMTP details. Then:

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

`stats` reads the workbook (even while it's open in Excel) and every `send` appends each attempt to `output/send_log.csv`, so history survives later edits to the sheet.

Certificate errors (`CERTIFICATE_VERIFY_FAILED ... _ssl.c:...`, common with python.org Python on macOS): run `pip install -U truststore certifi`, then `python -m outreach.cli tls-check`. Behind a TLS-inspecting proxy, set `SSL_CERT_FILE` to its root certificate.

Step-by-step setup guides for each operating system: [Windows](Documentation-for%20Windows.md) · [macOS](Documentation-for%20Mac.md) · [Linux](Documentation-for%20Linux.md) · Questions: [FAQ](FAQ.md) · Something broken: [Diagnostics](DIAGNOSTICS.md)

SMTP is only needed for the last step — you can draft everything without it. Mode A scraping is entirely optional, and `.env.example` is organised so that only its first section is required; everything else has working defaults.

Don't have a list of professors yet? Build one from your research topic instead of collecting names by hand:

```bash
python -m outreach.cli discover --count 1000 --batches 4 --query "machine learning particle physics; geometric deep learning"
python -m outreach.cli verify --xlsx output/professors.xlsx --repair --apply
```

See [`discover`](#discover--build-a-target-list-of-n-professors-in-batches) below.

### Your target spreadsheet

Any `.xlsx` works. The header row is auto-detected and ~25 common column names are mapped, so you usually need nothing beyond:

| Professor Name | Email | Institution | Research Area |
|---|---|---|---|
| Prof Jane Smith | jane.smith@uni.de | TU Munich | Graph neural networks for jet tagging |

`Country`, `Department`, `Fit Reason`, `Funding`, `Eligibility`, and `Application Route` are picked up if present, and any unrecognised column is folded into a notes field the model still sees. Richer research blurbs produce noticeably better drafts.

---

## Commands

### `profile` — verify resume extraction

```bash
python -m outreach.cli profile [--resume PATH]
```

Prints name, programme, interests, skills, and projects, writes `output/profile.json`, and shows the exact profile block that will be embedded in the LLM system prompt. Run this first — everything downstream depends on it.

### `models` — list what your key can actually reach

```bash
python -m outreach.cli models [--provider groq|openai]
```

Queries the provider live and marks your current `DRAFT_MODEL`, with pricing where known. Provider catalogues change often; trust this over any table in a README, including the one below.

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
| `--sheet NAME` | Restrict to one sheet |
| `--sources PATH` | YAML/JSON directory list for Mode A |
| `--output PATH` | Write a new workbook instead of editing in place |
| `--max-professors N` | Cap how many reach the LLM |
| `--min-score F` | Local match threshold, 0–1 (default `0.25`) |
| `--budget USD` | Hard spend cap for the run |
| `--provider groq\|openai` | LLM provider (default: `LLM_PROVIDER` from `.env`) |
| `--model NAME` | Override the drafting model |
| `--no-enrich` | Skip OpenAlex publication lookups (same as `--skip enrich`) |
| `--skip STEPS` | Skip optional steps, comma-separated: `enrich` (OpenAlex), `filter` (local score threshold; rows still need an email and the `--max-professors` cap applies), `gate` (same as `--yes`). e.g. `--skip enrich,filter` |
| `--no-profile-hop` | Mode A: don't open individual profile pages for emails |
| `--no-backup` | Don't back up the workbook before editing |
| `--yes` | Skip the `[Y/N]` cost gate (for scripting) |

### `discover` — build a target list of N professors, in batches

```bash
python -m outreach.cli discover --count 1000 --batches 4 \
    --query "machine learning particle physics; geometric deep learning; computational high energy physics; physics-informed machine learning"
python -m outreach.cli discover --count 200 --countries dach,nordics --since 2023
```

Builds a large, ranked list of professors without you naming a single university. It searches OpenAlex's **paper** index for your topics, keeps only recent papers from academic institutions in the chosen countries, and records the **first and last authors** — the people who lead the work. Papers with more than ~15 authors are discarded: a 2,000-author collaboration paper names everyone and tells you nothing about who works on what.

**How batching works.** `--count` is split evenly over `--batches` (1000 / 4 = 250 each). Each batch takes one topic from `--query` (separate topics with `;`); with fewer topics than batches they are reused, and a reused topic *continues from the page the previous batch reached*, so it finds new people rather than the same ones. A batch keeps reading pages until it has its quota of senior researchers, its topic runs out of relevant papers, or it hits `--max-pages`. Any shortfall is carried to the next batch.

- **Nobody is added twice** — across batches, and against everyone already in the output workbook (by OpenAlex id and by accent/order-insensitive name).
- **Each batch is saved the moment it finishes**, and progress is kept in `<output>.batches.json`. If the run is interrupted, re-run the same command and it resumes at the first unfinished batch. `--fresh` forces a new plan (see below for which options also do).
- **Off-topic results are dropped.** Free-text search matches words, not meaning ("geometric deep learning" also hits papers about tooth geometry). Each topic's own best results define which broad fields it belongs to, and papers from other fields, or far below the top relevance, are ignored. Nothing about subjects is hardcoded.

| Flag | Purpose |
|---|---|
| `--count N` | Total professors to find (default `DISCOVER_COUNT`, `1000`) |
| `--batches K` | Number of batches (default `DISCOVER_BATCHES`, `4`) |
| `--query "a; b; c"` | Topics, one per batch, reused round-robin (default `DISCOVER_QUERIES`, then your resume's interests) |
| `--countries` | `europe`, `eu`, `dach`, `nordics`, `uk`, `usa`, `northamerica`, `asia`, `anz`, or ISO codes like `de,ch,gb` |
| `--since YEAR` | Only count papers from this year on (default `2021`) |
| `--max-pages N` | Page cap per batch, 100 papers per page (default `40`) |
| `--min-h-index N` | Seniority gate (default `8`) — filters out first-year PhD students |
| `--min-works N` | Minimum publication count (default `20`) |
| `--output PATH` | Workbook to grow (default `output/professors.xlsx`) |
| `--verify-emails` | Look up each person's current address as each batch finishes (slow; see `verify`) |
| `--workers N` | Parallel email lookups (default `VERIFY_WORKERS`, `4`) |
| `--exclude XLSX` | Skip anyone already in this workbook (repeatable; a missing path prints a warning) |
| `--resume PATH` | Resume used to derive default topics when `--query` is omitted |
| `--fresh` | Discard saved batch progress |
| `--top-universities N` | Only consider people at the region's N best universities, and favour higher-ranked ones (default `DISCOVER_TOP_UNIVERSITIES`, `0` = off) |
| `--prestige-weight W` | With `--top-universities`: `0` = topic fit only, `1` = balanced (default), `3` = mostly prestige |
| `--list-universities` | Print the region's top universities and exit |

**Aiming for the best universities.** `--top-universities N` ranks the universities in `--countries` by how many highly-cited papers (50+ citations) they've published since `--since`. That proxy tracks the usual league tables closely (for `dach`: ETH Zurich, TUM, LMU, Zurich, Heidelberg, Bern, EPFL...) and needs no hardcoded list. Discovery then only searches papers from those universities and ranks people by topic fit plus a prestige bonus for their university's rank. Check the list first:

```bash
python -m outreach.cli discover --list-universities --countries europe --top-universities 30
python -m outreach.cli discover --count 200 --countries europe --top-universities 30 --prestige-weight 2
```

Changing `--top-universities` starts a new batch plan; changing `--prestige-weight` doesn't.

Progress is saved in `<output>.batches.json` after each batch, so re-running the same command resumes. Changing the topics, count, batches, countries, `--since`, `--min-h-index` or `--min-works` starts a new plan; `--max-pages` and `--exclude` can be changed without losing progress. If the output workbook is open in Excel when a batch finishes, the tool waits for you to close it rather than dropping the batch.

No API key is needed and nothing is scraped — OpenAlex is a free public index (set `OPENALEX_MAILTO` or `OPENALEX_API_KEY` for a faster, more reliable quota on big runs). Discovered rows carry a name, institution, country, research summary and OpenAlex id, but **no email address**; that is what `verify --repair` is for.

The full flow:

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

For every row not yet mailed it pulls the person's OpenAlex author record and marks them `active`, `moved` (now publishing from a different institution — acronyms like KIT, EPFL or CERN are resolved through OpenAlex, not a table), `inactive` (no papers for 3+ years) or `not found` (no author record matching both the name and the listed institution), in a **Profile Status** column. A lookup that fails (network error, rate limit) leaves the previous status untouched. A blank Institution or OpenAlex ID cell is filled in from the record; filled cells are never overwritten. It then re-runs the `verify --repair` email lookup for the same rows.

| Flag | Purpose |
|---|---|
| `--apply` | Replace missing or failing addresses with the one found online |
| `--professors-only` / `--emails-only` | Run only one half of the check |
| `--include-sent` | Also recheck rows already marked `sent`/`review-sent` (skipped by default) |
| `--dry-run` | Report only, never touch the workbook |
| `--xlsx`, `--sheet`, `--workers`, `--no-dns`, `--no-backup` | As in `verify` |

### `verify` — check and repair email addresses

```bash
python -m outreach.cli verify --dry-run                  # report only
python -m outreach.cli verify --repair --apply           # find and write correct addresses
```

Every address is checked for syntax, for whether the domain actually accepts mail (MX/A records), and for whether the local part plausibly matches the professor's name. With `--repair` it goes further: it searches the web for that person, opens their own pages, and extracts the address *they* publish. An address is only trusted when the name matches **and** the page that published it belongs to the same domain — the tool never assumes how a given university's domain ought to be spelled, because that assumption is what produces confidently wrong addresses.

| Flag | Purpose |
|---|---|
| `--xlsx PATH` / `--sheet NAME` | Which workbook and sheet to check |
| `--top N` | Only check the N highest-probability rows (by `Probability of Acceptance`, falling back to a `Probability` column) |
| `--repair` | Search the web and read profile pages for the real address |
| `--apply` | Write the found address into the Email column when the current one is missing or not `ok`; a passing address is kept and the alternative left in `Suggested Email` |
| `--include-sent` | Also check rows already marked sent (skipped by default) |
| `--probe-smtp` | Ask the mail server whether the mailbox exists (advisory only) |
| `--no-dns` | Skip MX/A lookups |
| `--workers N` | Parallel lookups (default `VERIFY_WORKERS`, `4`) |
| `--dry-run` | Report only, never touch the workbook |

Each row ends up `ok`, `suspect`, or `invalid`, with a confidence percentage and a note saying where the address was seen. Results are cached in `output/email_lookup_cache.json`, so re-running is cheap. Repair is slow — 20–40 seconds per professor, since it is doing real web searches; `--workers` runs several at once (1,000 professors at 4 workers takes roughly 2–3 hours) — so run it once on a freshly discovered list rather than before every send.

### `send` — dispatch

```bash
python -m outreach.cli send --dry-run --preview 3
python -m outreach.cli send --live --top 10 --min-probability 60
```

| Flag | Purpose |
|---|---|
| `--live` | Actually send (default is dry-run) |
| `--dry-run` | Explicit dry run (the default) |
| `--review` | Mail every draft to yourself (`SMTP_FROM`) instead of the professor |
| `--review-to ADDR` | Like `--review`, to a different address |
| `--export` | Write `.eml` files instead of sending (`--export-dir DIR`, default `output/drafts`) |
| `--top N` | Email only the **N highest-probability** professors |
| `--limit N` | Max real sends this run (overrides `DAILY_SEND_CAP`) |
| `--min-probability N` | Only send to rows scoring ≥ N% |
| `--allow-unverified` | Also send to rows whose Email Status is `invalid` |
| `--delay-min/--delay-max S` | Randomised gap between sends |
| `--resend` | Re-send rows already marked sent |
| `--preview N` | How many full drafts to print in dry-run |
| `--at TIME` | Wait (with a countdown), then start at `HH:MM` or `YYYY-MM-DD HH:MM`, your local time |
| `--local-window H-H` | Only send inside the recipient's local hours, e.g. `9-11` (from the Country column; default `SEND_LOCAL_WINDOW`, `off` disables) |
| `--wait` | With a local window, keep running until each row's window opens instead of holding it |
| `--weekends` | Allow the local window on Saturday/Sunday (weekdays only by default) |
| `--yes` | Skip the `[Y/N]` prompt, for Task Scheduler / cron |
| `--xlsx PATH` / `--sheet NAME` / `--resume PATH` | Workbook, sheet, and resume (for the signature) |

**Choosing how many to mail.** Three knobs, combinable:

- `--top N` ranks the drafted rows by acceptance probability and mails the best N. This is usually what you want.
- `--min-probability N` sets a quality floor instead of a count.
- `--limit N` caps how many emails are actually sent in this run, applied after the `--top` ordering.
- `DAILY_SEND_CAP` in `.env` is the default for `--limit`: a per-run cap on real sends (it does not count earlier runs that day).

Rows already marked `sent` are skipped automatically, so an interrupted run is safe to resume. Dry runs never block a later real send.

**Scheduling.** Emails land best mid-morning in the professor's own timezone.

```bash
# Start at 12:30 IST (09:00 CEST); only mail people for whom it is 9-11 locally
python -m outreach.cli send --live --top 20 --at 12:30 --local-window 9-11
# Same, but keep running until every row's window opens (e.g. Finland, then UK)
python -m outreach.cli send --live --top 20 --local-window 9-11 --wait
```

Rows outside their window are left untouched and go out on a later run. The terminal must stay open and the PC awake. To run unattended every weekday, register a Windows scheduled task:

```powershell
schtasks /Create /TN AgnostosSend /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 12:30 `
  /TR "cmd /c cd /d C:\path\to\Agnostos-v2 && python -m outreach.cli send --live --yes --top 20 --local-window 9-11 --wait >> output\send.log 2>&1"
```

Each successful send also stores its `Message ID`, which `check-replies` uses to match answers.

### `check-replies` — who answered

```bash
python -m outreach.cli check-replies            # update Reply Status
python -m outreach.cli check-replies --dry-run  # report only
```

Logs into your mailbox over IMAP (read-only, nothing is marked read), looks in `IMAP_FOLDERS` for mail from each `sent` professor or threaded to the stored Message ID, and classifies it as `replied`, `auto-reply` (out-of-office) or `bounced`. Results go to **Reply Status** (e.g. `replied 2026-10-16 14:02`) and a `[reply] subject | first lines` note in **Follow-up Notes** — notes you typed yourself are never overwritten. `IMAP_HOST` defaults to `SMTP_HOST` with `smtp.` → `imap.`, and the login reuses `SMTP_USER`/`SMTP_PASSWORD`.

### `replies` — draft and send follow-ups

```bash
python -m outreach.cli replies                              # draft follow-ups -> output/reply_queue.json
python -m outreach.cli replies --approve-all                # approve every unsent reply/thank draft
python -m outreach.cli replies --send                       # dry run of approved drafts
python -m outreach.cli replies --send --live                 # really send approved drafts
python -m outreach.cli replies --send --live --approve-all  # approve everything and send in one go
python -m outreach.cli replies --send --live --local-window 9-17 --wait  # send in each professor's working hours
```

`--local-window`, `--wait` and `--weekends` work like they do for `send`. Each reply's timezone comes from the workbook's Country column (falling back to the email's country TLD, e.g. `.es`); `SEND_LOCAL_WINDOW` in `.env` is the default, `--local-window off` disables it. Sent replies are saved to the queue immediately, so stopping a `--wait` run never resends.

Review or edit bodies in `output/reply_queue.json` before sending; set `"approved": true` per item to approve selectively. `--approve-all` approves every queued draft that has a body, isn't already sent and whose action isn't `none` — including drafts queued by earlier runs. `--redraft` regenerates drafts already in the queue.

If a reply says something is attached (e.g. "I've attached my CV"), the files in `ATTACHMENTS` are attached to it automatically and the send log shows `[attached: ...]`. If that file is missing the reply fails instead of going out without the promised CV. Replies that don't mention an attachment are sent without one.

If drafting fails with `403 ... model is not currently available upstream`, your provider no longer serves that model: run `python -m outreach.cli models` and set `DRAFT_MODEL` / `SCORE_MODEL` in `.env` to one that's listed.


### Funding follow-ups and meeting requests

When a professor says they can't fund you (or can only pay part), `replies` doesn't stop at a thank-you. It writes a reply that keeps the door open: partial support, a remote project, a shorter visit, or a joint fellowship application. If they then go quiet, each `replies` run drafts up to `FUNDING_FOLLOWUPS` (default 2) more follow-ups, sent only after `FOLLOWUP_GAP_DAYS` (default 2) of silence. As soon as they write back, the follow-ups stop.

**Meeting requests.** Your second message in a thread always asks for a short call (`MEET_MINUTES`, default 20), and so does every funding follow-up. Each request offers three slots on different weekdays. Every slot falls inside the professor's `MEET_THEIR_HOURS` and your own `MEET_MY_HOURS` (in `MEET_MY_TZ`). Slots are never offered to two professors at once and, once Google Calendar is connected, avoid times you're already busy. When the email is sent, each proposed slot is added to your calendar as a tentative "HOLD". Delete the extra holds once the professor picks a time.

**Google Calendar (one-time setup).** Follow **[CALENDAR.md](CALENDAR.md)**. It covers creating the Cloud project, making the app *External / Testing* (which avoids the common `Error 403: org_internal`), downloading `credentials.json`, running `python -m outreach.cli calendar-auth`, switching accounts, and troubleshooting.

Without the setup, meeting requests still go out. Only the calendar check and the holds are skipped.

### Reading every conversation

Mail sent over SMTP doesn't appear in your mail app's **Sent** folder, so a professor's answer shows up without the email it answers. Two fixes:

```bash
python -m outreach.cli conversations            # build output/conversations.html and open it
python -m outreach.cli archive-sent --live      # copy everything already sent into your IMAP Sent folder (one-off backfill)
```

- **`conversations`** builds one searchable page with every thread in order: your first email (exactly as sent), resends from the second account, the professor's replies, bounces, your replies and follow-ups, and drafts still waiting to go out. You can filter by state (`awaiting you`, `replied`, `bounced`, `draft pending`...). Re-run it any time to refresh.
- **`archive-sent`** backfills the IITD **Sent** folder (with the original Message-ID and Date) so Outlook/Thunderbird/webmail show full threads. It remembers what it copied (`output/archived_sent.json`), so re-running never duplicates. From now on, every email sent over SMTP is also copied to Sent automatically (`SAVE_TO_SENT=true`; Gmail already does this itself).

### `legacy` — write to the leading researchers in your field

```bash
python -m outreach.cli legacy --find --include "Neil deGrasse Tyson; Fabiola Gianotti"   # build output/legacy.xlsx
python -m outreach.cli legacy --draft                     # one aspiring-scientist letter each
python -m outreach.cli legacy --send                      # dry run
python -m outreach.cli legacy --send --live               # send approved letters from RESEND_SMTP_* (your Gmail)
```

`legacy` finds high-impact, still-active researchers in your topics (`--topics`, worldwide by default, `--min-h 60`), plus anyone you name with `--include`. It keeps only physicists and fetches their own small-team papers, so a letter never credits them with a 3,000-author collaboration paper. Addresses come from the same strict finder as `verify`, and an address at an unrelated institution or a non-academic domain is rejected. Public figures with no published address are listed with a note to use their official contact page.

The letter is different from an internship request. It's a short, specific, humble note: one idea of theirs that shaped your thinking, one real project of yours, and a small ask, either a summer visit through a real route (CERN/DESY summer student programmes, DAAD WISE, Mitacs, Charpak, EPFL/ETH summer programmes, Caltech SURF, or their own group) or a pointer to someone who could help. It never invents how you found their work.

Review `output/legacy.xlsx` and set **Approved = yes** for each letter you want to send. `--approve-all` covers only addresses the finder verified; addresses typed in by hand must be approved row by row. Sends are spaced 2-5 minutes apart, 10 per run (`--limit`).

### `resend` — re-deliver the original email from a second account

```bash
python -m outreach.cli resend                                   # dry run: who would get it
python -m outreach.cli resend --live --local-window 9-17 --wait # send
python -m outreach.cli resend --who bounced --live              # only bounced ones
```

Sends the **exact original subject and body** (no redraft) through `RESEND_SMTP_*` (e.g. a Gmail account with an [app password](https://myaccount.google.com/apppasswords)) to professors who were mailed but never answered (`--who noreply`), whose mail bounced (`--who bounced`), or both (`all`, default). It skips anyone who replied or auto-replied, anyone already resent (tracked in `send_log.csv` and a `Resent At` column), and anyone first mailed less than `RESEND_MIN_DAYS` ago. Bounced rows go first, and `RESEND_DAILY_CAP` limits sends per day. The original `Send Status`/`Sent At`/`Message ID` are never changed. A hard bounce means the address itself was rejected, so re-verify those addresses before resending.

---

## The pipeline

**1. Resume parsing** (`resume_parser.py`) — PDF via `pdfplumber`, DOCX via `python-docx`. Section-aware: splits on headings, pulls education/interests/projects/achievements, repairs glued-together PDF text, and extracts a domain-vocabulary keyword set. Bulleted and plain-text project lists are both handled.

**2. Target acquisition**
- *Mode B* reads every professor-like sheet in your workbook, auto-detects the header row, maps ~25 header aliases, folds unknown columns into a notes field, and de-duplicates by email.
- *Mode A* scrapes faculty directories (see below).
- *`discover`* builds the workbook for you from a research topic, using the OpenAlex paper index rather than any list of universities.
- *`verify`* then checks, and with `--repair` finds, the addresses those rows should carry.

**3. OpenAlex enrichment** (`enrich.py`) — free API. Resolves each professor to an author ID (disambiguated by institution), pulls their topic concepts, and fetches recent **first/last-author** papers with abstracts, filtering out 3000-author collaboration papers that say nothing about the PI. Results are cached in `output/openalex_cache.json`, so re-runs cost nothing.

> OpenAlex's keyless tier shares a small daily budget across your whole IP. If you see `OpenAlex rate limit hit`, grab a free key at [openalex.org](https://openalex.org/) and set `OPENALEX_API_KEY` in `.env`. The pipeline degrades gracefully and continues without enrichment.

**4. Local NLP filter** (`matcher.py`) — **zero tokens**. Pure-Python TF-IDF cosine similarity with bigrams, IDF computed over the actual corpus (so "physics" is correctly discounted), a synonym layer (`HEP`→high-energy physics, `GNN`→graph neural network, `PINN`→SciML, …), and a saturating domain-term overlap bonus. Only professors above `--min-score` and within `--max-professors` reach the LLM.

Professors with too little research context (bare directory stubs like `"Research CMS 511b"`) are rejected regardless of score — a "personalised" email written from nothing reads generic and wastes tokens. In Mode A this is the usual outcome for most scraped rows, which is why enrichment matters: aim your `sources.yaml` at **group pages with research blurbs**, not bare staff tables.

**5. LLM evaluation + drafting** (`llm.py`) — one Chat Completions call per professor returns **both** the probability score and the email draft. Works against Groq, OpenAI, or any OpenAI-compatible gateway.

Token optimisations:
- The applicant profile sits in a **stable system-prompt prefix**, so providers with automatic prompt caching discount it (≈4× cheaper) on every call after the first. The prompt is deliberately kept above the 1024-token minimum caching requires.
- Per-professor user messages carry only a ~250-token context block.
- **Structured Outputs** (`strict: true` JSON schema) guarantee a parseable response where supported — including on Groq.
- Rejected professors never cost anything.

Robustness:
- **Capability negotiation.** Gateways and proxies differ in what they accept. On a `400`, the client drops the most likely unsupported field — `json_schema` → `json_object` → `max_completion_tokens` → `temperature` — and retries. Downgrades are learned once and reused for the rest of the run, and they don't consume retry budget.
- **Body repair.** Drafts missing a salutation, or returned as one wall of text, are reformatted into a greeting plus 3–4 paragraphs before being written.
- Truncated responses (`finish_reason: length`) are reported, not silently saved.
- Three consecutive failures abort the run rather than burning the list.

The **estimation gate** prints projected tokens and cost and demands `[Y/N]` before any paid call. On a free provider it says so and asks anyway:

```
 Model                : openai/gpt-oss-120b
 Professors to call   : 47
 System prompt        : ~1,115 tokens (identical prefix each call)
 Input tokens  (total): ~56,226
 Output tokens (total): ~28,435
 ESTIMATED COST       : $0.0000 (provider free tier)
 Proceed with the LLM calls? [Y/N]:
```

A running cost ceiling also aborts mid-flight if `BUDGET_USD` is reached on a paid provider.

**6. Humanising layer** (`humanize.py`) — three stages, two of them free:

1. **Deslop** — regex substitutions that remove the standard LLM tells: "I hope this email finds you well", "delve", "leverage", "I am writing to express", em-dash pile-ups, triplet constructions, and empty superlatives.
2. **Score** — an AI-tell rating over the cleaned draft, plus detection of *hard claims* (invented publications, fabricated grades, overstated results) that you should check before signing.
3. **Rewrite** — only if the score is still at or above `HUMANIZE_THRESHOLD`, or a hard claim was found, does the draft go back to the model for a rewrite. Most drafts never reach this stage.

The score and any review flags are written into the spreadsheet so you can sort by them.

**7. Data management** (`excel_io.py`) — Mode B appends result columns in place (after a timestamped backup); Mode A writes a fresh sorted workbook:

`Local Match Score` · `Probability of Acceptance` · `Probability Justification` · `Email Subject` · `Custom Email Draft` · `AI-Tell Score` · `Review Flags` · `Email Status` · `Email Confidence` · `Email Notes` · `Suggested Email` · `Profile Status` · `LLM Status` · `Send Status` · `Sent At` · `Reply Status` · `Follow-up Notes` (plus `OpenAlex ID` and `Institution`, filled in only when blank)

Re-running is idempotent — existing columns are refreshed, never duplicated, and blank LLM results never overwrite cells you edited by hand. The humanised draft is what lands in `Custom Email Draft`, so you can edit it in Excel and send exactly what you read. `Reply Status` and `Follow-up Notes` are filled by `check-replies`; hand-typed notes are kept.

**8. Dispatch** (`mailer.py`) — SMTP with STARTTLS/SSL/plain, auto-appended signature built from your resume, CV/transcript attachments, randomised delays, a daily cap, probability floor, top-N selection, a live countdown between sends, `--at` start times, recipient-local send windows, `.eml` export, and dry-run previews. Statuses and each Message-ID are written back to the workbook.

**9. Reply tracking** (`replies.py`) — read-only IMAP scan of your inbox and spam folders; matches replies by sender address and by the stored Message-ID, and tells real replies from out-of-office auto-replies and bounces.

---

## Mode A: scraping and anti-bot handling

Optional. Requires `pip install playwright && python -m playwright install chromium`.

`sources.yaml`:

```yaml
sources:
  - url: https://www.example.ac.uk/high-energy-physics/people/
    institution: Example University
    country: UK
    department: High Energy Physics
```

The scraper (`scraper.py`) uses Playwright Chromium with:

- **Fingerprint stealth** — `navigator.webdriver` deleted from the prototype chain (not merely set to `undefined`), a real `PluginArray` with `MimeType` entries, full `chrome.runtime`/`loadTimes`/`csi` surface, patched WebGL vendor/renderer, consistent locale/timezone/screen depth, and `Function.prototype.toString` spoofing so the patches themselves read as native code.
- **Randomised context identity** — viewport, device scale factor, locale, and timezone are re-rolled per context.
- **Human-like interaction** — smoothstep-eased mouse paths, variable dwell times, and scroll bursts before content is read.
- **Residential proxy support** — set `PROXY_SERVER`/`PROXY_USERNAME`/`PROXY_PASSWORD`; a blocked page triggers a fresh context, i.e. a new proxy exit and fingerprint.
- **Challenge detection** — Cloudflare/Imperva/PerimeterX interstitials are detected by hard markers plus a page-length heuristic, so a long directory page that merely mentions Cloudflare isn't a false positive. Challenges are waited out once, then retried with a new identity.
- **Two-hop email resolution** — directories that list names but hide emails are followed to each person's profile page, where the email is matched by surname.
- **Graceful degradation** — without Playwright installed, it falls back to plain HTTP fetch.

Extraction is dual-pass: email-anchored (including `[at]`/`(dot)` obfuscation) and title-anchored (`Prof`/`Dr`/`Reader`/…), with role suffixes stripped from names and generic addresses (`info@`, `office@`, `studies@`) dropped.

`robots.txt` is honoured by default. Setting `RESPECT_ROBOTS=false` is your decision and your responsibility; keep the delays generous and don't hammer anyone. The scraper does not solve CAPTCHAs.

---

## Configuration (`.env`)

Every setting lives in `.env` (see `.env.example`, which is split into a required section and six optional ones). Nothing is hardcoded — the tool ships with no personal paths, addresses, or keys. The settings that matter most:

| Key | Default | Notes |
|---|---|---|
| `RESUME_PATH` | — | Required; everything is personalised from this |
| `TARGET_XLSX` | — | Required for Mode B |
| `LLM_PROVIDER` | `groq` | `groq` (free) or `openai` |
| `GROQ_API_KEY` / `OPENAI_API_KEY` | — | Whichever provider you chose |
| `SMTP_HOST/USER/PASSWORD/FROM` | — | Required only for `send --live` |
| `OPENAI_BASE_URL` | — | Optional: Azure/OpenRouter/proxy endpoint |
| `DRAFT_MODEL` | provider default | Leave blank unless you have a preference |
| `SCORE_MODEL` | provider default | |
| `CAN_SELF_FUND` | blank | `yes`/`no`: whether you can cover your own travel/living costs. Shapes `replies` drafts when a professor mentions funding (blank = draft leaves a `[FILL]`) |
| `SELF_FUND_NOTE` | — | Optional detail for the above, e.g. "family covers travel and 3 months' rent" |
| `BUDGET_USD` | `5.0` | Hard ceiling per run; ignored on free tiers |
| `MAX_PROFESSORS` | `50` | LLM call cap |
| `MIN_LOCAL_SCORE` | `0.25` | Local filter threshold |
| `HUMANIZE_REWRITE` | `true` | Paid rewrite pass for stubborn drafts |
| `HUMANIZE_THRESHOLD` | `10` | AI-tell score that triggers a rewrite |
| `ATTACHMENTS` | — | Semicolon-separated; CV, transcript |
| `OPENALEX_API_KEY` | — | Free; avoids the shared per-IP rate limit |
| `DISCOVER_COUNT` / `DISCOVER_BATCHES` | `1000` / `4` | `discover` headcount and batch split |
| `DISCOVER_QUERIES` | — | `;`-separated topics (default: resume interests) |
| `DISCOVER_COUNTRIES` / `DISCOVER_SINCE` | `europe` / `2021` | Region and paper recency |
| `DISCOVER_MAX_PAGES` | `40` | Page cap per batch |
| `DISCOVER_TOP_UNIVERSITIES` | `0` | Restrict `discover` to the region's N best universities (0 = off) |
| `DISCOVER_PRESTIGE_WEIGHT` | `1.0` | How much university rank counts against topic fit |
| `VERIFY_WORKERS` | `4` | Parallel email lookups |
| `SEND_DELAY_MIN/MAX` | `90`/`240` | Seconds between emails |
| `DAILY_SEND_CAP` | `25` | Stay under provider limits |
| `SEND_LOCAL_WINDOW` | — | Recipient-local hours to send in, e.g. `9-11` |
| `IMAP_HOST/PORT/USER/PASSWORD` | from SMTP | Mailbox for `check-replies` |
| `IMAP_FOLDERS` | `INBOX;SPAM;Junk;Junk Email` | Folders to scan for replies |
| `SEND_MIN_PROBABILITY` | `0` | Standing quality floor |
| `RESPECT_ROBOTS` | `true` | Mode A |

Missing files, missing keys, and placeholder values left over from `.env.example` are all detected up front and reported as a single clear `CONFIG:` message, rather than failing deep inside an API or SMTP call. Never commit `.env` — it is git-ignored.

---

## Cost

**Groq is free**, and it is the default. A full 47-professor run — enrichment, scoring, drafting, and humanising — costs nothing. Run `python -m outreach.cli models --provider groq` for the current catalogue; `openai/gpt-oss-120b` is the default and the strongest of the free options.

If you'd rather use OpenAI, set `LLM_PROVIDER=openai` and an `OPENAI_API_KEY`. Priced per full 47-professor run, with prompt caching active:

| Model | Est. cost |
|---|---|
| `gpt-4.1` | ~$0.26 |
| `gpt-5-mini` | ~$0.06 |
| `gpt-4.1-mini` | ~$0.05 |
| `gpt-4o-mini` | ~$0.02 |

Switch per run with `--provider openai --model gpt-4.1-mini`. The local filter and OpenAlex enrichment are free regardless, so most of your target list is triaged before a single token is spent. Unknown model names fall back to `gpt-4.1` pricing for the estimate — add them to `MODEL_PRICES` in `outreach/config.py` for accuracy.

---

## Testing

```bash
python tests/make_fixtures.py       # optional; the suites build these on demand
python tests/smoke_test.py          # fully mocked, no network, no spend
python tests/openai_stub_test.py    # real OpenAI SDK against a local stub server
```

Both suites run on a fresh clone with **no `.env` and no API key** — they fall back to synthetic fixtures (`tests/fixtures/`) generated on demand. If your `.env` points at real files, those are used instead, so the same tests double as a check of your own setup. CI runs them on Python 3.10, 3.12, and 3.13.

`smoke_test.py` covers resume parsing, Excel round-trips, filter behaviour, cost maths on both free and paid providers, a mocked LLM pass, early abort on repeated API failures, draft formatting repair, the humanising layer, idempotent column writes, attachment handling, resume-safety on interrupted sends, `.eml` export, scraper extraction, block detection, email verification, discovery batch planning and resume fingerprints, append-only workbook growth, institution matching for `recheck`, skipping already-sent rows (including ones parked in the pending sidecar), and the rule that `--apply` never replaces an address that already passed.

`openai_stub_test.py` boots a local HTTP server, points the real `openai` SDK at it, and asserts the request shape, cached-token accounting, temperature omission for reasoning models, truncation handling, **capability downgrade against a restrictive gateway**, and Groq provider wiring.

---

## Sending etiquette

Cold emails to professors work when they're specific and sparse. Read every draft before sending — the LLM is grounded on real OpenAlex publications, but you are the one signing it, and the `Review Flags` column exists because models do occasionally invent a credential. Keep `DAILY_SEND_CAP` modest, send from your university address, attach your CV, and use `--top 10` rather than mailing an entire faculty.

### When sends start failing

University relays throttle aggressively. If a message is refused or the socket drops, the mailer reconnects once and retries; after three consecutive failures it stops the run so the untouched rows stay sendable. Failed rows are never marked as sent, so re-running the same command retries exactly those rows and skips the successes.

If you see `SMTPSenderRefused` or repeated `SMTPServerDisconnected`, the relay is almost certainly rate-limiting you. Raise `SEND_DELAY_MIN`/`SEND_DELAY_MAX` (300/600 is safe for a university server), lower `DAILY_SEND_CAP`, and send in small batches with `--top 5`. Also confirm `SMTP_FROM` is exactly the address `SMTP_USER` is allowed to send as — most relays refuse any mismatch.

### The spreadsheet is the database

There is no separate database — the workbook at `TARGET_XLSX` holds everything, and the `Send Status` column is the only record of who has been contacted. Rows marked `sent` or `review-sent` are skipped forever; anything else (blank, `dry-run`, `failed: …`) is still a candidate. So:

- `--top 50` after a `--top 10` run mails the next 40, not the first 10 again.
- Editing or clearing `Send Status` by hand *will* change who gets mailed — clearing a `sent` cell re-sends that email.
- Adding rows with a draft and an email address adds new targets; deleting rows removes them.
- `--resend` deliberately ignores `Send Status` and mails everything matching the filters.

Because that column is the only safeguard, `send --live` refuses to start if the workbook is open in Excel, and if the file becomes locked mid-run the statuses are parked in `<workbook>.xlsx.pending-status.json` and applied on the next run instead of being lost. Rows parked there count as sent everywhere — `send`, `verify` and `recheck` all skip them.

`verify` and `recheck` leave already-mailed rows untouched by default (pass `--include-sent` to override), so re-checking a list you have partly worked through never rewrites the addresses you actually used.

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

Every step is resumable: interrupt it and re-run the same command. Close the workbook in Excel before any step that writes to it.

---

## License

MIT — see [LICENSE](LICENSE).

