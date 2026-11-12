# Google Calendar setup

Agnostos uses Google Calendar for two tasks when it sends meeting requests (see [Funding follow-ups and meeting requests](https://github.com/Avinashistoocool/Agnostos-v2#funding-follow-ups-and-meeting-requests)):

- **Selection of slots.** The tool never proposes a time when you are busy.
- **Hold of slots.** When a reply goes out, the tool adds each proposed time to your calendar as a tentative **HOLD: call with &lt;professor&gt;** event.

The setup is optional. Without it, meeting requests still go out. The tool skips only the busy check and the holds.

The setup takes about 5 minutes, and you do it one time.

---

## 1. Use the correct Google account

Do all the steps while you are signed in to the **personal Gmail account whose calendar must get the holds**. Look at the avatar in the top-right corner of the Cloud Console.

> **Most frequent failure: `Error 403: org_internal`.** The message is "Access blocked: &lt;app&gt; can only be used within its organization". It means that the Cloud project is part of a Google Workspace organisation, and the audience of the app is **Internal**. Such an organisation is a university or company account, or an organisation that you made. A personal Gmail account cannot sign in to an Internal app. To fix this, set the audience to **External** in step 4. Alternatively, make the project with **Location: No organization**.

## 2. Create a project

1. Open <https://console.cloud.google.com/projectcreate>.
2. Give the project a name, for example `agnostos`.
3. If possible, set **Location / Organization** to **No organization**.
4. Click **Create**.
5. Make sure that the top bar shows the new project.

## 3. Enable the Calendar API

Open <https://console.cloud.google.com/apis/library/calendar-json.googleapis.com> and click **Enable**.

## 4. Configure the consent screen (Google Auth Platform)

1. Open <https://console.cloud.google.com/auth/overview> and click **Get started**.
2. **App name:** any name (for example, `Agnostos`). **Support email:** your Gmail address.
3. **Audience:** select **External**.
4. **Contact information:** your Gmail address. Accept the policy and click **Create**.
5. Open <https://console.cloud.google.com/auth/audience>:
   - **User type** must show **External**. If it shows Internal, click **Make external**, select **Testing**, then click **Confirm**.
   - Under **Test users**, click **Add users**. Add the Gmail address that you will use to sign in, then click **Save**.

Google does not review apps in "Testing" mode. Only the test users that you list can sign in. This is the correct configuration for this tool.

## 5. Create a Desktop OAuth client

1. Open <https://console.cloud.google.com/auth/clients> and click **Create client**.
2. **Application type:** **Desktop app**. **Name:** any name.
3. Click **Create**, then click **Download JSON**.
4. Save the file as `credentials.json` in the root of the repository, next to `README.md`. Replace an old file if there is one. Alternatively, set `GOOGLE_CLIENT_SECRET=path\to\file.json` in `.env`.

Git ignores `credentials.json` and the token. Never commit them.

## 6. Sign in one time

```bash
python -m outreach.cli calendar-auth
```

A browser opens:

1. Select your Gmail account.
2. You see **"Google hasn't verified this app"**. Click **Continue**, because it is your own app.
3. Give access to Google Calendar.

Then the terminal shows `Authorised. Calendar: <your email> (<timezone>)`. The tool saves the token to `output/gcal_token.json`, and the token refreshes itself. Thus, the tool does not ask you again.

## 7. Settings (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `GOOGLE_CLIENT_SECRET` | `credentials.json` | Path to the OAuth client JSON |
| `GOOGLE_CALENDAR_ID` | `primary` | Calendar that the tool checks and that gets the holds |
| `MEET_MINUTES` | `20` | Length of the call |
| `MEET_LEAD_DAYS` | `2` | The first slot is this number of days in the future |
| `MEET_THEIR_HOURS` | `9-17` | Local hours of the professor that must contain the slot |
| `MEET_MY_HOURS` | `13-23` | Your hours (in `MEET_MY_TZ`) that must contain the slot |
| `MEET_MY_TZ` | `Asia/Kolkata` | Your time zone |
| `MEET_LINK` | — | Optional fixed Meet/Zoom link to include |

## Switching accounts

To put holds on a different Google account:

1. Delete `output/gcal_token.json`.
2. If the new account is not a test user, add it in step 4. If it is in a different project, also replace `credentials.json`.
3. Run `python -m outreach.cli calendar-auth` again.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Error 403: org_internal` | The audience of the app is Internal. Go to [Audience](https://console.cloud.google.com/auth/audience), click **Make external**, select **Testing**, and add yourself as a test user. Alternatively, use a project with *No organization*. |
| `Error 403: access_denied` | The account that you selected is not a test user. Add it under **Test users**. |
| `Google Calendar not authorised` | The token is missing or deleted. Run `calendar-auth`. |
| `OAuth client file not found` | Save the downloaded JSON as `credentials.json` in the root of the repository, or set `GOOGLE_CLIENT_SECRET`. |
| `invalid_grant` on a subsequent run | The token was revoked or expired (tokens in Testing mode can expire after 7 days). Delete `output/gcal_token.json` and run `calendar-auth` again. |
| The holds go on the wrong calendar | You signed in with a different account. See *Switching accounts*. |
