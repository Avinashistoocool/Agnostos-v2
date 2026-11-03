"""First-email cap survives a stopped/restarted sender."""
from dataclasses import replace
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outreach.config import settings
from outreach.mailer import Mailer

today = datetime.now().strftime("%Y-%m-%d")
config = replace(settings, daily_send_cap=2, send_delay_min=0, send_delay_max=0)
rows = [
    {"sheet": "Targets", "row": i, "email": f"p{i}@example.edu",
     "send_status": "", "probability": 90, "email_status": "ok"}
    for i in range(2, 6)
]


def sender():
    mailer = Mailer(config, dry_run=False)

    def send_one(row):
        message = EmailMessage()
        message["Message-ID"] = f"<{row['row']}@example.edu>"
        mailer.sent_count += 1
        return {"status": "sent", "message": message}

    mailer.send_one = send_one
    return mailer


first = sender().send_batch(rows, initial_sent_by_date={today: 1})
assert len(first) == 1 and first[0]["status"] == "sent", first
rows[0]["send_status"] = "sent"
second = sender().send_batch(rows, initial_sent_by_date={today: 2})
assert second == [], second
assert len(sender().send_batch(rows, initial_sent_by_date={today: 0})) == 2
print("Daily first-email cap tests passed")
