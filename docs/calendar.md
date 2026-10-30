# Google Calendar setup

Agnostos uses Google Calendar for two things when it sends meeting requests (see [Funding follow-ups and meeting requests](https://github.com/Avinashistoocool/Agnostos-v2#funding-follow-ups-and-meeting-requests)):

- **Choosing slots.** It never proposes a time when you're already busy.
- **Holding slots.** When a reply goes out, each proposed time is added to your calendar as a tentative **HOLD: call with &lt;professor&gt;** event.

The setup is optional. Without it, meeting requests still go out; only the busy check and the holds are skipped.

It takes about 5 minutes and is done once.

---

## 1. Use the right Google account

Do every step while signed in to the **personal Gmail whose calendar you want the holds on**. Check the avatar in the top-right of the Cloud Console.

> **Most common failure: `Error 403: org_internal`.** "Access blocked: &lt;app&gt; can only be used within its organization" means the Cloud project belongs to a Google Workspace organisation (a university or company account, or an org you created) and the app's audience is **Internal**. A personal Gmail can't sign in to an Internal app. Fix it in step 4 by making it **External**, or create the project with **Location: No organization**.

## 2. Create a project

1. Open <https://console.cloud.google.com/projectcreate>.
2. Give it any name, e.g. `agnostos`.
3. Set **Location / Organization** to **No organization** if you can.
4. Click **Create**, then make sure the new project is selected in the top bar.

## 3. Enable the Calendar API

Open <https://console.cloud.google.com/apis/library/calendar-json.googleapis.com> and click **Enable**.

## 4. Configure the consent screen (Google Auth Platform)

1. Open <https://console.cloud.google.com/auth/overview> and click **Get started**.
2. **App name:** anything (e.g. `Agnostos`). **Support email:** your Gmail.
3. **Audience:** choose **External**.
4. **Contact information:** your Gmail. Accept the policy and click **Create**.
5. Open <https://console.cloud.google.com/auth/audience>:
   - **User type** must read **External**. If it says Internal, click **Make external** and choose **Testing**, then **Confirm**.
   - Under **Test users**, click **Add users**, add the Gmail you'll sign in with, then **Save**.

"Testing" needs no review by Google. Only the test users you list can sign in, which is exactly what you want.

## 5. Create a Desktop OAuth client

1. Open <https://console.cloud.google.com/auth/clients> and click **Create client**.
2. **Application type:** **Desktop app**. **Name:** anything.
3. Click **Create**, then **Download JSON**.
4. Save the file as `credentials.json` in the repo root, next to `README.md`, replacing any old one. Or set `GOOGLE_CLIENT_SECRET=path\to\file.json` in `.env`.

`credentials.json` and the token are git-ignored. Never commit them.

## 6. Sign in once

```bash
python -m outreach.cli calendar-auth
```

A browser opens:

1. Pick your Gmail.
2. You'll see **"Google hasn't verified this app"**. Click **Continue**; it's your own app.
3. Allow access to Google Calendar.

The terminal then prints `Authorised. Calendar: <your email> (<timezone>)`. The token is saved to `output/gcal_token.json` and refreshes itself, so you won't be asked again.

## 7. Settings (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `GOOGLE_CLIENT_SECRET` | `credentials.json` | Path to the OAuth client JSON |
| `GOOGLE_CALENDAR_ID` | `primary` | Calendar to check and write holds to |
| `MEET_MINUTES` | `20` | Call length |
| `MEET_LEAD_DAYS` | `2` | Earliest slot is this many days out |
| `MEET_THEIR_HOURS` | `9-17` | Professor's local hours a slot must fit in |
| `MEET_MY_HOURS` | `13-23` | Your hours (in `MEET_MY_TZ`) a slot must fit in |
| `MEET_MY_TZ` | `Asia/Kolkata` | Your timezone |
| `MEET_LINK` | — | Optional fixed Meet/Zoom link to include |

## Switching accounts

To put holds on a different Google account:

1. Delete `output/gcal_token.json`.
2. If the new account isn't a test user, add it in step 4. If it's in a different project, also replace `credentials.json`.
3. Run `python -m outreach.cli calendar-auth` again.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Error 403: org_internal` | App audience is Internal. Go to [Audience](https://console.cloud.google.com/auth/audience), click **Make external**, choose **Testing**, and add yourself as a test user. Or use a project with *No organization*. |
| `Error 403: access_denied` | The account you picked isn't a test user. Add it under **Test users**. |
| `Google Calendar not authorised` | Run `calendar-auth`. The token is missing or was deleted. |
| `OAuth client file not found` | Save the downloaded JSON as `credentials.json` in the repo root, or set `GOOGLE_CLIENT_SECRET`. |
| `invalid_grant` on a later run | The token was revoked or expired (Testing-mode tokens can expire after 7 days). Delete `output/gcal_token.json` and run `calendar-auth` again. |
| Holds land on the wrong calendar | You signed in with another account. See *Switching accounts*. |
