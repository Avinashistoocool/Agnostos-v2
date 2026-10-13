"""End-to-end smoke test with a mocked OpenAI client (no API calls, no emails sent)."""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from outreach.config import settings
from outreach.excel_io import (load_for_sending, load_targets, mark_sent,
                               update_workbook, write_new_workbook)
from outreach.llm import LLMEvaluator
from outreach.mailer import Mailer
from outreach.matcher import filter_candidates
from outreach.resume_parser import parse_resume
from outreach.scraper import ScrapeResult, _html_to_text, _looks_blocked, extract_professors

import _paths

settings.resume_path = _paths.resume_path(settings)
settings.target_xlsx = _paths.target_xlsx(settings)
MIN_TARGETS = 10 if _paths.using_fixtures(settings) else 40

TMP = Path(__file__).resolve().parent / "_tmp"


class _PromptDetails:
    cached_tokens = 1000


class _Usage:
    prompt_tokens = 1420
    completion_tokens = 310
    prompt_tokens_details = _PromptDetails()


class _Choice:
    finish_reason = "stop"

    def __init__(self, content):
        self.message = type("Msg", (), {"content": content})()


class _Resp:
    def __init__(self, text):
        self.choices = [_Choice(text)]
        self.usage = _Usage()


class FakeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["messages"][0]["role"] == "system"
        ctx = kwargs["messages"][1]["content"]
        name = ctx.split("Professor: ")[1].split("\n")[0]
        return _Resp(json.dumps({
            "probability": 40 + self.calls,
            "justification": f"Strong overlap on jet tagging with {name}.",
            "subject": "Summer internship enquiry - jet tagging",
            "body": f"Dear {name},\n\nI read your recent work.\n\nBest,\nAlex",
        }))


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


def _strip_result_columns(path: Path) -> None:
    """Remove any columns this tool previously wrote, so the fixture is pristine."""
    import openpyxl
    from outreach.excel_io import RESULT_COLUMNS, _find_header_row

    wanted = {c.lower() for c in RESULT_COLUMNS}
    wb = openpyxl.load_workbook(path)
    for ws in wb.worksheets:
        header_row = _find_header_row(ws)
        doomed = [c for c in range(ws.max_column, 0, -1)
                  if str(ws.cell(row=header_row, column=c).value or "").strip().lower() in wanted]
        for col in doomed:
            ws.delete_cols(col)
    wb.save(path)


def main() -> int:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    print("[1] resume parse")
    profile = parse_resume(settings.resume_path)
    assert profile.name and profile.email and profile.projects, "resume parse failed"
    print(f"    ok: {profile.name}, {len(profile.projects)} projects")

    print("[2] excel ingest")
    src = TMP / "targets.xlsx"
    shutil.copy2(settings.target_xlsx, src)
    _strip_result_columns(src)  # the live workbook may already hold real drafts
    professors = load_targets(src)
    assert len(professors) >= MIN_TARGETS, len(professors)
    print(f"    ok: {len(professors)} professors")

    print("[3] local filter")
    selected, rejected = filter_candidates(professors, profile, 0.25, 8)
    assert len(selected) == 8 and rejected
    assert all(p.local_score >= 0.25 for p in selected)
    print(f"    ok: {len(selected)} selected, {len(rejected)} rejected, "
          f"top={selected[0].local_score}")

    print("[3b] thin-context professors are rejected before the LLM")
    from outreach.models import Professor as _P
    thin = [_P(name="Dr Ghost", email="g@x.edu", institution="X",
               research_area="CMS 511b")]
    sel_thin, rej_thin = filter_candidates(thin + professors[:5], profile, 0.0, 10)
    assert any("too little research context" in p.llm_status for p in rej_thin), \
        [p.llm_status for p in rej_thin]
    assert all(p.name != "Dr Ghost" for p in sel_thin)
    print("    ok: directory stubs filtered out")

    print("[4] estimation gate maths")
    ev = LLMEvaluator(settings, profile)
    est = ev.estimate(selected)
    assert est.n_calls == 8
    if settings.is_free_tier:
        assert est.cost_usd == 0 and est.free_tier
        print(f"    ok: {est.n_calls} calls, free tier ({settings.provider})")
    else:
        assert est.cost_usd > 0
        print(f"    ok: ${est.cost_usd:.4f} for {est.n_calls} calls")

    print("[4b] paid-provider pricing still computes")
    paid = replace(settings, provider="openai", draft_model="gpt-4.1")
    est_paid = LLMEvaluator(paid, profile).estimate(selected)
    assert est_paid.cost_usd > 0 and not est_paid.free_tier
    print(f"    ok: ${est_paid.cost_usd:.4f} on openai/gpt-4.1")

    print("[5] mocked LLM evaluation")
    ev._client = FakeClient()
    ev.evaluate_all(selected)
    assert all(p.probability > 0 for p in selected), [p.llm_status for p in selected]
    assert all(p.email_body.startswith("Dear ") for p in selected)
    assert all("\n" in p.email_body for p in selected), "escaped newlines not decoded"
    assert ev.actual_cost() > 0 or settings.is_free_tier
    print(f"    ok: {ev.usage_report()}")

    print("[5b] abort after repeated failures")
    class BrokenCompletions:
        def create(self, **_kw):
            raise ValueError("bad gateway")

    class BrokenClient:
        chat = type("Chat", (), {"completions": BrokenCompletions()})()

    import copy
    victims = [copy.deepcopy(p) for p in professors if p.email][:6]
    for v in victims:
        v.probability, v.llm_status = 0, ""
    ev2 = LLMEvaluator(settings, profile)
    ev2._client = BrokenClient()
    ev2.evaluate_all(victims)
    assert ev2.usage["calls"] == 0
    assert any("aborted after repeated failures" in v.llm_status for v in victims), \
        [v.llm_status for v in victims]
    print("    ok: stopped early instead of burning the whole list")

    print("[5c] draft body formatting repair")
    from outreach.llm import tidy_body
    wall = ("I read your work on jet tagging. I built GDS-ParT in PyTorch. "
            "I am available May to July 2027. I can apply via DAAD WISE. "
            "Would you have capacity to host? May I send a proposal?")
    fixed = tidy_body(wall, "Prof. Michael Spannowsky")
    assert fixed.startswith("Dear Prof. Spannowsky,\n\n"), fixed[:40]
    assert fixed.count("\n\n") >= 2, fixed
    assert tidy_body("Body.", "Prof. Dr. Anna Schmidt").startswith("Dear Prof. Schmidt,")
    assert tidy_body("Body.", "").startswith("Dear Professor,")
    good = "Dear Dr. Butter,\n\nOne.\n\nTwo.\n\nBest,\nAlex"
    assert tidy_body(good, "Dr. Butter") == good, "mangled a well-formed body"
    print("    ok: salutation added, wall split, well-formed body untouched")

    print("[5d] humanizing layer")
    from outreach.humanize import deslop, has_hard_claims
    from outreach.humanize import score as ai_score
    sloppy = ("Dear Prof. X,\n\nI am writing to express my interest. I hope this email "
              "finds you well. Moreover, I utilised cutting-edge methods and my model "
              "achieved superior results.\n\nBest,\nAlex")
    before, _ = ai_score(sloppy)
    cleaned = deslop(sloppy)
    after, _ = ai_score(cleaned)
    assert after < before, (before, after)
    for banned in ("I am writing to", "utilised", "cutting-edge", "Moreover",
                   "achieved", "superior", "finds you well"):
        assert banned not in cleaned, banned
    assert cleaned.startswith("Dear Prof. X,")
    assert has_hard_claims("improved the accuracy by 12%")
    assert not has_hard_claims("I built a transformer variant and ran it on a subset.")
    print(f"    ok: AI-tell score {before} -> {after}, claims detected")

    print("[6] write back to source workbook (Mode B)")
    update_workbook(src, selected + rejected, make_backup=True)
    backups = list(TMP.glob("targets.backup-*.xlsx"))
    assert backups, "no backup created"
    rows = load_for_sending(src)
    assert len(rows) == 8, len(rows)
    assert rows[0]["subject"] and rows[0]["probability"] > 0
    print(f"    ok: {len(rows)} sendable rows, backup={backups[0].name}")

    print("[6b] idempotent re-write does not duplicate columns")
    import openpyxl
    sheet = openpyxl.load_workbook(src).sheetnames[0]
    before = openpyxl.load_workbook(src)[sheet].max_column
    update_workbook(src, selected + rejected, make_backup=False)
    after = openpyxl.load_workbook(src)[sheet].max_column
    assert before == after, (before, after)
    print(f"    ok: column count stable at {after}")

    print("[7] new workbook (Mode A output)")
    out = TMP / "new.xlsx"
    write_new_workbook(out, selected)
    new_rows = load_for_sending(out)
    assert len(new_rows) == 8
    assert new_rows[0]["probability"] >= new_rows[-1]["probability"], "not sorted"
    print(f"    ok: {len(new_rows)} rows written and re-read")

    print("[8] mailer dry-run + attachments")
    settings.attachments = [str(settings.resume_path)]
    mailer = Mailer(settings, profile, dry_run=True)
    updates = mailer.send_batch(rows)
    assert len(updates) == 8 and all(u["status"] == "dry-run" for u in updates)
    msg = mailer.send_one(rows[0])["message"]
    body = msg.get_body(("plain",)).get_content()
    assert profile.email in body and profile.name in body, "signature missing"
    atts = [a.get_filename() for a in msg.iter_attachments()]
    assert atts == [Path(settings.resume_path).name], atts
    print(f"    ok: 8 dry-run msgs, attachment={atts[0]}")

    print("[9] send-status writeback + resume safety")
    mark_sent(src, updates)
    rows2 = load_for_sending(src)
    assert all(r["send_status"] == "dry-run" for r in rows2)
    # A dry run must NOT block a later real send.
    still_pending = Mailer(settings, profile, dry_run=True).send_batch(rows2)
    assert len(still_pending) == 8, "dry-run wrongly treated as already sent"
    # A genuine send must block a repeat.
    sent_updates = [{**u, "status": "sent"} for u in updates]
    mark_sent(src, sent_updates)
    rows3 = load_for_sending(src)
    again = Mailer(settings, profile, dry_run=True).send_batch(rows3)
    assert not again, "already-sent rows were not skipped"
    forced = Mailer(settings, profile, dry_run=True).send_batch(rows3, resend=True)
    assert len(forced) == 8
    print("    ok: dry-run never blocks, real sends do, --resend overrides")

    print("[9b] review redirect keeps the real target visible")
    reviewer = Mailer(settings, profile, dry_run=True, redirect_to="me@example.com")
    msg = reviewer.send_one(rows3[0])["message"]
    assert msg["To"] == "me@example.com", msg["To"]
    assert rows3[0]["email"] in msg["Subject"], msg["Subject"]
    print(f"    ok: {msg['Subject'][:58]}")

    print("[9c] .eml export opens in a mail client")
    eml_dir = TMP / "drafts"
    written = Mailer(settings, profile, dry_run=True).save_eml(rows3[0], eml_dir)
    assert written.exists() and written.suffix == ".eml"
    import email as _email
    from email import policy as _policy
    parsed = _email.message_from_bytes(written.read_bytes(), policy=_policy.default)
    assert parsed["To"] and parsed["Subject"]
    assert [a.get_filename() for a in parsed.iter_attachments()] == \
        [Path(settings.resume_path).name]
    print(f"    ok: {written.name}")

    print("[9d] transient SMTP drop reconnects; persistent failure aborts")
    import smtplib as _smtplib

    class _FlakyServer:
        def __init__(self, fail_times):
            self.fail_times = fail_times
            self.delivered = 0

        def send_message(self, _msg):
            if self.fail_times > 0:
                self.fail_times -= 1
                raise _smtplib.SMTPServerDisconnected("connection reset")
            self.delivered += 1

    flaky = Mailer(settings, profile)
    flaky.dry_run = False
    server = _FlakyServer(fail_times=1)
    flaky._server = server
    flaky.connect = lambda: setattr(flaky, "_server", server)
    assert flaky.send_one(rows3[0])["status"] == "sent", "transient drop was not retried"
    assert server.delivered == 1

    dead = Mailer(settings, profile)
    dead.dry_run = False
    dead_server = _FlakyServer(fail_times=999)
    dead._server = dead_server
    dead.connect = lambda: setattr(dead, "_server", dead_server)
    dead.s = replace(settings, send_delay_min=0, send_delay_max=0)
    aborts = []
    dead_updates = dead.send_batch(
        rows3, resend=True,
        progress=lambda *a: aborts.append(a[3]["status"]))
    assert "aborted" in aborts, aborts
    assert len(dead_updates) < len(rows3), (len(dead_updates), len(rows3))
    print(f"    ok: retried once, then stopped after {len(dead_updates)} failures")

    print("[10] scraper extraction heuristics")
    html = """<html><body>
      <div class="person"><h3>Prof. Dr. Anna Schmidt</h3>
      <p>Machine learning for collider physics and jet tagging.</p>
      <p>Email: anna.schmidt [at] uni-example [dot] de</p></div>
      <div class="person"><h3>Dr. Marco Rossi</h3>
      <p>Graph neural networks for tracking.</p>
      <a href="mailto:m.rossi@uni-example.de">m.rossi@uni-example.de</a></div>
      <p>General enquiries: info@uni-example.de</p>
      <img src="logo@2x.png">
    </body></html>"""
    res = ScrapeResult("https://uni-example.de/staff", html, _html_to_text(html))
    found = extract_professors(res, "Uni Example", "Germany", "Physics")
    emails = sorted(p.email for p in found if p.email)
    assert emails == ["anna.schmidt@uni-example.de", "m.rossi@uni-example.de"], emails
    assert all(p.institution == "Uni Example" for p in found)
    print(f"    ok: extracted {emails} (generic info@ dropped)")

    print("[10b] emails behind profile links + role-suffix cleanup")
    html2 = """<html><body><table>
      <tr><td><a href="/people/j.smith">Prof Jane Smith</a></td><td>Professor</td></tr>
      <tr><td><a href="/people/k.lee">Dr Kai Lee</a></td><td>Senior Lecturer</td></tr>
    </table></body></html>"""
    text2 = "Prof Jane Smith\tProfessor\nDr Kai Lee\tSenior Lecturer"
    found2 = extract_professors(ScrapeResult("https://u.ac.uk/dept/", html2, text2),
                                "U", "UK", "Physics")
    names = sorted(p.name for p in found2)
    assert names == ["Dr Kai Lee", "Prof Jane Smith"], names
    urls = sorted(p.profile_url for p in found2)
    assert urls == ["https://u.ac.uk/people/j.smith", "https://u.ac.uk/people/k.lee"], urls
    assert all(not p.email and p.notes for p in found2)
    print(f"    ok: {names} resolved to profile pages for the second hop")

    print("[11] blocked-page detection")
    assert _looks_blocked("<html><title>Just a moment...</title>cf-chl</html>")
    assert not _looks_blocked("<html><body>Faculty directory</body></html>")
    # A long, genuine page that merely mentions Cloudflare must not be flagged.
    big = "<html><body>" + ("Faculty directory cloudflare cdn. " * 300) + "</body></html>"
    assert not _looks_blocked(big)
    print("    ok (no false positive on large pages)")

    shutil.rmtree(TMP)
    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
