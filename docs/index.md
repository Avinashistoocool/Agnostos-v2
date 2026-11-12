# Agnostos

**Research internship outreach that starts from your resume.** Agnostos is a free, open-source command-line tool.
It helps students find research internships:

- **To whom do I write?** The tool compares a list of professors with your resume locally, at no cost, and sorts the list.
  It can also make the list for you from a research topic, with the OpenAlex paper index.
- **On which subjects did they work recently?** The tool gets the recent papers where each professor is the first or last author.
- **What do I write?** One language-model call for each professor gives an acceptance estimate and a short,
  specific and honest draft. The tool removes the usual signs of AI text, and it flags claims that it cannot verify.
- **Is the address correct?** The tool checks each address. It can find the address that each professor publishes on
  their own page.
- **When do I send it?** Slowly, from your own inbox, during the working hours of each professor.
- **Did they answer?** The tool records replies, auto-replies and bounces. It writes follow-up drafts for your approval.

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
| [FAQ](faq.md) | Frequent questions about costs, sending, replies and safety |
| [Diagnostics](diagnostics.md) | Health checks, and solutions for each frequent error message |
| [Google Calendar](calendar.md) | One-time setup for the check of meeting slots and for calendar holds |
| [Technical report (PDF)](Agnostos_Technical_Report.pdf) | Architecture and each scoring rule: matcher, discovery ranking, cost estimate, AI-tell score, address confidence, schedules |

!!! note
    Agnostos writes drafts, and you make the decision. The tool sends nothing without `--live`. It writes each draft
    to your spreadsheet first, so that you can read and edit it. The acceptance percentage is an estimate of a model.
    It is for the sequence of your list. It is not a statistical probability.
