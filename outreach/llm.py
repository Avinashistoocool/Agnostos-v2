"""Token-optimized LLM evaluation + email drafting.

Works against any OpenAI-compatible endpoint (OpenAI, Groq, or a proxy) and
negotiates capabilities at runtime, because gateways differ in what they accept.

Design for cost control:
  * A single call per professor returns BOTH the probability score and the email draft.
  * Shared instructions sit in a stable system-prompt prefix, so providers with
    automatic prompt caching discount it on every call after the first.
  * Per-professor user messages carry only the minimal context block.
  * Structured Outputs are used when supported, with graceful downgrade to
    json_object and then to prompt-only JSON.
  * Estimation gate runs before any paid call.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from .config import CACHE_MIN_PREFIX_TOKENS, Settings
from .humanize import REWRITE_SYSTEM, build_rewrite_request, deslop, has_hard_claims
from .humanize import score as ai_score
from .models import Professor
from .resume_parser import ResumeProfile

SYSTEM_TEMPLATE = """You are an expert academic outreach strategist advising a student seeking a {position} in {geography}.

APPLICANT PROFILE
{profile}

Availability: {availability}

TASK
For each professor given, do two things:

1. SCORE the realistic probability (1-100) that this professor would accept this student for a {position}. Calibrate honestly and use the full range:
   - 80-100: near-perfect subfield overlap, funded route exists, group known to take interns
   - 60-79: strong overlap, plausible funding, realistic
   - 40-59: adjacent field or unclear funding
   - 20-39: weak overlap or strong competition
   - 1-19: wrong field, no route, or unrealistic
   Penalize: generic topic overlap, no funding route, very senior/large groups, missed deadlines.
   Reward: specific technical overlap with the student's actual projects, named funding programmes, explicit eligibility for non-EU undergraduates.

2. DRAFT a cold outreach email to that professor.

HONESTY AND FRAMING — THIS MATTERS MOST
The student is a second-year undergraduate. Their projects are coursework-scale and self-directed, NOT peer-reviewed results. Write accordingly:
- Describe what they BUILT and TRIED, never what they "achieved", "improved", "outperformed", or "demonstrated".
- Never cite metrics, accuracy figures, benchmark wins, or claims of novelty. Do not say a method "resulted in enhanced discrimination" or similar.
- Acceptable framing: "I built", "I implemented", "I was trying to see whether", "I spent the summer working on", "I got it running on".
- Explicitly allowed and encouraged: admitting limits. "on a small subset", "mostly to understand the architecture", "I am still working out why".
- Position the student as someone who wants to LEARN from this group, not as someone arriving with results. The ask is to be taught, not to be credited.
- Nothing in the email should embarrass the student if the professor asked them to defend it in a five-minute conversation.

VOICE — WRITE LIKE A PERSON, NOT A LANGUAGE MODEL
- Vary sentence length. Mix a long sentence with a short one. Some sentences can be six words.
- Use plain words: "used" not "utilised", "so" not "thus", "about" not "regarding", "I think" not "I believe it is evident that".
- Contractions are fine and good: I'm, I've, it's, don't.
- BANNED phrases: "I am writing to", "I am reaching out", "delve", "leverage", "utilise", "robust", "cutting-edge", "passionate about", "align with", "resonates", "moreover", "furthermore", "in conclusion", "I would be thrilled", "invaluable", "testament to", "deep dive", "landscape", "realm", "pivotal", "underscore", "showcase", "seamless", "comprehensive", "it is worth noting".
- No three-item lists ("X, Y, and Z"). That rhythm is the clearest LLM tell.
- Do not restate the professor's work back to them as a compliment. One specific sentence showing you actually read something is enough.
- Slight informality beats polish. A real student writes a little unevenly.

EMAIL RULES
- 130-180 words in the body. Shorter is better than padded.
- Begin with a salutation line addressing the professor by title and surname, followed by a blank line.
- Write 3 or 4 short paragraphs separated by blank lines. Never one solid block.
- Open by naming one specific thing from the professor's OWN recent work (use the supplied publications/topics; never invent a title). Say plainly what caught your interest or what you did not follow.
- Connect it to ONE thing the student actually built, described modestly, with a concrete technical detail.
- State availability, duration, and the funding route if one is supplied. Keep this factual and brief.
- One clear ask: whether they have capacity to take a summer student, and whether you may send more detail.
- Plain text, no markdown, no em dashes, no bullet points. British/neutral English.
- End with a short sign-off and the student's first name only; the signature block is appended automatically.
- Subject line: under 70 characters, lowercase-ish and specific, like a human typed it. No "Application", no colons-with-grand-titles.

OUTPUT
Return a JSON object with exactly these fields: probability, justification, subject, body.
Return only that JSON object, with no prose and no code fences."""

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["probability", "justification", "subject", "body"],
    "properties": {
        "probability": {
            "type": "integer",
            "description": "Realistic acceptance probability from 1 to 100.",
        },
        "justification": {
            "type": "string",
            "description": "Two to three sentences citing specific evidence for the score.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject line, under 70 characters.",
        },
        "body": {
            "type": "string",
            "description": ("Email body, 150-200 words. Plain text starting with a "
                            "salutation line, then 3-4 short paragraphs separated by "
                            "blank lines, then a sign-off. Use \\n for line breaks."),
        },
    },
}

USER_TEMPLATE = """Evaluate and draft for this professor.

{context}"""


GREETING_RE = re.compile(r"^(dear|hello|hi|good (morning|afternoon)|sehr geehrte)", re.I)
TITLE_PREFIX_RE = re.compile(r"^(Prof\.?|Professor|Dr\.?|PD|Mr\.?|Ms\.?|Mrs\.?)\s+", re.I)


def _salutation(professor_name: str) -> str:
    bare = TITLE_PREFIX_RE.sub("", professor_name).strip()
    while TITLE_PREFIX_RE.match(bare):  # e.g. "Prof. Dr. Anna Schmidt"
        bare = TITLE_PREFIX_RE.sub("", bare).strip()
    if not bare:
        return "Dear Professor,"
    surname = bare.split()[-1]
    title = "Prof." if re.match(r"\s*(Prof|Professor)", professor_name, re.I) else "Dr."
    return f"Dear {title} {surname},"


def _split_paragraphs(text: str, target_chunks: int = 3) -> str:
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    if len(sentences) < 4:
        return text.strip()
    per = max(2, -(-len(sentences) // target_chunks))
    chunks = [" ".join(sentences[i:i + per]) for i in range(0, len(sentences), per)]
    return "\n\n".join(c for c in chunks if c)


def tidy_body(body: str, professor_name: str) -> str:
    """Repair the two formatting faults models still produce occasionally:
    a missing salutation, and paragraphs run together into one block."""
    text = body.strip().replace("\\n", "\n").replace("\r\n", "\n")
    text = "\n".join(ln.strip() for ln in text.split("\n")).strip()

    greeting = ""
    if GREETING_RE.match(text):
        greeting, _, text = text.partition("\n")
        text = text.strip()
    else:
        greeting = _salutation(professor_name)

    # Peel off a trailing sign-off so it is never merged into a paragraph.
    signoff = ""
    parts = text.rsplit("\n\n", 1)
    if len(parts) == 2 and len(parts[1]) < 80:
        text, signoff = parts[0].strip(), parts[1].strip()

    if "\n\n" not in text:
        text = _split_paragraphs(text)

    out = f"{greeting}\n\n{text}"
    if signoff:
        out += f"\n\n{signoff}"
    return out


@dataclass
class Estimate:
    n_calls: int
    system_tokens: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_usd: float
    model: str
    cache_eligible: bool = True
    free_tier: bool = False

    def render(self) -> str:
        cache_line = (
            f"   of which cached   : ~{self.cached_input_tokens:,} (billed at the cached rate)"
            if self.cache_eligible else
            f"   cache             : inactive (prompt prefix under "
            f"{CACHE_MIN_PREFIX_TOKENS:,} tokens)"
        )
        cost_line = (" ESTIMATED COST       : $0.0000 (provider free tier)"
                     if self.free_tier else
                     f" ESTIMATED COST       : ${self.cost_usd:.4f}")
        lines = [
            "",
            "=" * 62,
            " TOKEN & COST ESTIMATE (pre-flight)",
            "=" * 62,
            f" Model                : {self.model}",
            f" Professors to call   : {self.n_calls}",
            f" System prompt        : ~{self.system_tokens:,} tokens (identical prefix each call)",
            f" Input tokens  (total): ~{self.input_tokens:,}",
            cache_line,
            f" Output tokens (total): ~{self.output_tokens:,}",
            cost_line,
            "=" * 62,
        ]
        return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Approximate OpenAI tokenization: ~4 chars/token for English prose."""
    if not text:
        return 0
    return max(1, int(len(text) / 4) + text.count("\n"))


class LLMEvaluator:
    def __init__(self, settings: Settings, profile: ResumeProfile):
        self.settings = settings
        self.profile = profile
        self._client = None
        self.system_prompt = SYSTEM_TEMPLATE.format(
            position=settings.position,
            geography=settings.geography,
            profile=profile.summary_block(),
            availability=settings.availability,
        )
        self.usage = {"input": 0, "output": 0, "cached": 0, "calls": 0, "rewrites": 0}
        # Capabilities are optimistic, then downgraded on the first rejection.
        self.caps = {
            "json_schema": True,
            "json_object": True,
            "max_completion_tokens": True,
            "temperature": True,
        }

    # --- client ---
    @property
    def client(self):
        if self._client is None:
            self.settings.require_api_key()
            from openai import OpenAI
            kwargs = {"api_key": self.settings.api_key}
            if self.settings.base_url:
                kwargs["base_url"] = self.settings.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    # --- estimation ---
    def estimate(self, professors: list[Professor], model: str | None = None) -> Estimate:
        model = model or self.settings.draft_model
        sys_tokens = estimate_tokens(self.system_prompt)
        per_user = [estimate_tokens(USER_TEMPLATE.format(context=p.context_block()))
                    for p in professors]
        n = len(professors)
        in_price, cached_price, out_price = self.settings.price(model)

        # Prompt caching is automatic, but only for sufficiently long prefixes,
        # only from the second call onwards, and only on some providers.
        cache_eligible = (self.settings.supports_prompt_cache
                          and sys_tokens >= CACHE_MIN_PREFIX_TOKENS)
        if cache_eligible:
            cached = sys_tokens * max(n - 1, 0)
            fresh = sys_tokens + sum(per_user)
        else:
            cached = 0
            fresh = sys_tokens * n + sum(per_user)
        out = n * int(self.settings.max_output_tokens * 0.55)
        if self.settings.humanize_rewrite:
            # Roughly a third of drafts trip the humanizer and get rewritten.
            rewrites = max(1, n // 3)
            fresh += rewrites * (estimate_tokens(REWRITE_SYSTEM) + 260)
            out += rewrites * 230

        cost = (fresh / 1e6 * in_price
                + cached / 1e6 * cached_price
                + out / 1e6 * out_price)
        return Estimate(n, sys_tokens, fresh + cached, out, cached,
                        round(cost, 4), model, cache_eligible,
                        free_tier=self.settings.is_free_tier)

    # --- parsing ---
    @staticmethod
    def _parse(text: str) -> dict:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Unparseable LLM response: {text[:200]}")

    # --- single call ---
    def _supports_temperature(self, model: str) -> bool:
        # Reasoning models (o-series, gpt-5) reject an explicit temperature.
        return not (model.startswith("o") or model.startswith("gpt-5"))

    def _build_request(self, model: str, message: str) -> dict:
        """Assemble a request using only the fields this endpoint has accepted.

        Gateways and proxies vary: some reject `max_completion_tokens`, some
        reject `response_format` entirely. Unsupported fields are learned once
        (see `_downgrade`) and then omitted for the rest of the run.
        """
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": message},
            ],
        }
        if self.caps["max_completion_tokens"]:
            kwargs["max_completion_tokens"] = self.settings.max_output_tokens
        else:
            kwargs["max_tokens"] = self.settings.max_output_tokens

        if self.caps["json_schema"]:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "professor_evaluation", "strict": True,
                                "schema": RESPONSE_SCHEMA},
            }
        elif self.caps["json_object"]:
            kwargs["response_format"] = {"type": "json_object"}

        if self.caps["temperature"] and self._supports_temperature(model):
            kwargs["temperature"] = 0.4
        return kwargs

    def _downgrade(self) -> str | None:
        """Turn off the most likely unsupported capability. Returns what changed."""
        for cap, label in (
            ("json_schema", "structured outputs (json_schema)"),
            ("json_object", "JSON response_format"),
            ("max_completion_tokens", "max_completion_tokens (using max_tokens)"),
            ("temperature", "temperature"),
        ):
            if self.caps[cap]:
                self.caps[cap] = False
                return label
        return None

    def evaluate_one(self, prof: Professor, model: str | None = None,
                     max_retries: int = 3) -> Professor:
        model = model or self.settings.draft_model
        message = USER_TEMPLATE.format(context=prof.context_block())

        last_error = ""
        attempt = 0
        # Downgrades do not consume a retry: they are negotiation, not failure.
        while attempt < max_retries:
            try:
                resp = self.client.chat.completions.create(
                    **self._build_request(model, message))
                choice = resp.choices[0]
                if choice.finish_reason == "length":
                    raise ValueError("response truncated; raise MAX_OUTPUT_TOKENS")
                data = self._parse(choice.message.content or "")

                u = resp.usage
                cached = 0
                details = getattr(u, "prompt_tokens_details", None)
                if details is not None:
                    cached = getattr(details, "cached_tokens", 0) or 0
                self.usage["input"] += (getattr(u, "prompt_tokens", 0) or 0) - cached
                self.usage["cached"] += cached
                self.usage["output"] += getattr(u, "completion_tokens", 0) or 0
                self.usage["calls"] += 1

                prob = int(float(data.get("probability", 0)))
                prof.probability = max(1, min(100, prob))
                prof.justification = str(data.get("justification", "")).strip()
                prof.email_subject = str(data.get("subject", "")).strip()
                prof.email_body = tidy_body(str(data.get("body", "")), prof.name)
                self._humanize(prof, model)
                prof.llm_status = f"ok ({model})"
                return prof
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                name = type(exc).__name__
                if name == "BadRequestError":
                    dropped = self._downgrade()
                    if dropped:
                        print(f"  ~ endpoint rejected {dropped}; retrying without it")
                        continue
                if name in ("AuthenticationError", "PermissionDeniedError",
                            "NotFoundError", "BadRequestError", "RuntimeError"):
                    break
                attempt += 1
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        prof.llm_status = f"failed: {last_error[:180]}"
        return prof

    # --- humanizing layer ---
    def _humanize(self, prof: Professor, model: str) -> None:
        """Free deterministic cleanup, then an LLM rewrite only if still needed."""
        body = deslop(prof.email_body)
        penalty, reasons = ai_score(body)
        needs_rewrite = (penalty >= self.settings.humanize_threshold
                         or has_hard_claims(body))

        if needs_rewrite and self.settings.humanize_rewrite:
            rewritten = self._rewrite(body, model)
            if rewritten:
                candidate = deslop(tidy_body(rewritten, prof.name))
                new_penalty, new_reasons = ai_score(candidate)
                # Keep the rewrite only if it is genuinely less robotic.
                if new_penalty <= penalty:
                    body, penalty, reasons = candidate, new_penalty, new_reasons
                    prof.llm_status += " +rewrite"

        prof.email_body = body
        prof.ai_score = penalty
        prof.ai_flags = "; ".join(reasons)
        if has_hard_claims(body):
            prof.ai_flags = ("UNVERIFIED CLAIM - review before sending; "
                             + prof.ai_flags).strip("; ")

    def _rewrite(self, body: str, model: str) -> str:
        kwargs = {
            "model": model,
            "messages": build_rewrite_request(body),
        }
        if self.caps["max_completion_tokens"]:
            kwargs["max_completion_tokens"] = self.settings.max_output_tokens
        else:
            kwargs["max_tokens"] = self.settings.max_output_tokens
        if self.caps["temperature"] and self._supports_temperature(model):
            kwargs["temperature"] = 0.8  # higher temperature reads less uniform
        try:
            resp = self.client.chat.completions.create(**kwargs)
            u = resp.usage
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            self.usage["input"] += (getattr(u, "prompt_tokens", 0) or 0) - cached
            self.usage["cached"] += cached
            self.usage["output"] += getattr(u, "completion_tokens", 0) or 0
            self.usage["rewrites"] += 1
            text = (resp.choices[0].message.content or "").strip()
            return re.sub(r"^```\w*\s*|\s*```$", "", text).strip('"\n ')
        except Exception:
            return ""  # a failed rewrite is never fatal; the deslopped body stands

    def evaluate_all(self, professors: list[Professor], model: str | None = None,
                     progress=None, budget_usd: float | None = None) -> list[Professor]:
        model = model or self.settings.draft_model
        consecutive_failures = 0
        for i, prof in enumerate(professors, 1):
            if budget_usd is not None and self.actual_cost(model) >= budget_usd:
                prof.llm_status = "skipped: budget exhausted"
                continue
            self.evaluate_one(prof, model=model)
            if progress:
                progress(i, len(professors), prof)
            ok = prof.llm_status.startswith("ok")
            consecutive_failures = 0 if ok else consecutive_failures + 1
            if consecutive_failures >= 3:
                for rest in professors[i:]:
                    rest.llm_status = "skipped: aborted after repeated failures"
                print("  ! Three consecutive failures; aborting to avoid wasted spend.")
                break
        return professors

    def actual_cost(self, model: str | None = None) -> float:
        model = model or self.settings.draft_model
        in_price, cached_price, out_price = self.settings.price(model)
        u = self.usage
        return (u["input"] / 1e6 * in_price
                + u["cached"] / 1e6 * cached_price
                + u["output"] / 1e6 * out_price)

    def usage_report(self, model: str | None = None) -> str:
        u = self.usage
        extra = f" | rewrites {u['rewrites']}" if u.get("rewrites") else ""
        cost = ("$0.0000 (free tier)" if self.settings.is_free_tier
                else f"${self.actual_cost(model):.4f}")
        return (
            f"LLM calls: {u['calls']}{extra} | input {u['input']:,} | "
            f"cached {u['cached']:,} | output {u['output']:,} | "
            f"actual cost {cost}"
        )


def confirm_gate(estimate: Estimate, budget_usd: float, assume_yes: bool = False) -> bool:
    """Display the estimate and require explicit [Y/N] confirmation."""
    print(estimate.render())
    if estimate.free_tier:
        print(" This provider's free tier covers the run; nothing will be billed.")
    elif estimate.cost_usd > budget_usd:
        print(f" !! Estimate ${estimate.cost_usd:.4f} EXCEEDS your budget cap of ${budget_usd:.2f}.")
        print("    Lower --max-professors, raise BUDGET_USD, or switch to "
              "--provider groq (free).")
    if assume_yes:
        print(" --yes supplied; proceeding without prompt.\n")
        return True
    try:
        answer = input(" Proceed with the LLM calls? [Y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def list_models(settings: Settings) -> list[str]:
    """Live model list from whichever provider is configured."""
    settings.require_api_key()
    from openai import OpenAI
    kwargs = {"api_key": settings.api_key}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return sorted(m.id for m in OpenAI(**kwargs).models.list().data)
