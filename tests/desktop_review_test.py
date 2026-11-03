"""Isolated, live-shaped v2 workbook and reply queue; never touches real output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from unittest.mock import patch

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_review.app import start
from desktop_review.storage import ReviewError, Workspace, read_queue, update_queue


class DesktopReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / "build" / "desktop-review-tests"
        if cls.scratch.exists():
            shutil.rmtree(cls.scratch)
        cls.workspace_path = cls.scratch / "Agnostos-v2"
        output = cls.workspace_path / "output"
        output.mkdir(parents=True)
        (cls.workspace_path / "outreach").mkdir()
        (cls.workspace_path / "outreach" / "cli.py").write_text(
            "# fixture: queue_operation(settings.output_dir", encoding="utf-8")
        (cls.workspace_path / "outreach" / "replier.py").write_text(
            "# fixture: write_queue(path,", encoding="utf-8")
        (cls.workspace_path / "outreach" / "queue_store.py").write_text(
            "# fixture coordinated writer", encoding="utf-8")
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Professor Name", "Email Address", "Custom Email Draft",
                      "Send Status", "Sent At", "Reply Status"])
        sheet.append(["A", "a@example.org", "Draft A", "sent", "2026-10-30", "replied"])
        sheet.append(["B", "b@example.org", "Draft B", "", "", ""])
        sheet.append(["C", "c@example.org", "", "review-sent", "", ""])
        workbook.save(output / "professors.xlsx")
        workbook.close()
        cls.queue = [
            {"email": "a@example.org", "name": "A", "subject": "Re: A",
             "their_message": "Hello", "summary": "Reply", "action": "reply",
             "body": "Original", "approved": False, "drafted_at": "2026-11-03", "sent_at": ""},
            {"email": "b@example.org", "name": "B", "subject": "Re: B",
             "their_message": "Thanks", "summary": "Complete", "action": "reply",
             "body": "Already sent", "approved": True, "drafted_at": "2026-11-02",
             "sent_at": "2026-11-03 10:00:00"},
        ]
        (output / "reply_queue.json").write_text(
            json.dumps(cls.queue, ensure_ascii=False), encoding="utf-8")
        (output / "conversations.html").write_text(
            '<!doctype html><title>Saved conversation</title><p>Saved locally</p>',
            encoding="utf-8")
        cls.store = Workspace(cls.scratch / "config")
        cls.server, cls.thread, cls.token, cls.address = start(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=10)
        cls.server.server_close()
        shutil.rmtree(cls.scratch)

    def setUp(self):
        self.store.path = None
        path = self.workspace_path / "output" / "reply_queue.json"
        if path.is_symlink():
            path.unlink()
        path.write_text(json.dumps(self.queue, ensure_ascii=False), encoding="utf-8")

    def request(self, path, body=None, token=None, origin=None):
        headers = {"X-Desktop-Token": token if token is not None else self.token}
        if origin:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.address + path, headers=headers,
            data=json.dumps(body).encode("utf-8") if body is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_workspace_selection_stats_and_conversations(self):
        self.assertEqual(self.request("/api/stats")[0], 409)
        self.assertEqual(self.request("/api/queue", token="not-the-token")[0], 403)
        self.assertEqual(self.request("/api/workspace", {"path": str(self.scratch)})[0], 400)
        self.assertEqual(self.request("/api/workspace", {"path": str(self.workspace_path)})[0], 200)
        self.assertEqual(Workspace(self.scratch / "config").path, self.workspace_path)
        status, stats = self.request("/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(stats["counts"], {"total": 3, "with_email": 3, "drafted": 2})
        self.assertEqual((stats["sent"], stats["review_sent"]), (1, 1))
        self.assertIn("Saved locally", self.request("/api/conversations")[1]["html"])
        (self.workspace_path / "output" / "conversations.html").write_text(
            "<p>Refreshed file</p>", encoding="utf-8")
        self.assertIn("Refreshed file", self.request("/api/conversations")[1]["html"])
        self.assertEqual(self.request("/api/stats", origin="https://not-local.example")[0], 403)

    def test_selected_approval_stale_version_and_sent_protection(self):
        self.store.select(str(self.workspace_path))
        version = self.request("/api/queue")[1]["version"]
        self.assertEqual(self.request("/api/queue/1", {
            "version": version, "body": "Changed", "approved": False})[0], 409)
        self.assertEqual(self.request("/api/queue/0", {
            "version": version, "body": "Edited by reviewer", "approved": True})[0], 200)
        queue = read_queue(self.store)
        self.assertEqual(queue["items"][0]["body"], "Edited by reviewer")
        self.assertTrue(queue["items"][0]["approved"])
        self.assertEqual(queue["items"][1]["body"], "Already sent")
        self.assertEqual(self.request("/api/queue/0", {
            "version": version, "body": "stale", "approved": True})[0], 409)
        self.assertEqual(self.request("/api/queue/0", {
            "version": queue["version"], "body": "Changed",
            "approved": False, "sent_at": ""})[0], 400)

    def test_cli_queue_lock_and_atomic_sender_save(self):
        self.store.select(str(self.workspace_path))
        version = read_queue(self.store)["version"]
        script = """
import sys
from pathlib import Path
from outreach.queue_store import queue_operation
from outreach.replier import load_queue, save_queue
path = Path(sys.argv[1])
with queue_operation(path.parent):
    print("locked", flush=True)
    sys.stdin.readline()
    items = load_queue(path)
    items[0]["sent_at"] = "2026-11-03 12:00:00"
    save_queue(path, items)
"""
        child = subprocess.Popen(
            [sys.executable, "-c", script,
             str(self.workspace_path / "output" / "reply_queue.json")],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            self.assertEqual(self.request("/api/queue/0", {
                "version": version, "body": "Too late", "approved": False})[0], 409)
            output, error = child.communicate(input="\n", timeout=15)
            self.assertEqual(child.returncode, 0, error)
            self.assertEqual(output, "")
            self.assertEqual(self.request("/api/queue/0", {
                "version": version, "body": "Stale edit", "approved": False})[0], 409)
            queue = read_queue(self.store)
            self.assertEqual(queue["items"][0]["body"], "Original")
            self.assertTrue(queue["items"][0]["sent_at"])
            self.assertEqual(self.request("/api/queue/0", {
                "version": queue["version"], "body": "Edit sent", "approved": False})[0], 409)
        finally:
            if child.poll() is None:
                child.communicate(input="\n", timeout=15)

    def test_cli_replies_dispatch_holds_operation_lock(self):
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
            from outreach import cli
        from outreach.queue_store import queue_operation
        output = self.workspace_path / "output"
        args = SimpleNamespace(command="replies", live=False, send=False,
                               func=lambda _: 42)
        parser = SimpleNamespace(parse_args=lambda _: args)
        settings = SimpleNamespace(output_dir=output, ensure_dirs=lambda: None)
        with patch.object(cli, "build_parser", return_value=parser), \
             patch.object(cli, "settings", settings), \
             patch("outreach.queue_store.queue_operation", wraps=queue_operation) as lock:
            self.assertEqual(cli.main([]), 42)
            lock.assert_called_once_with(output, timeout=10)

    def test_existing_live_sender_lock_blocks_review(self):
        self.store.select(str(self.workspace_path))
        version = read_queue(self.store)["version"]
        script = """
import sys
from pathlib import Path
from outreach.locks import InstanceLock
with InstanceLock(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.readline()
"""
        child = subprocess.Popen(
            [sys.executable, "-c", script,
             str(self.workspace_path / "output" / ".replies.lock")],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            self.assertEqual(self.request("/api/queue/0", {
                "version": version, "body": "Must wait", "approved": False})[0], 409)
            _, error = child.communicate(input="\n", timeout=15)
            self.assertEqual(child.returncode, 0, error)
            self.assertEqual(read_queue(self.store)["items"][0]["body"], "Original")
        finally:
            if child.poll() is None:
                child.communicate(input="\n", timeout=15)

    def test_old_workspace_remains_viewable_but_cannot_edit(self):
        self.store.select(str(self.workspace_path))
        marker = self.workspace_path / "outreach" / "queue_store.py"
        marker.unlink()
        try:
            self.assertEqual(self.request("/api/stats")[0], 200)
            queue = self.request("/api/queue")[1]
            self.assertFalse(queue["review_supported"])
            self.assertEqual(self.request("/api/queue/0", {
                "version": queue["version"], "body": "Unsafe", "approved": False})[0], 409)
            self.assertEqual(read_queue(self.store)["items"][0]["body"], "Original")
        finally:
            marker.write_text("# fixture coordinated writer", encoding="utf-8")

    def test_no_send_routes_or_escape(self):
        self.store.select(str(self.workspace_path))
        for route in ("/api/send", "/api/resend", "/api/replies/send", "/api/restart"):
            self.assertEqual(self.request(route, {})[0], 404, route)
        self.assertEqual(self.request("/api/queue/../../send", {})[0], 404)
        with self.assertRaises(ReviewError):
            self.store.file("../.env")

    def test_workspace_symlink_escape(self):
        self.store.select(str(self.workspace_path))
        outside = self.scratch / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        if hasattr(os, "symlink"):
            try:
                queue_path = self.workspace_path / "output" / "reply_queue.json"
                queue_path.unlink()
                queue_path.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks require privileges on this Windows machine")
            try:
                with self.assertRaises(ReviewError):
                    read_queue(self.store)
            finally:
                queue_path.unlink(missing_ok=True)

    def test_browser_view_review_offline(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            self.skipTest("Optional Playwright browser tests are not installed")
        self.store.select(str(self.workspace_path))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                external = []

                def offline(route):
                    if urlsplit(route.request.url).hostname == "127.0.0.1":
                        route.continue_()
                    else:
                        external.append(route.request.url)
                        route.abort()

                page.route("**/*", offline)
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(self.address + "/#" + self.token)
                expect(page.locator("#metrics")).to_contain_text("Researchers")
                page.get_by_role("button", name="Conversations").click()
                expect(page.locator("#conversations-updated")).to_contain_text("Showing saved file")
                frame = page.frame_locator("#conversations-frame")
                expect(frame.locator("body")).to_contain_text("Saved locally")
                page.get_by_role("button", name="Reply drafts").click()
                expect(page.locator("#queue-count")).to_contain_text("2 items")
                sent = page.locator(".draft.sent")
                expect(sent.locator("textarea")).to_have_attribute("readonly", "")
                unsent = page.locator(".draft:not(.sent)")
                unsent.locator("textarea").fill("Approved via UI")
                unsent.locator('input[type="checkbox"]').check()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/queue/0")
                    and response.request.method == "POST"
                ) as saving:
                    unsent.get_by_role("button", name="Save this draft").click()
                self.assertEqual(saving.value.status, 200, saving.value.text())
                expect(unsent.locator("textarea")).to_have_value("Approved via UI")
                self.assertEqual(read_queue(self.store)["items"][0]["body"], "Approved via UI")
                self.assertTrue(read_queue(self.store)["items"][0]["approved"])
                self.assertEqual(external, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
