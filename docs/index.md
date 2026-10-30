# Agnostos

**Resume-driven outreach for research internships.** Agnostos is a free, open-source command-line tool
that helps students find research internships:

- **Who should I write to?** It ranks a professor list against your resume locally, for free, or builds
  the list for you from a research topic using the OpenAlex paper index.
- **What have they worked on lately?** It pulls each professor's recent first- and last-author papers.
- **What do I say?** One language-model call per professor returns an acceptance estimate and a short,
  specific, honest draft. Common AI tells are stripped out and unverifiable claims are flagged.
- **Is the address right?** It checks every address and can find the one each professor publishes on
  their own page.
- **When do I send it?** Slowly, from your own inbox, during each professor's working hours.
- **Did they answer?** It tracks replies, auto-replies and bounces, and drafts follow-ups for you to approve.

## Get it

[Source on GitHub](https://github.com/Avinashistoocool/Agnostos-v2){ .md-button .md-button--primary }
[Technical report (PDF)](Agnostos_Technical_Report.pdf){ .md-button }

```bash
git clone https://github.com/Avinashistoocool/Agnostos-v2
cd Agnostos-v2
pip install -r requirements.txt
cp .env.example .env                       # Windows: copy .env.example .env
python -m outreach.cli profile             # check resume parsing
python -m outreach.cli run --mode list     # score + draft into your xlsx
python -m outreach.cli send --dry-run      # preview the emails
```

The full command reference is in the
[README](https://github.com/Avinashistoocool/Agnostos-v2#readme).

## Documentation

| | |
|---|---|
| Setup: [Windows](install-windows.md) · [macOS](install-macos.md) · [Linux](install-linux.md) | Step-by-step installation and daily use for each operating system |
| [FAQ](faq.md) | Common questions about costs, sending, replies and safety |
| [Diagnostics](diagnostics.md) | Health checks and fixes for every common error message |
| [Google Calendar](calendar.md) | One-time setup for meeting-slot checks and calendar holds |
| [Technical report (PDF)](Agnostos_Technical_Report.pdf) | Architecture and every scoring rule: matcher, discovery ranking, cost estimate, AI-tell score, address confidence, scheduling |

!!! note
    Agnostos drafts; you decide. Nothing is sent without `--live`, and every draft is written to your
    spreadsheet first so you can read and edit it. The acceptance percentage is a model's estimate for
    ordering your list, not a statistical probability.
