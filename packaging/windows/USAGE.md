# Agnostos usage and outreach policies

These are the intended operator policies and the relevant beta behavior.
They do not grant permission to bypass verification, approvals, recipient
preferences or provider limits. Read the author-specific limitations in
`README.md` first.

## 1. Set up your own workspace

1. Start Agnostos and use Guest or a local account for initial testing.
2. Complete onboarding: import your resume, review the extracted profile,
   select interests/targets, configure email and an LLM provider, then review
   funding and sending limits.
3. Correct every parsed name, course, date, project, result and affiliation.
   Never invent grades, research experience, funding or programme eligibility.
4. Configure your own SMTP/IMAP or Gmail authorization and LLM API key.
   Use the connection-test controls before attempting live actions.
5. In **Settings > Workspace**, check where the app saves its records.

Do not use the author's personal settings, funding promises or application
answers as your own. For this beta, a different user must also have the
author-specific drafting instructions corrected before using live outreach.

## 2. Find contacts before drafting

Use **Pipeline > Discover professors** first. Then inspect the **Professors**
list and verify the identities, affiliations and addresses.

An empty workbook field uses the workspace's default
`output\professors.xlsx`, creating an empty workbook when needed. Creating a
workbook does not discover anyone. **Match & draft** needs actual professor rows.

Research relevance matters more than prestige. Check that the person is active,
works in the field and can plausibly supervise the proposed project. Institution
rankings and generated probability scores are not reliable admissions forecasts.

## 3. Draft, inspect, then approve

Use **Match & draft**, then inspect the complete subject and body for each
recipient. Check:

- The salutation matches the person.
- Any paper title and attribution are real.
- Your results and skills are true and relevant.
- The proposed dates and call times are still in the future.
- The request is specific and respectful.
- Links belong to you and work.
- Every promised attachment is present and correct.

Prefer a brief, factual first email with one concrete request. Do not pretend
to have read a paper, manufacture admiration or promise self-funding. Editing
for clearer language is not a guarantee of human authorship and must not be used
to evade a programme's ban on AI-written application answers.

Legacy letters, queued replies and coordinator messages require approval.
Read the full text before setting an approval, not just a summary or name.

## 4. Sending policy

| Policy | Behavior / action |
|---|---|
| Preview first | Start with a dry run. A dry run is not delivery. |
| Explicit live action | The desktop asks for typed confirmation and relays the worker's confirmation prompt. Live sending is not the default. |
| Reasonable volume | Cold sends are capped at 40 per day; your configured cap may be lower. Do not treat 40 as a delivery target. |
| Per-domain pacing | Default: at most 3 cold emails per institution domain over 7 days. All of `cern.ch` counts together, not separately per group. |
| Recipient hours | Keep weekday recipient-local 09:00-17:00 windows. Enable waiting only when you want the job to remain open. |
| Delays | Keep paced gaps between messages; the desktop rejects live delays below 60 seconds. |
| Address safety | Skip bounced, suspect and unverified addresses, identity mismatches and other guard-held recipients. Do not bypass these holds. |
| No duplicate campaigns | Do not run competing senders on the same workspace or send the same message from a second account to chase a non-response. |
| Funding | Set the funding answer truthfully. With `CAN_SELF_FUND=no`, offers to pay your own expenses are blocked. |
| Attachments | Cold emails default to no CV attachment. Replies may attach promised files; explicit per-row attachment settings can override defaults. Review these carefully. |
| Rejections | Respect clear refusals and requests not to contact someone. Do not follow a refusal with repeated call or funding requests. |

The author stopped the identical Gmail-resend workflow. The beta may still
expose a Resend command; its presence is not a recommendation to use it.

## 5. Verification must not delay mailing

Senders skip unverified contacts, store them once in
`output\verification_queue.json`, and continue with verified rows. Skipped
contacts do not consume legacy delivery slots. No address-search job should
be started as part of a send.

Run **Verify email addresses** separately with its **Deferred** option. Preview
first; enable Repair/Apply only when ready to update the queued addresses.
Workbooks held by a sender are postponed rather than edited concurrently.
A changed legacy recipient loses its approval and must be reviewed again.

For a separately installed source checkout only (Python is not required for
the desktop installer):

```powershell
python -m outreach.cli verify --deferred --dry-run
python -m outreach.cli verify --deferred --repair --apply --top 20
```

This queue is not an automatic promise to verify or send at a particular time.
The installed app does not install a nightly verification task for you.

## 6. Review replies and conversations

Check incoming mail before planning follow-ups. Open **Conversations** to read
the full thread, then **Replies** to inspect and approve a response.

Confirm which sender account belongs to the thread. Answer actual questions
and send requested documents before asking for another call. Do not send stale
drafts after a newer professor response.

For a non-response, consider one short, relevant follow-up after roughly
10-14 days. Do not assume a five-day delay means rejection. Do not repeat the
original message or create an automatic sequence after a clear refusal.

## 7. Progress, logs and unattended operation

**Activity** normally shows progress and results rather than raw terminal logs.
**Settings > About > Developer mode** exposes logs for troubleshooting.
Logs may contain personal correspondence: redact them before sharing.

To confirm delivery, check the message's recorded sent status and timestamp.
"Running" can mean sleeping for a window; "approved" means allowed, not sent.
An SMTP success does not prove inbox placement or that the recipient read it.

The author has separate Windows scheduled tasks, but these are not bundled in
the installer. Closing the desktop stops its engine; do not assume jobs continue.
Keep the PC awake and online for desktop jobs. Unattended operation requires
separately configured recovery, duplicate prevention and monitoring.

## 8. Common issues

- **Google/GitHub says Not set up:** configure your own OAuth application, or
  continue with Guest/local sign-in for testing.
- **Google reports invalid_grant:** reauthorize the affected account. Testing
  mode refresh tokens can expire; use Google's current publishing guidance.
- **No professors found:** Discover first, then Match & draft.
- **OpenAlex rate limit:** provide your own OpenAlex API key and wait as directed.
- **Nothing sent:** inspect approvals, verification status, daily/domain limits,
  recipient hours and the Activity error. Do not raise limits just to clear a queue.
- **Workbook busy/open in Excel:** close Excel or wait for the other job.
- **Bad extracted profile:** fix it before generating drafts; never send an
  incorrect grade, institution, salutation or claimed result.

## 9. Sharing the app

Share only the installer ZIP and these documents. Never include your workspace,
mail queues, `.env`, OAuth tokens, API keys, CV/transcript or private logs.
Do not distribute another user's configured account as a convenient preset.
