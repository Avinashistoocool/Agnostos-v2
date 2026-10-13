"""CLI entrypoint for the academic outreach pipeline.

  python -m outreach.cli profile
  python -m outreach.cli run  --mode list   [--yes] [--no-enrich] [--max-professors N]
  python -m outreach.cli run  --mode scrape --sources sources.yaml
  python -m outreach.cli send --dry-run
  python -m outreach.cli send --live
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import MODEL_PRICES, PROVIDERS, ConfigError, settings
from .enrich import OpenAlexClient
from .excel_io import (is_writable, load_for_sending, load_targets, mark_sent,
                       update_workbook, write_new_workbook)
from .llm import LLMEvaluator, confirm_gate, list_models
from .mailer import Mailer
from .matcher import filter_candidates
from .resume_parser import parse_resume, save_profile

BAR = "=" * 62

# Mapped from the exception name the mailer reports, so a failed run ends with
# the fix rather than a bare traceback class.
SMTP_HINTS = {
    "SMTPSenderRefused":
        "   The server refused your From address. SMTP_FROM usually has to be\n"
        "   exactly the mailbox SMTP_USER authenticates as - check .env.",
    "SMTPAuthenticationError":
        "   Login rejected. For Gmail use a 16-char App Password, not your\n"
        "   account password (https://myaccount.google.com/apppasswords).",
    "SMTPServerDisconnected":
        "   The server dropped the connection, usually rate-limiting. Raise\n"
        "   SEND_DELAY_MIN/MAX, lower DAILY_SEND_CAP, and re-run to continue.",
    "SMTPRecipientsRefused":
        "   The recipient address was rejected - check that row in the sheet.",
    "SMTPDataError":
        "   The server rejected the message body, often as suspected spam.\n"
        "   Shorten the draft or send fewer at a time.",
    "SMTPConnectError":
        "   Could not reach SMTP_HOST:SMTP_PORT. Check the host, port, and\n"
        "   SMTP_SECURITY (starttls on 587, ssl on 465).",
    "TimeoutError":
        "   The mail server timed out. Raise SMTP_TIMEOUT in .env.",
}


def _h(title: str) -> None:
    print(f"\n{BAR}\n {title}\n{BAR}")


def _safe(text: str) -> str:
    """Windows consoles are often cp1252; never let printing kill a run."""
    enc = sys.stdout.encoding or "utf-8"
    return str(text).encode(enc, errors="replace").decode(enc)


def _load_sources(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Sources file not found: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("pip install pyyaml, or use a .json sources file") from exc
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    sources = data.get("sources", data) if isinstance(data, dict) else data
    if not isinstance(sources, list):
        raise ValueError("Sources file must contain a list of {url, institution, country}")
    return sources


# ---------------------------------------------------------------- commands
def cmd_profile(args) -> int:
    _h("RESUME PARSE")
    profile = parse_resume(settings.require_resume(args.resume))
    print(_safe(f" Name        : {profile.name}"))
    print(_safe(f" Email       : {profile.email}"))
    print(_safe(f" Programme   : {profile.degree} @ {profile.institution} "
                f"({profile.graduation_year}, GPA {profile.gpa})"))
    print(_safe(f" Interests   : {', '.join(profile.research_interests)}"))
    print(_safe(f" Skills      : {', '.join(profile.skills[:20])}"))
    print(f" Projects    : {len(profile.projects)}")
    for p in profile.projects:
        print(_safe(f"   - {p['title']}"))
    settings.ensure_dirs()
    out = settings.output_dir / "profile.json"
    save_profile(profile, out)
    print(f"\n Saved structured profile -> {out}")
    print("\n--- LLM system-prompt profile block ---")
    print(_safe(profile.summary_block()))
    return 0


def cmd_run(args) -> int:
    settings.ensure_dirs()
    if args.provider:
        settings.provider = args.provider
        settings.draft_model = args.model or PROVIDERS[args.provider]["default_model"]
    if args.max_professors:
        settings.max_professors = args.max_professors
    if args.budget:
        settings.budget_usd = args.budget
    if args.model:
        settings.draft_model = args.model

    _h("STEP 1/6  RESUME")
    profile = parse_resume(settings.require_resume(args.resume))
    print(_safe(f" {profile.name} | {profile.degree} @ {profile.institution}"))
    print(_safe(f" Interests: {', '.join(profile.research_interests[:6])}"))

    _h("STEP 2/6  TARGET ACQUISITION")
    if args.mode == "scrape":
        from .scraper import run_scrape
        sources = _load_sources(Path(args.sources))
        print(f" Scraping {len(sources)} directory page(s) with stealth browser...")

        def scrape_progress(i, total, src, result, found):
            flag = "BLOCKED" if result.blocked else ("ERR" if result.error else "ok")
            print(_safe(f"  [{i}/{total}] {src['url'][:62]:<62} {flag:>8} "
                        f"+{len(found)} profs"))
            if result.error:
                print(_safe(f"          {result.error[:90]}"))

        professors = run_scrape(settings, sources, scrape_progress,
                                resolve_profiles=not args.no_profile_hop)
        with_email = sum(1 for p in professors if p.email)
        print(f" Discovered {len(professors)} people, {with_email} with an email address.")
    else:
        xlsx = settings.require_target_xlsx(args.xlsx)
        professors = load_targets(xlsx, sheet=args.sheet)
        print(f" Loaded {len(professors)} professors from {xlsx.name}")
    if not professors:
        print(" No professors found. Aborting.")
        return 1

    _h("STEP 3/6  OPENALEX ENRICHMENT")
    if args.no_enrich or not settings.use_openalex:
        print(" Skipped (--no-enrich).")
    else:
        client = OpenAlexClient(
            mailto=settings.openalex_mailto or profile.email,
            api_key=settings.openalex_api_key,
            cache_path=settings.output_dir / "openalex_cache.json",
            works_per_author=settings.openalex_works,
        )

        def enrich_progress(i, total, p):
            if i % 10 == 0 or i == total:
                print(f"  [{i}/{total}] enriched")

        client.enrich_all(professors, enrich_progress)
        hit = sum(1 for p in professors if p.recent_works)
        print(f" Publication data found for {hit}/{len(professors)} professors.")
        if client.rate_limited:
            print(f" ! {client.last_error}")
            print("   Continuing with directory/sheet text only.")

    _h("STEP 4/6  LOCAL NLP FILTER (zero tokens)")
    selected, rejected = filter_candidates(
        professors, profile,
        min_score=args.min_score if args.min_score is not None else settings.min_local_score,
        max_count=settings.max_professors,
    )
    print(f" {len(selected)} selected / {len(rejected)} filtered out "
          f"(threshold {settings.min_local_score}, cap {settings.max_professors})")
    for p in selected[:12]:
        print(_safe(f"   {p.local_score:>6.3f}  {p.name[:30]:<30} {p.research_area[:36]}"))
    if len(selected) > 12:
        print(f"   ... and {len(selected) - 12} more")
    if not selected:
        print(" Nothing passed the filter. Lower --min-score and retry.")
        return 1

    _h("STEP 5/6  LLM EVALUATION + DRAFTING")
    cost_note = " (free tier)" if settings.is_free_tier else ""
    print(f" Provider: {settings.provider}{cost_note} | model: {settings.draft_model}")
    settings.require_api_key()
    evaluator = LLMEvaluator(settings, profile)
    estimate = evaluator.estimate(selected)
    if not confirm_gate(estimate, settings.budget_usd, assume_yes=args.yes):
        print(" Aborted by user. No API calls made, no files written.")
        return 2

    def llm_progress(i, total, p):
        status = f"{p.probability:>3}%" if p.probability else "----"
        print(_safe(f"  [{i}/{total}] {status}  {p.name[:34]:<34} {p.llm_status[:28]}"))

    evaluator.evaluate_all(selected, progress=llm_progress,
                           budget_usd=settings.budget_usd)
    print("\n " + evaluator.usage_report())

    _h("STEP 6/6  WRITE RESULTS")
    all_profs = selected + rejected
    if args.mode == "scrape" or args.output:
        out_path = Path(args.output) if args.output else (
            settings.output_dir / f"outreach_targets_{datetime.now():%Y%m%d-%H%M}.xlsx")
        write_new_workbook(out_path, all_profs)
        print(f" Wrote new workbook -> {out_path}")
    else:
        target = settings.require_target_xlsx(args.xlsx)
        update_workbook(target, all_profs, make_backup=not args.no_backup)
        print(f" Updated in place    -> {target}")
        if not args.no_backup:
            print(" Timestamped backup saved alongside the original.")

    ranked = sorted([p for p in selected if p.probability], key=lambda p: -p.probability)
    if ranked:
        print("\n Top matches:")
        for p in ranked[:10]:
            print(_safe(f"   {p.probability:>3}%  {p.name[:32]:<32} {p.institution[:26]}"))
    else:
        print("\n No drafts were produced. Check the LLM Status column for errors.")
        return 1
    print("\n Next: review the drafts, then run "
          "`python -m outreach.cli send --dry-run`.")
    return 0


def cmd_send(args) -> int:
    settings.ensure_dirs()
    if args.delay_min is not None:
        settings.send_delay_min = args.delay_min
    if args.delay_max is not None:
        settings.send_delay_max = args.delay_max
    if args.min_probability is not None:
        settings.send_min_probability = args.min_probability
    if args.limit:
        settings.daily_send_cap = args.limit

    path = settings.require_target_xlsx(args.xlsx)
    profile = parse_resume(settings.require_resume(args.resume))
    rows = load_for_sending(path, sheet=args.sheet)

    # --- Export mode: write .eml files you can open in any mail client ---
    if args.export:
        out_dir = Path(args.export_dir) if args.export_dir else settings.output_dir / "drafts"
        _h(f"EXPORT DRAFTS -> {out_dir}")
        print(f" {len(rows)} rows with drafts in {path.name}")
        if not rows:
            print(" Nothing to export. Run the `run` command first.")
            return 1
        mailer = Mailer(settings, profile, dry_run=True)
        eligible = [r for r in rows
                    if r["probability"] >= settings.send_min_probability]
        eligible.sort(key=lambda r: -r["probability"])
        if args.top:
            eligible = eligible[:args.top]
        for r in eligible:
            written = mailer.save_eml(r, out_dir)
            print(_safe(f"  {r['probability']:>3}%  {written.name}"))
        print(f"\n Wrote {len(eligible)} .eml files to {out_dir}")
        print(" Double-click any of them to open in Outlook/Thunderbird/Mail.")
        return 0

    review_to = args.review_to or (settings.smtp_from if args.review else "")
    dry_run = not (args.live or review_to)
    mode = "DRY RUN" if dry_run else ("REVIEW -> " + review_to if review_to else "LIVE")
    _h(f"EMAIL DISPATCH ({mode})")
    print(f" {len(rows)} rows with drafts in {path.name}")
    if not rows:
        print(" Nothing to send. Run the `run` command first.")
        return 1

    if not dry_run and not is_writable(path):
        print(_safe(f" ERROR: {path.name} is open in Excel (or otherwise locked)."))
        print(" Close it before sending — statuses must be written back, or the")
        print(" same professors could be mailed twice on the next run.")
        return 1

    if not dry_run:
        target_desc = (f"ALL to {review_to} (review copies)" if review_to
                       else "the professors themselves")
        print(f" Sending from {settings.smtp_from} via "
              f"{settings.smtp_host}:{settings.smtp_port} ({settings.smtp_security})")
        print(f" Recipients: {target_desc}")
        print(f" Delay {settings.send_delay_min:.0f}-{settings.send_delay_max:.0f}s | "
              f"cap {settings.daily_send_cap} | min probability "
              f"{settings.send_min_probability}%")
        if args.top:
            print(f" Mailing only the {args.top} highest-probability rows.")
        if settings.attachments:
            print(f" Attachments: {', '.join(Path(a).name for a in settings.attachments)}")
        prompt = (" Send review copies to yourself now? [Y/N]: " if review_to
                  else " Send REAL emails to professors now? [Y/N]: ")
        if input(prompt).strip().lower() not in {"y", "yes"}:
            print(" Aborted.")
            return 2

    def progress(i, total, row, result):
        if result["status"] == "aborted":
            print(_safe(f"\n  ! Stopped: {result['detail']}"))
            return
        print(_safe(f"  [{i}/{total}] {result['status']:<12} {row['email'][:40]:<40} "
                    f"({row['probability']}%)"))
        if result["status"].startswith("failed") and result.get("detail"):
            print(_safe(f"       -> {result['detail'][:120]}"))
        if dry_run and i <= args.preview and result.get("message") is not None:
            msg = result["message"]
            print("  " + "-" * 58)
            print(_safe(f"  Subject: {msg['Subject']}"))
            for line in msg.get_body(("plain",)).get_content().splitlines():
                print(_safe("  | " + line))
            print("  " + "-" * 58)

    with Mailer(settings, profile, dry_run=dry_run, redirect_to=review_to) as mailer:
        updates = mailer.send_batch(rows, progress=progress, resend=args.resend,
                                    top=args.top)

    deferred = mark_sent(path, updates)
    sent = sum(1 for u in updates if u["status"] == "sent")
    review = sum(1 for u in updates if u["status"] == "review-sent")
    failed = [u for u in updates if u["status"].startswith("failed")]
    print(f"\n Done. sent={sent} review-sent={review} "
          f"dry-run={sum(1 for u in updates if u['status'] == 'dry-run')} "
          f"failed={len(failed)} | statuses written back to {path.name}")
    if deferred:
        print(_safe(f" NOTE: {path.name} was locked, so statuses were parked in "
                    f"{deferred.name}."))
        print(" They are applied automatically on the next run — nobody will be mailed twice.")
    if failed:
        first = failed[0]
        print(_safe(f" First failure: {first['status']}"))
        if first.get("detail"):
            print(_safe(f"   {first['detail'][:200]}"))
        print(SMTP_HINTS.get(first["status"].removeprefix("failed: "),
                             "   Re-run the same command to retry the failed rows; "
                             "successful sends are not repeated."))
    if dry_run:
        print("\n To actually see these in your mail app, either:")
        print("   python -m outreach.cli send --review    # mail copies to yourself")
        print("   python -m outreach.cli send --export    # write .eml files to open")
    return 0


# ---------------------------------------------------------------- parser
def cmd_models(args) -> int:
    if args.provider:
        settings.provider = args.provider
    _h(f"AVAILABLE MODELS ({settings.provider})")
    try:
        models = list_models(settings)
    except ConfigError as exc:
        print(f" {exc}")
        return 1
    chat = [m for m in models if not any(
        t in m for t in ("whisper", "orpheus", "guard", "tts", "embedding"))]
    for m in chat:
        marker = " <- current DRAFT_MODEL" if m == settings.draft_model else ""
        price = "free" if settings.is_free_tier else (
            f"${MODEL_PRICES[m][0]:.2f}/{MODEL_PRICES[m][2]:.2f} per 1M in/out"
            if m in MODEL_PRICES else "pricing unknown")
        print(_safe(f"  {m:<42} {price}{marker}"))
    other = [m for m in models if m not in chat]
    if other:
        print(f"\n Non-chat models (speech/moderation), not usable here: "
              f"{', '.join(other)}")
    print(f"\n Set DRAFT_MODEL in .env, or pass --model to `run`.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="outreach",
        description="Resume-driven professor matching and personalized cold-email automation.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("profile", help="Parse the resume and show what was extracted")
    sp.add_argument("--resume", help="Path to resume PDF/DOCX")
    sp.set_defaults(func=cmd_profile)

    sm = sub.add_parser("models", help="List the models your provider currently offers")
    sm.add_argument("--provider", choices=sorted(PROVIDERS),
                    help="Provider to query (default: LLM_PROVIDER from .env)")
    sm.set_defaults(func=cmd_models)

    sr = sub.add_parser("run", help="Run the full match + draft pipeline")
    sr.add_argument("--mode", choices=["list", "scrape"], default="list",
                    help="list = Mode B (existing xlsx); scrape = Mode A (discovery)")
    sr.add_argument("--resume", help="Path to resume PDF/DOCX")
    sr.add_argument("--xlsx", help="Target workbook (Mode B)")
    sr.add_argument("--sheet", help="Restrict to a single sheet name")
    sr.add_argument("--sources", default="sources.yaml",
                    help="YAML/JSON list of directory URLs (Mode A)")
    sr.add_argument("--output", help="Write results to a new workbook instead of in place")
    sr.add_argument("--max-professors", type=int, help="Cap on LLM-evaluated professors")
    sr.add_argument("--min-score", type=float, help="Local match score threshold (0-1)")
    sr.add_argument("--budget", type=float, help="Hard USD budget for this run")
    sr.add_argument("--provider", choices=sorted(PROVIDERS),
                    help="LLM provider (default: LLM_PROVIDER from .env)")
    sr.add_argument("--model", help="Override the drafting model")
    sr.add_argument("--no-enrich", action="store_true", help="Skip OpenAlex lookups")
    sr.add_argument("--no-profile-hop", action="store_true",
                    help="Mode A: do not visit individual profile pages for emails")
    sr.add_argument("--no-backup", action="store_true", help="Do not back up the workbook")
    sr.add_argument("--yes", action="store_true", help="Skip the [Y/N] cost gate")
    sr.set_defaults(func=cmd_run)

    ss = sub.add_parser("send", help="Dispatch the drafted emails")
    ss.add_argument("--xlsx", help="Workbook containing the drafts")
    ss.add_argument("--sheet", help="Restrict to a single sheet name")
    ss.add_argument("--resume", help="Path to resume (for the signature block)")
    ss.add_argument("--live", action="store_true", help="Actually send (default is dry-run)")
    ss.add_argument("--dry-run", action="store_true", help="Explicit dry run (default)")
    ss.add_argument("--review", action="store_true",
                    help="Mail every draft to yourself (SMTP_FROM) instead of professors")
    ss.add_argument("--review-to", help="Mail every draft to this address instead")
    ss.add_argument("--export", action="store_true",
                    help="Write each draft as a .eml file you can open in a mail client")
    ss.add_argument("--export-dir", help="Where to write .eml files (default output/drafts)")
    ss.add_argument("--resend", action="store_true", help="Re-send rows already marked sent")
    ss.add_argument("--top", type=int,
                    help="Mail only the N highest-probability professors")
    ss.add_argument("--limit", type=int, help="Max emails this run")
    ss.add_argument("--delay-min", type=float, help="Min seconds between emails")
    ss.add_argument("--delay-max", type=float, help="Max seconds between emails")
    ss.add_argument("--min-probability", type=int,
                    help="Only send to rows at or above this probability")
    ss.add_argument("--preview", type=int, default=2,
                    help="How many full drafts to print in dry-run")
    ss.set_defaults(func=cmd_send)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n Interrupted.")
        return 130
    except ConfigError as exc:
        print(f"\n CONFIG: {exc}")
        return 1
    except Exception as exc:
        print(f"\n ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
