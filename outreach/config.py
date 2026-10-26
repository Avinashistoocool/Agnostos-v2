"""Central configuration. Values come from .env with sane defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _i(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _b(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "y", "on"}


# Pricing in USD per 1M tokens: (input, cached_input, output).
#
# Groq models are listed at their paid on-demand rate so the estimate stays
# honest if you ever leave the free tier, but `Settings.is_free_tier` reports
# them as free, which is what the cost gate shows by default.
MODEL_PRICES = {
    # --- OpenAI ---
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "o4-mini": (1.10, 0.275, 4.40),
    # --- Groq (no prompt caching; cached rate mirrors input) ---
    "openai/gpt-oss-120b": (0.15, 0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.10, 0.50),
    "openai/gpt-oss-safeguard-20b": (0.10, 0.10, 0.50),
    "qwen/qwen3.8-27b": (0.29, 0.29, 0.59),
    "allam-2-7b": (0.05, 0.05, 0.08),
}
DEFAULT_PRICE = (2.00, 0.50, 8.00)

# Built-in provider endpoints. All are OpenAI-compatible.
#
#   free_tier=True means the provider has a no-cost tier that comfortably
#   covers a normal run, so the pre-flight gate reports $0.00 rather than a
#   misleading on-demand figure.
PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "default_model": "openai/gpt-oss-120b", "prompt_cache": False,
             "free_tier": True, "console": "https://console.groq.com/keys"},
    "openai": {"base_url": "", "key_env": "OPENAI_API_KEY",
               "default_model": "gpt-4.1", "prompt_cache": True,
               "free_tier": False, "console": "https://platform.openai.com/api-keys"},
}

# Values shipped in .env.example. Treated as "not configured" so users get a
# clear message instead of a failure deep inside an API or SMTP call.
PLACEHOLDERS = (
    "replace_me", "sk-replace_me", "your_app_password", "your-university",
    "your_full_name", "path/to/your", "path\\to\\your", "you@example.com",
)


def looks_like_placeholder(value) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    return any(token in text for token in PLACEHOLDERS)


class ConfigError(RuntimeError):
    """Raised when .env is missing something the command actually needs."""


def _require_file(value, env_key: str, what: str) -> Path:
    if looks_like_placeholder(value):
        raise ConfigError(
            f"{env_key} is not set. Point it at {what} in your .env file.\n"
            f"   Copy .env.example to .env and edit section 1.")
    path = Path(value).expanduser()
    if not path.exists():
        raise ConfigError(f"{env_key} points at a file that does not exist: {path}")
    return path

# OpenAI only caches prompt prefixes at or above this length, and does so
# automatically. Below it, every input token is billed at the full rate.
CACHE_MIN_PREFIX_TOKENS = 1024


@dataclass
class Settings:
    # --- Paths (no defaults: these are personal and must come from .env) ---
    resume_path: Path = Path(os.getenv("RESUME_PATH", ""))
    target_xlsx: Path = Path(os.getenv("TARGET_XLSX", ""))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(ROOT / "output")))
    attachments: list[str] = field(default_factory=lambda: [
        p.strip() for p in os.getenv("ATTACHMENTS", "").split(";") if p.strip()
    ])

    # --- LLM ---
    provider: str = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", PROVIDERS["groq"]["base_url"])
    score_model: str = os.getenv("SCORE_MODEL", "")
    draft_model: str = os.getenv("DRAFT_MODEL", "")
    budget_usd: float = _f("BUDGET_USD", 5.0)
    max_professors: int = _i("MAX_PROFESSORS", 50)
    draft_top_n: int = _i("DRAFT_TOP_N", 50)
    min_local_score: float = _f("MIN_LOCAL_SCORE", 0.25)
    max_output_tokens: int = _i("MAX_OUTPUT_TOKENS", 1100)

    # --- Humanizing layer ---
    humanize_rewrite: bool = _b("HUMANIZE_REWRITE", True)
    humanize_threshold: int = _i("HUMANIZE_THRESHOLD", 10)

    # --- Applicant profile ---
    position: str = os.getenv("POSITION", "summer research internship (undergraduate)")
    geography: str = os.getenv("GEOGRAPHY", "Europe (EU + Switzerland + UK)")
    availability: str = os.getenv("AVAILABILITY", "May-July 2027, 8-12 weeks, flexible")
    # Whether the student can cover their own travel/living costs. Blank = not stated.
    can_self_fund: str = os.getenv("CAN_SELF_FUND", "").strip().lower()
    self_fund_note: str = os.getenv("SELF_FUND_NOTE", "").strip()

    @property
    def funding_stance(self) -> str:
        note = f" ({self.self_fund_note})" if self.self_fund_note else ""
        if self.can_self_fund in {"1", "true", "yes", "y", "on"}:
            return ("The student CAN cover their own travel and living expenses" + note
                    + ". If the professor raises funding, a stipend, or lack of money, say "
                    "plainly that they can fund themselves, so funding need not be an obstacle.")
        if self.can_self_fund in {"0", "false", "no", "n", "off"}:
            return ("The student CANNOT cover their own expenses and needs a funded position"
                    + note + ". If the professor says there is no funding, thank them and ask "
                    "whether they know a fellowship, programme, or colleague that could fund "
                    "a visit. Never offer to pay their own way.")
        return ("Self-funding not stated. If funding comes up, do not promise either way; "
                "write [FILL: can you cover your own expenses?].")

    # --- Enrichment ---
    use_openalex: bool = _b("USE_OPENALEX", True)
    openalex_api_key: str = os.getenv("OPENALEX_API_KEY", "")
    openalex_mailto: str = os.getenv("OPENALEX_MAILTO", os.getenv("SMTP_FROM", ""))
    openalex_works: int = _i("OPENALEX_WORKS", 4)

    # --- Batched discovery (`discover --count N --batches K`) ---
    discover_count: int = _i("DISCOVER_COUNT", 1000)
    discover_batches: int = _i("DISCOVER_BATCHES", 4)
    discover_queries: str = os.getenv("DISCOVER_QUERIES", "")
    discover_countries: str = os.getenv("DISCOVER_COUNTRIES", "europe")
    discover_since: int = _i("DISCOVER_SINCE", 2021)
    discover_max_pages: int = _i("DISCOVER_MAX_PAGES", 40)
    # Restrict discovery to the region's N best universities (0 = off).
    discover_top_universities: int = _i("DISCOVER_TOP_UNIVERSITIES", 0)
    discover_prestige_weight: float = _f("DISCOVER_PRESTIGE_WEIGHT", 1.0)
    verify_workers: int = _i("VERIFY_WORKERS", 4)

    # --- Email ---
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = _i("SMTP_PORT", 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_security: str = os.getenv("SMTP_SECURITY", "starttls")  # starttls | ssl | none
    smtp_timeout: float = _f("SMTP_TIMEOUT", 60)
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "")
    reply_to: str = os.getenv("REPLY_TO", "")
    send_delay_min: float = _f("SEND_DELAY_MIN", 90)
    send_delay_max: float = _f("SEND_DELAY_MAX", 240)
    daily_send_cap: int = _i("DAILY_SEND_CAP", 25)
    send_min_probability: int = _i("SEND_MIN_PROBABILITY", 0)
    # Recipient-local hours to send in, e.g. "9-11". Blank = any time.
    send_local_window: str = os.getenv("SEND_LOCAL_WINDOW", "")

    # --- `resend`: re-deliver the original email from a second account ---
    resend_smtp_host: str = os.getenv("RESEND_SMTP_HOST", "smtp.gmail.com")
    resend_smtp_port: int = _i("RESEND_SMTP_PORT", 465)
    resend_smtp_security: str = os.getenv("RESEND_SMTP_SECURITY", "ssl")
    resend_smtp_user: str = os.getenv("RESEND_SMTP_USER", "")
    resend_smtp_password: str = os.getenv("RESEND_SMTP_PASSWORD", "").replace(" ", "")
    resend_smtp_from: str = os.getenv("RESEND_SMTP_FROM", "") or os.getenv("RESEND_SMTP_USER", "")
    resend_daily_cap: int = _i("RESEND_DAILY_CAP", 100)
    resend_min_days: int = _i("RESEND_MIN_DAYS", 4)

    # --- Reply tracking (`check-replies`). Defaults reuse the SMTP login. ---
    imap_host: str = os.getenv("IMAP_HOST", "")
    imap_port: int = _i("IMAP_PORT", 993)
    imap_user: str = os.getenv("IMAP_USER", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    imap_folders: str = os.getenv("IMAP_FOLDERS", "INBOX;SPAM;Junk;Junk Email")

    # --- Scraper ---
    proxy_server: str = os.getenv("PROXY_SERVER", "")
    proxy_username: str = os.getenv("PROXY_USERNAME", "")
    proxy_password: str = os.getenv("PROXY_PASSWORD", "")
    scrape_delay_min: float = _f("SCRAPE_DELAY_MIN", 4)
    scrape_delay_max: float = _f("SCRAPE_DELAY_MAX", 11)
    scrape_headless: bool = _b("SCRAPE_HEADLESS", True)
    respect_robots: bool = _b("RESPECT_ROBOTS", True)
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    )

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(
                f"Unknown LLM_PROVIDER {self.provider!r}. "
                f"Choose one of: {', '.join(PROVIDERS)}")
        spec = PROVIDERS[self.provider]
        if not self.draft_model:
            self.draft_model = spec["default_model"]
        if not self.score_model:
            self.score_model = spec["default_model"]

    @property
    def api_key(self) -> str:
        return self.groq_api_key if self.provider == "groq" else self.openai_api_key

    @property
    def base_url(self) -> str:
        return self.groq_base_url if self.provider == "groq" else self.openai_base_url

    @property
    def key_env_name(self) -> str:
        return PROVIDERS[self.provider]["key_env"]

    @property
    def supports_prompt_cache(self) -> bool:
        return PROVIDERS[self.provider]["prompt_cache"]

    @property
    def is_free_tier(self) -> bool:
        """True when the configured provider bills nothing for a normal run."""
        return PROVIDERS[self.provider]["free_tier"]

    @property
    def console_url(self) -> str:
        return PROVIDERS[self.provider]["console"]

    @property
    def has_api_key(self) -> bool:
        return not looks_like_placeholder(self.api_key)

    def require_api_key(self) -> None:
        if not self.has_api_key:
            raise ConfigError(
                f"{self.key_env_name} is not set (LLM_PROVIDER={self.provider}).\n"
                f"   Get a key at {self.console_url}, then put it in your .env file.\n"
                f"   Groq's free tier covers a full run at no cost: LLM_PROVIDER=groq")

    def require_resume(self, override: str | Path | None = None) -> Path:
        return _require_file(override or self.resume_path, "RESUME_PATH",
                             "your resume PDF or DOCX")

    def require_target_xlsx(self, override: str | Path | None = None) -> Path:
        return _require_file(override or self.target_xlsx, "TARGET_XLSX",
                             "the professor list workbook (.xlsx)")

    def price(self, model: str) -> tuple[float, float, float]:
        """(input, cached_input, output) USD per 1M tokens."""
        if self.is_free_tier:
            return (0.0, 0.0, 0.0)
        return MODEL_PRICES.get(model, DEFAULT_PRICE)

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
