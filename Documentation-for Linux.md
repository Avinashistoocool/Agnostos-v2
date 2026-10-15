# Agnostos on Linux

This guide covers setup and daily use on Ubuntu/Debian, Fedora and Arch, as a desktop or a headless server. It runs Agnostos as a local command-line tool.

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

Python 3.10 or newer is required. Check with `python3 --version`.

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

> Many cloud VPS providers block outbound port 25, and some block 465 and 587 on new accounts. Run `python -m outreach.cli tls-check` to confirm SMTP is reachable.

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
| Review copies to yourself | `python -m outreach.cli send --review --top 3` |
| Send for real, paced | `python -m outreach.cli send --live --limit 40 --local-window 9-17 --wait` |
| Progress | `python -m outreach.cli stats` |
| Detect replies and bounces | `python -m outreach.cli check-replies` |
| Draft follow-ups | `python -m outreach.cli replies` |
| Send approved follow-ups | `python -m outreach.cli replies --send --live` |

The workbook is an `.xlsx`. You can open it in LibreOffice Calc, but close it before a live send. Already-sent rows are never re-sent unless you pass `--resend`.

## 7. Send automatically every weekday

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

`systemd-inhibit` stops the machine from sleeping while the send runs. `Persistent=true` catches up on a run that was missed while the machine was off.

### Option B: cron

```bash
crontab -e
```
```
30 12 * * 1-5 cd $HOME/Agnostos-v2 && PYTHONIOENCODING=utf-8 .venv/bin/python -u -m outreach.cli send --live --yes --limit 40 --local-window 9-17 --wait >> output/daily_send.log 2>&1
```

Cron uses the system timezone. Check it with `timedatectl`.

## 8. Keep the machine awake (laptops)

- Use `systemd-inhibit` as in Option A, or prefix a manual run:
  `systemd-inhibit --what=sleep:idle python -m outreach.cli send --live ...`
- To keep running with the lid closed on power, set `HandleLidSwitchExternalPower=ignore` in `/etc/systemd/logind.conf`, then run `sudo systemctl restart systemd-logind`.
- On a headless server, run long manual jobs inside `tmux` so they survive SSH disconnects:
  `tmux new -s agnostos` → run the command → `Ctrl+B D` to detach → `tmux attach -t agnostos` to return.

If the machine sleeps anyway, nothing is lost. Each sent email is saved immediately, and the waits use the wall clock.

## 9. Monitor remotely (optional)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh            # Tailscale SSH, no sshd config needed
```
From another device:
```bash
ssh <you>@<machine-name>
cd ~/Agnostos-v2 && source .venv/bin/activate
python -m outreach.cli stats
tail -f output/daily_send.log
```

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | `sudo apt install --reinstall ca-certificates` (or your distro's equivalent), then `pip install -U truststore certifi` and `python -m outreach.cli tls-check`. For a custom CA: `export SSL_CERT_FILE=/path/root.pem` |
| `error: externally-managed-environment` | You're outside the venv. Run `source .venv/bin/activate` |
| `No module named venv` | `sudo apt install python3-venv` |
| `SMTPConnectError` / timeout on a VPS | Your provider blocks SMTP. Ask them to unblock it, or use a different port or host |
| `SMTPAuthenticationError` | Use an app password. Check `SMTP_USER` |
| Timer didn't fire | `systemctl --user list-timers`. On servers, make sure `loginctl enable-linger` was run |
| Few emails sent | `python -m outreach.cli stats` explains why rows were skipped |
