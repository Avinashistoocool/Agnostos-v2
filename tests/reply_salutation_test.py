"""Wrong-name greetings in reply drafts must never be mailed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outreach.config import settings
from outreach.mailer import Mailer

mailer = Mailer(settings, dry_run=True)
for name, text in (
    ("Johannes Fottner", "Dear Professor Fottner,\nThank you."),
    ("Elmar Rückert", "Dear Dr. Rueckert,\nThank you."),
    ("R.A. Pitts", "Dear Professor Pitts,\nThank you."),
    ("Johannes Fottner", "Dear Professor,\nThank you."),
):
    mailer.build_reply("test@example.edu", name, "Test", text)
try:
    mailer.build_reply("test@example.edu", "Johannes Fottner", "Test",
                       "Dear Dr. Fischer,\nThank you.")
except ValueError as exc:
    assert "names someone else" in str(exc)
else:
    raise AssertionError("Wrong-person salutation was not blocked")
print("Reply salutation tests passed")
