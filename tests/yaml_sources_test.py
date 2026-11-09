"""Default YAML discovery sources work without a compiled PyYAML extension."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach.cli import _load_sources

base = Path(__file__).resolve().parents[1]
sources = _load_sources(base / "sources.yaml")
assert sources and all(row.get("url") and row.get("institution") for row in sources)

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "sources.yaml"
    path.write_text("sources:\n  - url: https://example.org/staff\n"
                    "    institution: Institute of Physics\n"
                    "    country: UK\n", encoding="utf-8")
    assert _load_sources(path)[0]["institution"] == "Institute of Physics"
    path = path.with_suffix(".json")
    path.write_text('{"sources":[{"url":"https://example.org/staff",'
                    '"institution":"Institute of Physics"}]}', encoding="utf-8")
    assert _load_sources(path)[0]["institution"] == "Institute of Physics"
print("YAML and JSON source tests passed")
