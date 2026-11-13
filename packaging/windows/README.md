# Agnostos for Windows - 2.2.0 beta

A desktop application for finding research contacts, reviewing email drafts,
sending approved outreach and tracking conversations.

## What is in this ZIP?

- `Agnostos_2.2.0_x64-setup.exe`: Windows installer, including the Python engine.
- `README.md`: installation, privacy and limitations.
- `USAGE.md`: workflow and sending policies.
- `LICENSE`: project license.

No repository checkout, personal workbooks, CV files, `.env` files, API keys or
OAuth token files are included as separate files in this ZIP. This is not a
backup of the author's workspace.

## Install

1. Extract the ZIP to a normal folder.
2. Run `Agnostos_2.2.0_x64-setup.exe`.
3. Open **Agnostos** from the Windows Start menu.

Windows 10/11 x64 is required. Python, Node.js and Rust do not need to be
installed. The installer downloads Microsoft WebView2 if it is missing, so
installation may require internet access.

The installer is unsigned. Windows may show an unknown-publisher or SmartScreen
warning. Only run a copy you trust; do not disable Windows security globally.
Updates are manual: install a newer build. Automatic updates are not enabled.

## Read this before using live mail

**This is an author-configured beta, not yet a general-purpose outreach release.**
It is suitable for trying the interface and giving feedback, but a different
user should not enable live sending until these limitations are addressed:

- Some drafting instructions and fallback facts explicitly describe the author's
  IIT Delhi background, projects and results. Importing your resume does not
  guarantee all of these are replaced. Editing a CV link alone is not sufficient.
- The default CV link points to the author's portfolio. Replace it with your own;
  never describe a generic homepage as a downloadable CV unless it provides one.
- Programme reminders have fixed author-specific recipients and local paths.
  Do not enable that workflow for another user; recipient configuration needs
  to be generalized first.
- The author's scheduled outreach loops, programme research, contact lists and
  approvals are not installed on another PC.

These are limitations of the software, not problems a README can fix. No
application or email should contain someone else's achievements or identity.

## Accounts and external services

Guest and local email/password accounts are available. A local account is not
a cloud account and does not verify ownership of an email address.

Google/GitHub sign-in requires OAuth client configuration. Gmail sending also
requires the appropriate Gmail authorization. Each tester must use their own
accounts and credentials; do not copy the author's OAuth tokens or `.env`.

The interface and records are local, but network features are not offline:
discovery contacts research/search services, drafting sends relevant resume and
message context to the configured LLM provider, and mail uses SMTP/IMAP or Gmail
authorization. Provider costs, quotas and privacy terms apply. Google Calendar
is used when calendar integration is enabled.

## Where your data lives

The default per-user workspace is:

`%LOCALAPPDATA%\Agnostos\users\<user-id>\workspace`

The application can use another workspace via **Settings > Workspace**.
Treat the workspace, credentials, transcripts, logs and email contents as
private. Do not share that folder or upload it to a public repository.
Guest mode is not password protection, and this beta should not be assumed
to encrypt all local files.

## Current limitations

- Google/GitHub OAuth is not preconfigured for strangers.
- Browser-based scraping is not bundled. Use the supported discovery/list
  workflow rather than scrape mode.
- Publishing an OAuth app does not automatically grant approval for restricted
  scopes. Follow Google's current verification and consent requirements.
- A running window, scheduled task or "approved" row is not proof of delivery.
  Check each message's sent status and timestamp.
- The app does not guarantee replies, funding, placement or admission.

Read `USAGE.md` before configuring any sending workflow.
