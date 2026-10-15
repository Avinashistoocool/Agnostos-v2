# Agnostos on Windows

See also: [FAQ](FAQ.md) · [Diagnostics](DIAGNOSTICS.md)

This guide covers setup and daily use on Windows 10 or 11. It runs Agnostos as a local command-line tool.

---

## 1. Install the prerequisites

1. **Python 3.10 or newer.** Get it from https://www.python.org/downloads/windows/ and tick **"Add python.exe to PATH"** in the installer.
   Check it worked:
   ```powershell
   python --version
   ```
2. **Git.** Get it from https://git-scm.com/download/win.

## 2. Get the code

```powershell
cd $HOME\Desktop
git clone https://github.com/Avinashistoocool/Agnostos-v2.git
cd Agnostos-v2
```

## 3. Create a virtual environment and install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

If PowerShell says *running scripts is disabled*, run this once and then activate again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Activate the venv (`.\.venv\Scripts\Activate.ps1`) in every new terminal before you run any `python -m outreach.cli ...` command.

## 4. Configure `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in **section 1** at minimum. Use full Windows paths:

```ini
RESUME_PATH=C:\Users\<you>\Documents\CV.pdf
TARGET_XLSX=C:\Users\<you>\Desktop\Agnostos-v2\output\professors.xlsx
ATTACHMENTS=C:\Users\<you>\Documents\research_CV.pdf

LLM_PROVIDER=groq                # free; or openai
GROQ_API_KEY=gsk_...
# OPENAI_API_KEY=sk-...          # if LLM_PROVIDER=openai
# DRAFT_MODEL=gpt-5-mini

SMTP_HOST=smtp.gmail.com         # university: e.g. smtp.iitd.ac.in
SMTP_PORT=465
SMTP_SECURITY=ssl                # ssl on 465, starttls on 587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char app password>
SMTP_FROM=you@gmail.com
```

> **Gmail:** turn on 2-Step Verification, then create an app password at https://myaccount.google.com/apppasswords. Your normal password will not work.

Recommended pacing, so your mailbox doesn't get throttled:
```ini
DAILY_SEND_CAP=40
SEND_DELAY_MIN=300
SEND_DELAY_MAX=600
SEND_LOCAL_WINDOW=9-17
```

## 5. Check the setup

```powershell
python -m outreach.cli profile       # what was read from your resume
python -m outreach.cli models        # which models your key can use
python -m outreach.cli tls-check     # SMTP / IMAP / API certificates
```

## 6. The workflow

| Step | Command | What it does |
|---|---|---|
| Find professors | `python -m outreach.cli discover --count 300 --batches 3 --verify-emails` | Searches OpenAlex for active researchers in your topics and writes them to `output\professors.xlsx` |
| Fix emails | `python -m outreach.cli verify --repair --apply` | Checks every address and replaces bad ones with the address on their university page |
| Score and draft | `python -m outreach.cli run --mode list --max-professors 300` | Scores each match and drafts one honest email per professor |
| Preview | `python -m outreach.cli send --dry-run` | Prints the drafts. Nothing is sent |
| Review in your inbox | `python -m outreach.cli send --review --top 3` | Mails 3 drafts **to yourself** |
| Send for real | `python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait` | Sends paced emails, only during each professor's local working hours |
| Progress | `python -m outreach.cli stats` | Shows drafted, sent, replied and bounced counts, and why rows were skipped |
| Replies | `python -m outreach.cli check-replies` | Marks replied, auto-reply and bounced rows in the workbook |
| Draft follow-ups | `python -m outreach.cli replies` | Reads each full thread and drafts a reply into `output\reply_queue.json` |
| Send follow-ups | `python -m outreach.cli replies --send --live` | Sends the queue items you set to `"approved": true` |

Important rules:
- **Close the workbook in Excel before a live send.** If it is open, statuses are saved to a sidecar file and merged on the next run. Nobody gets mailed twice.
- Rows already marked `sent` are never sent again unless you pass `--resend`.

## 7. Send automatically every weekday (Task Scheduler)

This registers a task that sends up to 40 emails every weekday at 12:30. In IST, that covers the European morning.

```powershell
$repo = "$HOME\Desktop\Agnostos-v2"
$py   = "$repo\.venv\Scripts\python.exe"
$cmd  = "cd /d `"$repo`" && set PYTHONIOENCODING=utf-8 && `"$py`" -u -m outreach.cli send --live --yes --limit 40 --local-window 9-17 --wait >> output\daily_send.log 2>&1"
$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $cmd"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "12:30"
$set     = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 14) -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Agnostos daily outreach send" -Action $action -Trigger $trigger -Settings $set -Force
```

Manage the task:
```powershell
Start-ScheduledTask   -TaskName "Agnostos daily outreach send"     # run now
Get-ScheduledTaskInfo -TaskName "Agnostos daily outreach send"     # last/next run
Unregister-ScheduledTask -TaskName "Agnostos daily outreach send" -Confirm:$false
Get-Content output\daily_send.log -Tail 20 -Wait                   # live log
```

## 8. Keep the laptop awake

A paced send runs for hours, and closing the lid normally puts the laptop to sleep. Either:

- Run these in an **Administrator** PowerShell to keep it running on charger with the lid closed:
  ```powershell
  powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
  powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
  powercfg /setactive SCHEME_CURRENT
  ```
- Or install **Microsoft PowerToys â†’ Awake** and set it to "Keep awake indefinitely".

If the machine does sleep, nothing is lost. Each sent email is saved to the workbook immediately. The send continues after you wake the machine, or on the next scheduled run.

## 9. Monitor remotely (optional)

1. Install Tailscale on the PC and on your phone, and sign in on both.
2. Enable the SSH server once, in an **Administrator** PowerShell:
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd; Set-Service sshd -StartupType Automatic
   ```
3. From the phone or another computer, connect with `ssh <windows-user>@<tailscale-ip>` (find the IP with `tailscale ip -4`). Then run:
   ```powershell
   cd $HOME\Desktop\Agnostos-v2
   .\.venv\Scripts\python.exe -m outreach.cli stats
   Get-Content output\daily_send.log -Tail 20 -Wait
   ```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | `pip install -U truststore certifi`, then `python -m outreach.cli tls-check`. Behind antivirus or a proxy that inspects HTTPS, set `SSL_CERT_FILE` to its root certificate |
| `SMTPAuthenticationError` | Use an app password, not your login password. Check `SMTP_USER` |
| `SMTPServerDisconnected` / read timed out | The server drops idle sessions. Agnostos reconnects on its own. If it keeps happening, raise `SEND_DELAY_MIN` and lower `DAILY_SEND_CAP` |
| `SMTPSenderRefused` | `SMTP_FROM` must be the same mailbox as `SMTP_USER` |
| `response truncated` from the LLM | Fixed automatically for gpt-5 and o-series models. For other models, raise `MAX_OUTPUT_TOKENS` |
| Workbook "is open in Excel" | Close Excel, then re-run |
| Accented names print as `?` | `$env:PYTHONIOENCODING="utf-8"` |
| Few emails sent | Run `stats`. It lists the reason, for example rows with no email, low match scores, the `MAX_PROFESSORS` cap, or the daily cap |
