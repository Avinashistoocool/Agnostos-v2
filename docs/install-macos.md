# Agnostos on macOS

See also: [FAQ](faq.md) · [Diagnostics](diagnostics.md)

This guide tells you how to set up and use Agnostos each day on macOS 12 or later, on Apple Silicon or Intel. Agnostos runs as a local command-line tool.

---

## 1. Install the prerequisites

Use Homebrew (https://brew.sh):

```bash
brew install python@3.12 git
python3 --version
```

> **If you use the python.org installer:** that Python has **no SSL certificates**. Thus, each connection fails with
> `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:...)`.
> To fix this one time, double-click `/Applications/Python 3.x/Install Certificates.command`.
> Agnostos also installs `truststore`, so that it reads the macOS Keychain directly. See Troubleshooting.

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

In each new terminal, run `source .venv/bin/activate` before you use `python -m outreach.cli ...`.

## 4. Configure `.env`

```bash
cp .env.example .env
open -e .env          # or: nano .env
```

Fill in **section 1** as a minimum. Use full macOS paths:

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

> **Gmail / iCloud:** use an app password. For Gmail, make one at https://myaccount.google.com/apppasswords. For iCloud, go to appleid.apple.com â†’ Sign-In and Security â†’ App-Specific Passwords. iCloud SMTP is `smtp.mail.me.com` on port 587 with `starttls`.

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
| Review copies to you | `python -m outreach.cli send --review --top 3` |
| Send for real, at intervals | `python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait` |
| Progress | `python -m outreach.cli stats` |
| Find replies and bounces | `python -m outreach.cli check-replies` |
| Write follow-up drafts from full threads | `python -m outreach.cli replies` |
| Send approved follow-ups | `python -m outreach.cli replies --send --live` |

Close the workbook in Excel or Numbers before a live send. The tool never sends again to rows that have the status sent, unless you use `--resend`.

## 7. Send automatically each weekday (launchd)

Make the file `~/Library/LaunchAgents/com.agnostos.send.plist`. Replace `<you>` with your username:

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

Load the file and manage the job:
```bash
launchctl load  ~/Library/LaunchAgents/com.agnostos.send.plist
launchctl start com.agnostos.send                     # run now
tail -f output/daily_send.log                         # live log
launchctl unload ~/Library/LaunchAgents/com.agnostos.send.plist   # stop
```

The `caffeinate -i` wrapper prevents idle sleep of the Mac while a send is active.

> If the repository is in `~/Desktop` or `~/Documents`, open **System Settings â†’ Privacy & Security â†’ Full Disk Access**. Add `/usr/bin/caffeinate` and the `python` of the venv. Without this step, macOS can prevent launchd from reading those folders.

## 8. Keep the Mac awake

- For a manual run, start the command with `caffeinate -i`:
  `caffeinate -i python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait`
- **When you close the lid, the Mac goes to sleep**, unless it has power and an external display (clamshell mode). Alternatively, run `sudo pmset -a disablesleep 1`. Later, undo it with `sudo pmset -a disablesleep 0`.

If the Mac goes to sleep during a run, no data is lost. The tool saves each sent email immediately. The wait timers use the wall clock, thus they continue correctly after the Mac wakes.

## 9. Monitor remotely (optional)

Turn on **System Settings â†’ General â†’ Sharing â†’ Remote Login**. Install Tailscale. Then connect from a different device:
```bash
ssh <you>@<tailscale-ip>
cd ~/Desktop/Agnostos-v2 && source .venv/bin/activate
python -m outreach.cli stats
tail -f output/daily_send.log
```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED ... (_ssl.c:1144)` or a similar error | 1) `pip install -U truststore certifi` 2) run `Install Certificates.command` (python.org builds) 3) `python -m outreach.cli tls-check`. Behind a company proxy, `export SSL_CERT_FILE=/path/to/root.pem` |
| `SMTPAuthenticationError` | Use an app password. Check `SMTP_USER` |
| `SMTPServerDisconnected` | The tool connects again automatically. If the problem continues, increase `SEND_DELAY_MIN` and decrease `DAILY_SEND_CAP` |
| `xcrun: error` during pip install | `xcode-select --install` |
| `zsh: command not found: python` | Use `python3`, or activate the venv |
| The launchd job never runs | Check Full Disk Access (see section 7), then `launchctl list \| grep agnostos` |
| The tool sent few emails | `python -m outreach.cli stats` gives the reasons for skipped rows |
