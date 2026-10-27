"""One HTML page with every professor conversation, both sides, newest activity first.

Sources, merged and de-duplicated:
  * the IMAP mailbox (professor replies, bounces, anything in Sent)
  * the workbook (the first email exactly as sent, even if Sent has no copy)
  * send_log.csv (resends from the second account)
  * reply_queue.json (replies/follow-ups we sent, and drafts still waiting)
"""
from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .excel_io import load_for_sending
from .replier import Message, ThreadReader


def _dt(text: str) -> datetime | None:
    try:
        return datetime.strptime((text or "")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _near(a: datetime | None, b: datetime | None, secs: int = 900) -> bool:
    return bool(a and b and abs((a - b).total_seconds()) < secs)


def collect(settings, path: Path, progress=None) -> list[dict]:
    rows = [r for r in load_for_sending(path) if r["send_status"].lower() == "sent"]
    out_dir = settings.output_dir
    queue = []
    qp = out_dir / "reply_queue.json"
    if qp.exists():
        queue = json.loads(qp.read_text(encoding="utf-8"))
    resends: dict[str, list[dict]] = {}
    lp = out_dir / "send_log.csv"
    if lp.exists():
        with lp.open(newline="", encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                if rec.get("mode") == "resend" and rec.get("status") == "sent":
                    resends.setdefault(rec["email"].lower(), []).append(rec)

    with ThreadReader(settings) as reader:
        threads = reader.threads(rows, progress=progress)

    convos = []
    for t in threads:
        r = t.row
        email = r["email"].lower()
        msgs = [m for m in t.messages]
        # First email: make sure the full text from the workbook is there.
        first_at = _dt(r.get("sent_at", ""))
        if not any(m.sender == "student" and _near(m.when, first_at) for m in msgs):
            msgs.append(Message(when=first_at, sender="student", subject=r.get("subject", ""),
                                text=r.get("body", ""), kind="first"))
        for rec in resends.get(email, []):
            msgs.append(Message(when=_dt(rec["time"]), sender="student",
                                subject=r.get("subject", ""), text=r.get("body", ""),
                                kind=f"resent from {settings.resend_smtp_from or 'Gmail'}"))
        for q in queue:
            if q["email"].lower() != email or not q.get("body"):
                continue
            when = _dt(q.get("sent_at", ""))
            if when and any(m.sender == "student" and _near(m.when, when) for m in msgs):
                continue
            msgs.append(Message(
                when=when, sender="student" if when else "draft",
                subject="Re: " + q.get("subject", ""), text=q["body"],
                kind=(q.get("kind") or "reply") + ("" if when else
                      (" - approved, waiting to send" if q.get("approved") else " - draft"))))
        msgs.sort(key=lambda m: (m.when is None, m.when or datetime.max))
        prof = [m for m in msgs if m.sender == "professor"]
        last = max((m.when for m in msgs if m.when), default=None)
        state = (r.get("reply_status") or "no reply").split()[0]
        if any(m.sender == "draft" for m in msgs):
            state = "draft pending"
        elif prof and msgs[-1].sender == "professor":
            state = "awaiting you"
        convos.append({"row": r, "messages": msgs, "last": last, "state": state,
                       "replied": bool(prof)})
    convos.sort(key=lambda c: (not c["replied"], -(c["last"] or datetime.min).timestamp()))
    return convos


CSS = """
body{font:14px/1.45 system-ui,Segoe UI,Arial;margin:0;background:#f4f5f7;color:#1d2330}
header{position:sticky;top:0;background:#1f3864;color:#fff;padding:10px 18px;z-index:2}
header input{width:340px;padding:6px 8px;border-radius:6px;border:0;margin-left:12px}
header select{padding:5px;border-radius:6px;margin-left:6px}
.wrap{display:flex;height:calc(100vh - 52px)}
nav{width:360px;overflow:auto;border-right:1px solid #d6d9e0;background:#fff}
nav a{display:block;padding:8px 12px;border-bottom:1px solid #eef0f3;color:inherit;text-decoration:none}
nav a:hover{background:#eef3ff}
nav .n{font-weight:600}
nav .i{color:#667;font-size:12px}
main{flex:1;overflow:auto;padding:18px 26px}
section{background:#fff;border-radius:10px;padding:14px 18px;margin:0 0 22px;box-shadow:0 1px 3px #0001}
h2{margin:0 0 4px;font-size:18px}
.meta{color:#667;font-size:12px;margin-bottom:10px}
.msg{border-radius:10px;padding:10px 12px;margin:10px 0;max-width:860px;white-space:pre-wrap}
.student{background:#e8f0ff;margin-left:60px}
.professor{background:#eaf7ec;margin-right:60px;border-left:4px solid #2e9e4f}
.system{background:#fdecea;margin-right:60px}
.draft{background:#fff8e1;margin-left:60px;border:1px dashed #d9a400}
.h{font-size:12px;color:#556;margin-bottom:4px;white-space:normal}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;background:#dde3ee;margin-left:6px}
.t-replied,.t-awaiting{background:#c9efd3}.t-bounced{background:#f6c9c4}.t-draft{background:#ffe9a8}
"""

JS = """
const q=document.getElementById('q'),f=document.getElementById('f');
function apply(){const s=q.value.toLowerCase(),st=f.value;
 document.querySelectorAll('section').forEach(el=>{
  const ok=(!s||el.dataset.k.includes(s))&&(!st||el.dataset.s===st);
  el.style.display=ok?'':'none';
  document.querySelector('nav a[href="#'+el.id+'"]').style.display=ok?'':'none';});}
q.oninput=apply;f.onchange=apply;
"""


def render(convos: list[dict]) -> str:
    e = html.escape
    states = Counter(c["state"] for c in convos)
    nav, body = [], []
    for i, c in enumerate(convos):
        r = c["row"]
        sid = f"c{i}"
        tag = c["state"]
        tcls = "t-" + tag.split()[0]
        nav.append(f'<a href="#{sid}"><span class="n">{e(str(r.get("name","")))}</span>'
                   f'<span class="tag {tcls}">{e(tag)}</span><br><span class="i">'
                   f'{e(str(r.get("institution","")))[:48]}</span></a>')
        parts = []
        for m in c["messages"]:
            who = {"student": "You", "professor": str(r.get("name", "Professor")),
                   "system": "Mail server", "draft": "Draft (not sent)"}.get(m.sender, m.sender)
            when = f"{m.when:%a %d %b %Y, %H:%M}" if m.when else "not sent yet"
            kind = f'<span class="tag">{e(m.kind)}</span>' if m.kind else ""
            parts.append(f'<div class="msg {m.sender}"><div class="h"><b>{e(who)}</b> · {when}'
                         f'{kind}<br>{e(m.subject or "")}</div>{e((m.text or "").strip())}</div>')
        key = " ".join(str(x) for x in (r.get("name"), r.get("email"), r.get("institution"),
                                         r.get("country"))).lower()
        body.append(
            f'<section id="{sid}" data-k="{e(key)}" data-s="{e(tag)}"><h2>{e(str(r.get("name","")))}'
            f'<span class="tag {tcls}">{e(tag)}</span></h2><div class="meta">'
            f'{e(r["email"])} · {e(str(r.get("institution","")))} · {e(str(r.get("country","")))}'
            f' · {len(c["messages"])} messages</div>{"".join(parts)}</section>')
    opts = "".join(f'<option value="{e(s)}">{e(s)} ({n})</option>' for s, n in states.most_common())
    return (f'<!doctype html><meta charset="utf-8"><title>Agnostos conversations</title>'
            f'<style>{CSS}</style><header><b>Agnostos conversations</b> · {len(convos)} threads · '
            f'built {datetime.now():%d %b %H:%M}<input id="q" placeholder="search name, email, '
            f'university..."><select id="f"><option value="">all</option>{opts}</select></header>'
            f'<div class="wrap"><nav>{"".join(nav)}</nav><main>{"".join(body)}</main></div>'
            f'<script>{JS}</script>')


def build_html(settings, path: Path, out: Path, progress=None) -> int:
    convos = collect(settings, path, progress)
    out.write_text(render(convos), encoding="utf-8")
    return len(convos)
