# Agnostos on Windows

See also: [FAQ](faq.md) · [Diagnostics](diagnostics.md)

This guide tells you how to set up and use Agnostos each day on Windows 10 or 11. Agnostos runs as a local command-line tool.

---

## 1. Install the prerequisites

1. **Python 3.10 or newer, including Python 3.15.** Get a stable release from https://www.python.org/downloads/windows/. In the installer, select **"Add python.exe to PATH"**.
   Make sure that the installation is correct:
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
python -m pip install -r requirements.txt
```

The standard dependencies have wheels for Python 3.15 on Windows. Thus, you do **not** need
Visual C++ Build Tools. If pip tries to compile PyYAML, run
`git pull` first. Older versions of Agnostos required PyYAML, and PyYAML has no
wheel for Python 3.15 on Windows. After the update, make a new virtual
environment as shown above, and install the requirements again. Use the same `python`
or `.\.venv\Scripts\python.exe` for the installation and for the CLI commands.

If PowerShell says *running scripts is disabled*, run this command one time. Then activate the venv again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

In each new terminal, activate the venv (`.\.venv\Scripts\Activate.ps1`) before you run a `python -m outreach.cli ...` command.

## 4. Configure `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in **section 1** as a minimum. Use full Windows paths:

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

> **Gmail:** turn on 2-Step Verification. Then make an app password at https://myaccount.google.com/apppasswords. Your usual password does not work.

Recommended speed, so that your mail provider does not limit your mailbox:
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
| Find professors | `python -m outreach.cli discover --count 300 --batches 3 --verify-emails` | Searches OpenAlex for active researchers in your topics, and writes them to `output\professors.xlsx` |
| Fix emails | `python -m outreach.cli verify --repair --apply` | Checks each address, and replaces incorrect addresses with the address on the university page |
| Score and draft | `python -m outreach.cli run --mode list --max-professors 300` | Gives a score to each match, and writes one honest email for each professor |
| Preview | `python -m outreach.cli send --dry-run` | Shows the drafts. It sends nothing |
| Review in your inbox | `python -m outreach.cli send --review --top 3` | Sends 3 drafts **to you** |
| Send for real | `python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait` | Sends emails at intervals, only during the local working hours of each professor |
| Progress | `python -m outreach.cli stats` | Shows the counts of drafted, sent, replied and bounced rows, and the reasons for skipped rows |
| Replies | `python -m outreach.cli check-replies` | Marks replied, auto-reply and bounced rows in the workbook |
| Draft follow-ups | `python -m outreach.cli replies` | Reads each full thread, and writes a draft reply into `output\reply_queue.json` |
| Send follow-ups | `python -m outreach.cli replies --send --live` | Sends the queue items that you set to `"approved": true` |

Important rules:
- **Close the workbook in Excel before a live send.** If it is open, the tool saves the statuses to a sidecar file. It merges them on the next run. No person gets two emails.
- The tool never sends again to rows that have the status `sent`, unless you use `--resend`.

## 7. Send automatically each weekday (Task Scheduler)

This procedure registers a task that sends up to 40 emails each weekday at 12:30. In IST, that time is the European morning.

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

A send at intervals continues for hours. When you close the lid, the laptop usually goes to sleep. Use one of these methods:

- To keep the laptop on with the charger connected and the lid closed, run these commands in an **Administrator** PowerShell:
  ```powershell
  powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
  powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
  powercfg /setactive SCHEME_CURRENT
  ```
- Or install **Microsoft PowerToys â†’ Awake** and set it to "Keep awake indefinitely".

If the machine goes to sleep, no data is lost. The tool saves each sent email to the workbook immediately. The send continues after you wake the machine, or on the next scheduled run.

## 9. Monitor remotely (optional)

1. Install Tailscale on the PC and on your phone, and sign in on the two devices.
2. Enable the SSH server one time, in an **Administrator** PowerShell:
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd; Set-Service sshd -StartupType Automatic
   ```
3. From the phone or a different computer, connect with `ssh <windows-user>@<tailscale-ip>` (to find the IP, use `tailscale ip -4`). Then run:
   ```powershell
   cd $HOME\Desktop\Agnostos-v2
   .\.venv\Scripts\python.exe -m outreach.cli stats
   Get-Content output\daily_send.log -Tail 20 -Wait
   ```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | Run `pip install -U truststore certifi`, then `python -m outreach.cli tls-check`. Behind antivirus software or a proxy that inspects HTTPS, set `SSL_CERT_FILE` to its root certificate |
| `SMTPAuthenticationError` | Use an app password, not your login password. Check `SMTP_USER` |
| `SMTPServerDisconnected` / read timed out | The server closes idle sessions. Agnostos connects again automatically. If the problem continues, increase `SEND_DELAY_MIN` and decrease `DAILY_SEND_CAP` |
| `SMTPSenderRefused` | `SMTP_FROM` must be the same mailbox as `SMTP_USER` |
| `response truncated` from the LLM | The tool fixes this automatically for gpt-5 and o-series models. For other models, increase `MAX_OUTPUT_TOKENS` |
| Workbook "is open in Excel" | Close Excel, then run the command again |
| Names with accents show as `?` | `$env:PYTHONIOENCODING="utf-8"` |
| The tool sent few emails | Run `stats`. It shows the reason, for example rows with no email, low match scores, the `MAX_PROFESSORS` limit, or the daily limit |
