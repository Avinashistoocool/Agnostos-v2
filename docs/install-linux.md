# Agnostos on Linux

See also: [FAQ](faq.md) · [Diagnostics](diagnostics.md)

This guide tells you how to set up and use Agnostos each day on Ubuntu/Debian, Fedora and Arch. It applies to a desktop or a headless server. Agnostos runs as a local command-line tool.

---

## 1. Install the prerequisites

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git ca-certificates

# Fedora
sudo dnf install -y python3 python3-pip git ca-certificates

# Arch
sudo pacman -S --needed python python-pip git ca-certificates
```

Agnostos requires Python 3.10 or newer. To check the version, run `python3 --version`.

## 2. Get the code

```bash
cd ~
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

## 4. Configure `.env`

```bash
cp .env.example .env
chmod 600 .env        # it holds passwords
nano .env
```

```ini
RESUME_PATH=/home/<you>/CV.pdf
TARGET_XLSX=/home/<you>/Agnostos-v2/output/professors.xlsx
ATTACHMENTS=/home/<you>/research_CV.pdf

LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
# OPENAI_API_KEY=sk-...
# DRAFT_MODEL=gpt-5-mini

SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_SECURITY=ssl
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<app password>
SMTP_FROM=you@gmail.com

DAILY_SEND_CAP=40
SEND_DELAY_MIN=300
SEND_DELAY_MAX=600
SEND_LOCAL_WINDOW=9-17
```

> Many cloud VPS providers block outbound port 25. Some providers also block 465 and 587 on new accounts. To make sure that the tool can connect to SMTP, run `python -m outreach.cli tls-check`.

## 5. Check the setup

```bash
python -m outreach.cli profile
python -m outreach.cli models
python -m outreach.cli tls-check
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
| Write follow-up drafts | `python -m outreach.cli replies` |
| Send approved follow-ups | `python -m outreach.cli replies --send --live` |

The workbook is an `.xlsx` file. You can open it in LibreOffice Calc, but close it before a live send. The tool never sends again to rows that have the status sent, unless you use `--resend`.

## 7. Send automatically each weekday

### Option A: systemd user timer (recommended)

`~/.config/systemd/user/agnostos-send.service`
```ini
[Unit]
Description=Agnostos paced outreach send

[Service]
Type=simple
WorkingDirectory=%h/Agnostos-v2
Environment=PYTHONIOENCODING=utf-8
ExecStart=/usr/bin/systemd-inhibit --what=sleep:idle --why="Agnostos sending" \
  %h/Agnostos-v2/.venv/bin/python -u -m outreach.cli send --live --yes --limit 40 --local-window 9-17 --wait
StandardOutput=append:%h/Agnostos-v2/output/daily_send.log
StandardError=append:%h/Agnostos-v2/output/daily_send.log
```

`~/.config/systemd/user/agnostos-send.timer`
```ini
[Unit]
Description=Run Agnostos send on weekdays

[Timer]
OnCalendar=Mon..Fri 12:30
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now agnostos-send.timer
sudo loginctl enable-linger $USER          # keep running after you log out (servers)
systemctl --user list-timers | grep agnostos
systemctl --user start agnostos-send        # run now
journalctl --user -u agnostos-send -f       # or: tail -f output/daily_send.log
```

`systemd-inhibit` prevents sleep of the machine while the send is active. With `Persistent=true`, the timer does a run that it missed while the machine was off.

### Option B: cron

```bash
crontab -e
```
```
30 12 * * 1-5 cd $HOME/Agnostos-v2 && PYTHONIOENCODING=utf-8 .venv/bin/python -u -m outreach.cli send --live --yes --limit 40 --local-window 9-17 --wait >> output/daily_send.log 2>&1
```

Cron uses the time zone of the system. To check it, run `timedatectl`.

## 8. Keep the machine awake (laptops)

- Use `systemd-inhibit` as in Option A, or put it before the command of a manual run:
  `systemd-inhibit --what=sleep:idle python -m outreach.cli send --live ...`
- To keep the machine on with the lid closed and the power connected, set `HandleLidSwitchExternalPower=ignore` in `/etc/systemd/logind.conf`. Then run `sudo systemctl restart systemd-logind`.
- On a headless server, run long manual jobs in `tmux`, so that they continue after an SSH disconnection:
  `tmux new -s agnostos` â†’ run the command â†’ `Ctrl+B D` to detach â†’ `tmux attach -t agnostos` to return.

If the machine goes to sleep, no data is lost. The tool saves each sent email immediately, and the waits use the wall clock.

## 9. Monitor remotely (optional)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh            # Tailscale SSH, no sshd config needed
```
From a different device:
```bash
ssh <you>@<machine-name>
cd ~/Agnostos-v2 && source .venv/bin/activate
python -m outreach.cli stats
tail -f output/daily_send.log
```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | Run `sudo apt install --reinstall ca-certificates` (or the equivalent command of your distribution). Then run `pip install -U truststore certifi` and `python -m outreach.cli tls-check`. For a custom CA: `export SSL_CERT_FILE=/path/root.pem` |
| `error: externally-managed-environment` | You are not in the venv. Run `source .venv/bin/activate` |
| `No module named venv` | `sudo apt install python3-venv` |
| `SMTPConnectError` / timeout on a VPS | Your provider blocks SMTP. Ask the provider to unblock it, or use a different port or host |
| `SMTPAuthenticationError` | Use an app password. Check `SMTP_USER` |
| The timer did not start | `systemctl --user list-timers`. On servers, make sure that you ran `loginctl enable-linger` |
| The tool sent few emails | `python -m outreach.cli stats` gives the reasons for skipped rows |
