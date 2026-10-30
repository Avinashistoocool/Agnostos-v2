# Agnostos on macOS

See also: [FAQ](faq.md) · [Diagnostics](diagnostics.md)

This guide covers setup and daily use on macOS 12 or later, on Apple Silicon or Intel. It runs Agnostos as a local command-line tool.

---

## 1. Install the prerequisites

Use Homebrew (https://brew.sh):

```bash
brew install python@3.12 git
python3 --version
```

> **If you use the python.org installer instead:** it ships **without any SSL certificates**. Every connection then fails with
> `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:...)`.
> Fix it once by double-clicking `/Applications/Python 3.x/Install Certificates.command`.
> Agnostos also installs `truststore`, so it reads the macOS Keychain directly. See Troubleshooting.

## 2. Get the code

```bash
cd ~/Desktop
git clone https://github.com/Avinashistoocool/Agnostos-v2.git
cd Agnostos-v2
```

## 3. Create a virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Run `source .venv/bin/activate` in every new terminal before using `python -m outreach.cli ...`.

## 4. Configure `.env`

```bash
cp .env.example .env
open -e .env          # or: nano .env
```

Fill in **section 1** at minimum. Use full macOS paths:

```ini
RESUME_PATH=/Users/<you>/Documents/CV.pdf
TARGET_XLSX=/Users/<you>/Desktop/Agnostos-v2/output/professors.xlsx
ATTACHMENTS=/Users/<you>/Documents/research_CV.pdf

LLM_PROVIDER=groq                # free; or openai
GROQ_API_KEY=gsk_...
# OPENAI_API_KEY=sk-...
# DRAFT_MODEL=gpt-5-mini

SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_SECURITY=ssl                # ssl on 465, starttls on 587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char app password>
SMTP_FROM=you@gmail.com

DAILY_SEND_CAP=40
SEND_DELAY_MIN=300
SEND_DELAY_MAX=600
SEND_LOCAL_WINDOW=9-17
```

> **Gmail / iCloud:** use an app password. For Gmail, create one at https://myaccount.google.com/apppasswords. For iCloud, go to appleid.apple.com â†’ Sign-In and Security â†’ App-Specific Passwords. iCloud SMTP is `smtp.mail.me.com` on port 587 with `starttls`.

## 5. Check the setup

```bash
python -m outreach.cli profile
python -m outreach.cli models
python -m outreach.cli tls-check     # must show "ok" for every host
```

## 6. The workflow

| Step | Command |
|---|---|
| Find professors | `python -m outreach.cli discover --count 300 --batches 3 --verify-emails` |
| Fix emails | `python -m outreach.cli verify --repair --apply` |
| Score and draft | `python -m outreach.cli run --mode list --max-professors 300` |
| Preview (sends nothing) | `python -m outreach.cli send --dry-run` |
| Review copies to yourself | `python -m outreach.cli send --review --top 3` |
| Send for real, paced | `python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait` |
| Progress | `python -m outreach.cli stats` |
| Detect replies and bounces | `python -m outreach.cli check-replies` |
| Draft follow-ups from full threads | `python -m outreach.cli replies` |
| Send approved follow-ups | `python -m outreach.cli replies --send --live` |

Close the workbook in Excel or Numbers before a live send. Already-sent rows are never mailed again unless you pass `--resend`.

## 7. Send automatically every weekday (launchd)

Create `~/Library/LaunchAgents/com.agnostos.send.plist`. Replace `<you>` with your username:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agnostos.send</string>
  <key>WorkingDirectory</key><string>/Users/<you>/Desktop/Agnostos-v2</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>/Users/<you>/Desktop/Agnostos-v2/.venv/bin/python</string>
    <string>-u</string><string>-m</string><string>outreach.cli</string><string>send</string>
    <string>--live</string><string>--yes</string><string>--limit</string><string>40</string>
    <string>--local-window</string><string>9-17</string><string>--wait</string>
  </array>
  <key>EnvironmentVariables</key><dict><key>PYTHONIOENCODING</key><string>utf-8</string></dict>
  <key>StartCalendarInterval</key><array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>/Users/<you>/Desktop/Agnostos-v2/output/daily_send.log</string>
  <key>StandardErrorPath</key><string>/Users/<you>/Desktop/Agnostos-v2/output/daily_send.log</string>
</dict></plist>
```

Load it and manage it:
```bash
launchctl load  ~/Library/LaunchAgents/com.agnostos.send.plist
launchctl start com.agnostos.send                     # run now
tail -f output/daily_send.log                         # live log
launchctl unload ~/Library/LaunchAgents/com.agnostos.send.plist   # stop
```

The `caffeinate -i` wrapper keeps the Mac from idle-sleeping while a send is running.

> If you keep the repo in `~/Desktop` or `~/Documents`, open **System Settings â†’ Privacy & Security â†’ Full Disk Access** and add `/usr/bin/caffeinate` and the venv's `python`. Without this, launchd can be blocked from reading those folders.

## 8. Keep the Mac awake

- During a manual run, start the command with `caffeinate -i`:
  `caffeinate -i python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait`
- **Closing the lid sleeps the Mac anyway** unless it is on power with an external display attached (clamshell mode). Alternatively, run `sudo pmset -a disablesleep 1` and undo it later with `sudo pmset -a disablesleep 0`.

If the Mac sleeps mid-run, nothing is lost. Each sent email is saved immediately, and the wait timers use the wall clock, so they resume correctly after wake.

## 9. Monitor remotely (optional)

Turn on **System Settings â†’ General â†’ Sharing â†’ Remote Login**. Install Tailscale, then connect from another device:
```bash
ssh <you>@<tailscale-ip>
cd ~/Desktop/Agnostos-v2 && source .venv/bin/activate
python -m outreach.cli stats
tail -f output/daily_send.log
```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED ... (_ssl.c:1144)` or similar | 1) `pip install -U truststore certifi` 2) run `Install Certificates.command` (python.org builds) 3) `python -m outreach.cli tls-check`. Behind a corporate proxy, `export SSL_CERT_FILE=/path/to/root.pem` |
| `SMTPAuthenticationError` | Use an app password. Check `SMTP_USER` |
| `SMTPServerDisconnected` | Reconnects automatically. If it persists, raise `SEND_DELAY_MIN` and lower `DAILY_SEND_CAP` |
| `xcrun: error` during pip install | `xcode-select --install` |
| `zsh: command not found: python` | Use `python3`, or activate the venv |
| launchd job never runs | Check Full Disk Access (see section 7), then `launchctl list \| grep agnostos` |
| Few emails sent | `python -m outreach.cli stats` explains why rows were skipped |
