"""Native Qt desktop controls for the existing v2 CLI and local workspace."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .commands import COMMANDS
from .jobs import Jobs
from .settings import FIELDS, SECRETS
from .storage import (
    ReviewError, Workspace, read_drafts, read_queue, statistics, update_draft, update_queue,
)

def suggestion() -> str | None:
    import sys
    for candidate in (Path.cwd(), Path(sys.executable).resolve().parent,
                      Path(__file__).resolve().parents[1]):
        for path in (candidate, *candidate.parents):
            try:
                return str(Workspace.validate(str(path)))
            except ReviewError:
                pass
    return None


class ConversationText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script"}:
            self.hidden += 1
        elif tag in {"header", "section", "h2", "p", "div", "br", "a"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"header", "section", "h2", "p"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data)


def button(label: str, action) -> QPushButton:
    control = QPushButton(label)
    control.clicked.connect(action)
    return control


class DesktopWindow(QMainWindow):
    def __init__(self, workspace: Workspace):
        super().__init__()
        self.workspace = workspace
        self.jobs = Jobs(workspace)
        self.queue = {"version": "", "items": []}
        self.drafts = {"version": "", "items": [], "page": 0, "total": 0}
        self.active_id: str | None = None
        self._asked_prompt: tuple[str, str] | None = None
        self._controls = {}
        self.setWindowTitle("Agnostos v2 · Desktop")
        self.resize(1250, 850)
        shell = QWidget()
        main = QVBoxLayout(shell)
        top = QHBoxLayout()
        title = QLabel("AGNOSTOS  /  DESKTOP")
        title.setObjectName("brand")
        self.location = QLabel("")
        self.location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.location)
        top.addWidget(button("Choose workspace", self.choose_workspace))
        main.addLayout(top)
        self.tabs = QTabWidget()
        self.overview = self._overview()
        self.conversations = self._conversations()
        self.replies = self._replies()
        self.first_drafts = self._first_drafts()
        self.setup = self._setup()
        self.tools = self._tools()
        self.job_view = self._jobs()
        for label, widget in (
            ("Dashboard", self.overview), ("Conversations", self.conversations),
            ("Reply drafts", self.replies), ("First-email drafts", self.first_drafts),
            ("Setup", self.setup),
            ("CLI tools", self.tools), ("Jobs & progress", self.job_view),
        ):
            self.tabs.addTab(widget, label)
        self.tabs.currentChanged.connect(self._tab_changed)
        main.addWidget(self.tabs)
        self.setCentralWidget(shell)
        self.setStyleSheet("""
            QWidget { background:#f6f7fb; color:#202d42; font:10pt 'Segoe UI'; }
            QMainWindow { background:#f6f7fb; }
            QLabel#brand { font-size:17pt; font-weight:700; color:#233d6c; }
            QTabWidget::pane, QGroupBox { border:1px solid #d5deeb; border-radius:9px; }
            QTabBar::tab { background:#e9eef6; padding:11px 16px; }
            QTabBar::tab:selected { background:#284b83; color:white; }
            QPushButton { background:#284b83; color:white; padding:8px 13px;
                          border:0; border-radius:6px; }
            QPushButton:hover { background:#38639f; }
            QPushButton:disabled { background:#aeb8c7; }
            QLineEdit, QComboBox, QPlainTextEdit, QListWidget {
                background:white; border:1px solid #cbd4e1; border-radius:5px; padding:5px;
            }
            QGroupBox { background:white; margin-top:12px; padding:13px;
                        font-weight:600; }
            QGroupBox::title { subcontrol-origin:margin; left:12px; }
        """)
        self._workspace_changed()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_jobs)
        self.timer.start(1800)
        if not workspace.path:
            QTimer.singleShot(100, self.choose_workspace)

    def notify(self, error: Exception | str):
        QMessageBox.warning(self, "Agnostos", str(error))

    def choose_workspace(self):
        if self.jobs.process is not None and self.jobs.process.poll() is None:
            self.notify("Wait for the current desktop job before changing workspace.")
            return
        try:
            if any(row["status"] == "detached" for row in self.jobs.list()):
                self.notify("A detached CLI job is still running; wait for it to finish.")
                return
        except ReviewError:
            pass
        default = str(self.workspace.path or suggestion() or Path.cwd())
        chosen = QFileDialog.getExistingDirectory(self, "Existing Agnostos-v2 repository", default)
        if not chosen:
            return
        try:
            self.workspace.select(chosen)
            self.active_id = None
            self._workspace_changed()
        except ReviewError as exc:
            self.notify(exc)

    def _workspace_changed(self):
        self.tabs.setEnabled(bool(self.workspace.path))
        self.location.setText(str(self.workspace.path or "Choose an existing v2 workspace"))
        if self.workspace.path:
            self.refresh_overview()
            self.refresh_queue()
            self.refresh_drafts()
            self.refresh_settings()
            self.refresh_jobs()

    def _tab_changed(self, tab: int):
        if not self.workspace.path:
            return
        if tab == 0:
            self.refresh_overview()
        elif tab == 1:
            self.refresh_conversations()
        elif tab == 2:
            self.refresh_queue()
        elif tab == 3:
            self.refresh_drafts()
        elif tab == 4:
            self.refresh_settings()
        elif tab == 6:
            self.refresh_jobs()

    def _overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("WORKBOOK SUMMARY · output\\professors.xlsx"))
        self.metrics = QLabel("Select a workspace")
        self.metrics.setWordWrap(True)
        self.metrics.setStyleSheet("font-size:16pt; font-weight:600; padding:22px; background:white")
        layout.addWidget(self.metrics)
        layout.addWidget(button("Refresh workbook", self.refresh_overview))
        layout.addStretch()
        return page

    def refresh_overview(self):
        try:
            values = statistics(self.workspace)
            counts = values["counts"]
            self.metrics.setText(
                f"Researchers  {counts['total']}     With email  {counts['with_email']}\n"
                f"Drafted  {counts['drafted']}     Sent  {values['sent']}     "
                f"Review copies  {values['review_sent']}")
        except ReviewError as exc:
            self.metrics.setText(str(exc))

    def _conversations(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Latest SAVED output\\conversations.html · Refresh reads local HTML only; no IMAP"))
        search = QLineEdit()
        search.setPlaceholderText("Find text in saved conversations")
        self.conversation_text = QPlainTextEdit()
        self.conversation_text.setReadOnly(True)
        search.returnPressed.connect(lambda: self.conversation_text.find(search.text()))
        layout.addWidget(search)
        layout.addWidget(button("Refresh saved file", self.refresh_conversations))
        layout.addWidget(self.conversation_text)
        return page

    def refresh_conversations(self):
        try:
            path = self.workspace.file("conversations.html")
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ReviewError(413, "Conversation file is too large to display")
            parser = ConversationText()
            parser.feed(path.read_text(encoding="utf-8"))
            self.conversation_text.setPlainText(" ".join(parser.parts))
        except (OSError, ReviewError) as exc:
            self.conversation_text.setPlainText(str(exc))

    def _replies(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        warning = QLabel("Approval lets the separate scheduled CLI (or a confirmed GUI live job) "
                         "send this unsent draft later. Sent replies are read-only.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addWidget(button("Reload queue from disk", self.refresh_queue))
        splitter = QSplitter()
        self.reply_list = QListWidget()
        self.reply_list.currentRowChanged.connect(self.show_reply)
        right = QWidget()
        form = QVBoxLayout(right)
        self.reply_details = QLabel("")
        self.reply_details.setWordWrap(True)
        self.reply_body = QPlainTextEdit()
        self.reply_approved = QCheckBox("Approve this individual unsent reply")
        form.addWidget(self.reply_details)
        form.addWidget(self.reply_body)
        form.addWidget(self.reply_approved)
        form.addWidget(button("Save selected draft", self.save_reply))
        splitter.addWidget(self.reply_list)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)
        return page

    def refresh_queue(self):
        try:
            self.queue = read_queue(self.workspace)
            self.reply_list.clear()
            for item in self.queue["items"]:
                state = "SENT" if item.get("sent_at") else "APPROVED" if item.get("approved") else "draft"
                self.reply_list.addItem(f"[{state}] {item.get('name', '')} · {item.get('email', '')}")
            if self.reply_list.count():
                self.reply_list.setCurrentRow(0)
        except ReviewError as exc:
            self.reply_details.setText(str(exc))

    def show_reply(self, index: int):
        items = self.queue["items"]
        if index < 0 or index >= len(items):
            return
        item = items[index]
        self.reply_details.setText(
            f"{item.get('name', '')} <{item.get('email', '')}>\n"
            f"{item.get('subject', '')}  ·  {item.get('summary', '')}\n\n"
            f"They wrote: {item.get('their_message', '')[:1500]}")
        self.reply_body.setPlainText(item.get("body") or "")
        self.reply_body.setReadOnly(bool(item.get("sent_at")))
        self.reply_approved.setChecked(bool(item.get("approved")))
        self.reply_approved.setEnabled(not item.get("sent_at") and item.get("action") != "none")

    def save_reply(self):
        index = self.reply_list.currentRow()
        if index < 0 or index >= len(self.queue["items"]):
            return
        item = self.queue["items"][index]
        if item.get("sent_at"):
            self.notify("Sent replies are read-only.")
            return
        approved = self.reply_approved.isChecked()
        if approved and QMessageBox.question(self, "Approve draft",
                "The separately scheduled CLI may send this reply later. Approve this individual draft?"
                ) != QMessageBox.Yes:
            return
        try:
            update_queue(self.workspace, index, self.queue["version"],
                         self.reply_body.toPlainText(), approved)
            self.refresh_queue()
        except ReviewError as exc:
            self.notify(exc)
            self.refresh_queue()

    def _first_drafts(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel("Edit individual unsent Custom Email Draft cells in output\\professors.xlsx. "
                      "Sent rows are never offered. Saving does not send anything.")
        note.setWordWrap(True)
        layout.addWidget(note)
        navigation = QHBoxLayout()
        self.draft_page = QLabel("")
        navigation.addWidget(button("Previous", lambda: self.refresh_drafts(
            max(0, self.drafts["page"] - 1))))
        navigation.addWidget(self.draft_page)
        navigation.addWidget(button("Next", lambda: self.refresh_drafts(
            self.drafts["page"] + 1)))
        navigation.addWidget(button("Reload workbook", lambda: self.refresh_drafts(
            self.drafts["page"])))
        layout.addLayout(navigation)
        split = QSplitter()
        self.draft_list = QListWidget()
        self.draft_list.currentRowChanged.connect(self.show_draft)
        editor = QWidget()
        right = QVBoxLayout(editor)
        self.draft_details = QLabel("")
        self.draft_details.setWordWrap(True)
        self.draft_body = QPlainTextEdit()
        right.addWidget(self.draft_details)
        right.addWidget(self.draft_body)
        right.addWidget(button("Save selected unsent draft", self.save_draft))
        split.addWidget(self.draft_list)
        split.addWidget(editor)
        split.setStretchFactor(1, 3)
        layout.addWidget(split)
        return page

    def refresh_drafts(self, page: int = 0):
        try:
            drafts = read_drafts(self.workspace, page)
            if not drafts["items"] and page and drafts["total"]:
                drafts = read_drafts(self.workspace, max(0, (drafts["total"] - 1) // 50))
            self.drafts = drafts
            self.draft_page.setText(
                f"Page {drafts['page'] + 1} · {drafts['total']} unsent drafts")
            self.draft_list.clear()
            for item in drafts["items"]:
                self.draft_list.addItem(
                    f"{item['name']} · {item['email']}")
            self.draft_body.setReadOnly(not drafts["editable"])
            if self.draft_list.count():
                self.draft_list.setCurrentRow(0)
            elif not drafts["editable"]:
                self.draft_details.setText("Update the selected v2 CLI for coordinated draft editing.")
        except ReviewError as exc:
            self.draft_details.setText(str(exc))

    def show_draft(self, index: int):
        if not 0 <= index < len(self.drafts["items"]):
            return
        item = self.drafts["items"][index]
        self.draft_details.setText(
            f"{item['name']} <{item['email']}>\n{item['subject']}\n"
            "This is a workbook draft; review it before a separate live send.")
        self.draft_body.setPlainText(item["body"])

    def save_draft(self):
        index = self.draft_list.currentRow()
        if not 0 <= index < len(self.drafts["items"]):
            return
        item = self.drafts["items"][index]
        if QMessageBox.question(self, "Save first-email draft",
                "Save this unsent draft to the existing workbook? This does not send it."
                ) != QMessageBox.Yes:
            return
        try:
            update_draft(self.workspace, item["sheet"], item["row"],
                         self.drafts["version"], self.draft_body.toPlainText())
            self.refresh_drafts(self.drafts["page"])
        except ReviewError as exc:
            self.notify(exc)
            self.refresh_drafts(self.drafts["page"])

    def _setup(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(QLabel("Guided setup · existing .env is read but never modified. "
                               "GUI overrides are saved per workspace in AppData; passwords use Windows DPAPI."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.settings_layout = QVBoxLayout(container)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        return page

    def refresh_settings(self):
        while self.settings_layout.count():
            item = self.settings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._controls.clear()
        try:
            current = self.jobs.settings.public()
        except ReviewError as exc:
            self.settings_layout.addWidget(QLabel(str(exc)))
            return
        groups = {
            "Files & applicant": ("RESUME_PATH", "TARGET_XLSX", "ATTACHMENTS", "POSITION",
                                  "GEOGRAPHY", "AVAILABILITY", "CAN_SELF_FUND", "SELF_FUND_NOTE"),
            "Model": ("LLM_PROVIDER", "DRAFT_MODEL", "GROQ_API_KEY", "OPENAI_API_KEY",
                      "BUDGET_USD", "MAX_PROFESSORS"),
            "Main mailbox": tuple(k for k in FIELDS if k.startswith("SMTP_")) + ("REPLY_TO",),
            "IMAP & second mailbox": tuple(k for k in FIELDS if k.startswith(("IMAP_", "RESEND_"))),
            "Caps, windows & discovery": ("DAILY_SEND_CAP", "SEND_LOCAL_WINDOW",
                                           "SEND_DELAY_MIN", "SEND_DELAY_MAX",
                                           "DISCOVER_QUERIES", "DISCOVER_COUNTRIES", "OPENALEX_MAILTO"),
        }
        for title, keys in groups.items():
            box = QGroupBox(title)
            form = QFormLayout(box)
            for key in keys:
                kind = FIELDS[key]
                value = current["values"][key]
                control = QLineEdit()
                if key in SECRETS:
                    control.setEchoMode(QLineEdit.Password)
                    control.setPlaceholderText("Configured · leave blank to keep" if value["configured"]
                                               else "Not configured")
                else:
                    control.setText(str(value or ""))
                self._controls[key] = control
                row = QWidget()
                cells = QHBoxLayout(row)
                cells.setContentsMargins(0, 0, 0, 0)
                cells.addWidget(control)
                cells.addWidget(button("Save", lambda _, k=key: self.save_setting(k)))
                cells.addWidget(button("Reset", lambda _, k=key: self.save_setting(k, reset=True)))
                form.addRow(key.replace("_", " ").title(), row)
            self.settings_layout.addWidget(box)
        self.settings_layout.addStretch()

    def save_setting(self, key: str, reset: bool = False):
        value = None if reset else self._controls[key].text()
        if key in SECRETS and value == "":
            return
        try:
            self.jobs.settings.save({key: value})
            self.refresh_settings()
        except ReviewError as exc:
            self.notify(exc)

    def _tools(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        text = QLabel("The same v2 CLI runs in your selected workspace. No --yes, blanket approval, "
                      "no-focus, unverified sending or weekend override is exposed. "
                      "Live SMTP defaults OFF and requires typed approval AND the CLI prompt. "
                      "Legacy letters additionally require verified addresses, research focus, "
                      "recipient weekday hours and a shared daily cap.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.command_select = QComboBox()
        for name, info in COMMANDS.items():
            self.command_select.addItem(f"{name} · {info['description']}", name)
        self.command_select.currentIndexChanged.connect(self.render_options)
        layout.addWidget(self.command_select)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.option_container = QWidget()
        self.option_layout = QFormLayout(self.option_container)
        scroll.setWidget(self.option_container)
        layout.addWidget(scroll)
        layout.addWidget(button("Start selected CLI command", self.start_command))
        self.render_options()
        return page

    def render_options(self, *_):
        while self.option_layout.rowCount():
            self.option_layout.removeRow(0)
        self.option_inputs = {}
        command = self.command_select.currentData()
        for name, kind in COMMANDS[command]["fields"].items():
            if kind == "bool":
                widget = QCheckBox(name.replace("_", " ").title())
                self.option_layout.addRow(widget)
            elif kind.startswith("enum:"):
                widget = QComboBox()
                widget.addItem("Use CLI default", "")
                for choice in kind[5:].split("|"):
                    widget.addItem(choice, choice)
                self.option_layout.addRow(name.replace("_", " ").title(), widget)
            else:
                widget = QLineEdit()
                widget.setPlaceholderText("Optional · " + ("comma-separated paths" if kind == "list"
                                      else "workspace path (resume may be external)" if kind in ("file", "resume")
                                      else kind))
                if kind in ("file", "resume"):
                    row = QWidget()
                    cells = QHBoxLayout(row)
                    cells.setContentsMargins(0, 0, 0, 0)
                    cells.addWidget(widget)
                    cells.addWidget(button("Browse", lambda _, control=widget, field=kind:
                                           self.browse_file(control, field)))
                    self.option_layout.addRow(name.replace("_", " ").title(), row)
                else:
                    self.option_layout.addRow(name.replace("_", " ").title(), widget)
            self.option_inputs[name] = (kind, widget)

    def browse_file(self, field: QLineEdit, kind: str):
        initial = str(self.workspace.path or Path.cwd())
        path, _ = QFileDialog.getOpenFileName(self, "Select a file", initial)
        if path:
            field.setText(path)

    def start_command(self):
        command = self.command_select.currentData()
        options = {}
        for name, (kind, control) in self.option_inputs.items():
            if kind == "bool":
                if control.isChecked():
                    options[name] = True
            elif kind.startswith("enum:"):
                if control.currentData():
                    options[name] = control.currentData()
            elif control.text().strip():
                raw = control.text().strip()
                try:
                    options[name] = (int(raw) if kind == "int" else float(raw)
                                     if kind == "float" else [s.strip() for s in raw.split(",")]
                                     if kind == "list" else raw)
                except ValueError:
                    self.notify(f"{name} requires a valid {kind} value.")
                    return
        mail = options.get("live") or (command == "send" and
                                      (options.get("review") or options.get("review_to")))
        phrase = ("ARCHIVE" if command == "archive-sent" and options.get("live")
                  else f"SEND {command.upper()}" if mail else None)
        confirmation = None
        if phrase:
            confirmation, ok = QInputDialog.getText(self, "Confirm consequential action",
                f"This may {'copy mail to IMAP' if phrase == 'ARCHIVE' else 'send real SMTP mail'}.\n"
                f"Type {phrase} exactly; the CLI will also ask [Y/N]:")
            if not ok or confirmation != phrase:
                return
        try:
            result = self.jobs.start(command, options, confirmation)
            self.active_id = result["id"]
            self.tabs.setCurrentWidget(self.job_view)
            self.refresh_jobs()
        except ReviewError as exc:
            self.notify(exc)

    def _jobs(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Jobs stay in AppData; closing the window does not stop a running CLI child. "
                               "A restarted GUI never automatically reruns a job."))
        self.job_list = QListWidget()
        self.job_list.currentRowChanged.connect(self.select_job)
        layout.addWidget(self.job_list)
        actions = QHBoxLayout()
        actions.addWidget(button("Refresh", self.refresh_jobs))
        self.yes_button = button("Yes to visible CLI [Y/N]", lambda: self.answer("yes"))
        self.no_button = button("No to visible CLI [Y/N]", lambda: self.answer("no"))
        self.cancel_button = button("Cancel non-live job", self.cancel_job)
        for control in (self.yes_button, self.no_button, self.cancel_button):
            actions.addWidget(control)
        layout.addLayout(actions)
        self.job_log = QPlainTextEdit()
        self.job_log.setReadOnly(True)
        layout.addWidget(self.job_log)
        return page

    def refresh_jobs(self):
        try:
            items = self.jobs.list()
            selected = self.active_id
            self.job_list.blockSignals(True)
            self.job_list.clear()
            for item in items:
                self.job_list.addItem(f"{item['command']} · {item['status']} · {item['started']}")
            self.job_list.blockSignals(False)
            ids = [item["id"] for item in items]
            self._visible_jobs = ids
            if selected in ids:
                self.job_list.setCurrentRow(ids.index(selected))
            elif ids:
                self.job_list.setCurrentRow(0)
            self.poll_jobs()
        except ReviewError as exc:
            self.job_log.setPlainText(str(exc))

    def select_job(self, index: int):
        if index >= 0 and index < len(getattr(self, "_visible_jobs", [])):
            self.active_id = self._visible_jobs[index]
            self.poll_jobs()

    def poll_jobs(self):
        if not self.workspace.path or not self.active_id:
            return
        try:
            job = self.jobs.get(self.active_id)
            text = self.jobs.log(self.active_id)
            if self.job_log.toPlainText() != text:
                self.job_log.setPlainText(text)
                self.job_log.verticalScrollBar().setValue(
                    self.job_log.verticalScrollBar().maximum())
            running = job["status"] == "running"
            prompt = running and text.rstrip().endswith("[Y/N]:")
            self.yes_button.setEnabled(prompt)
            self.no_button.setEnabled(prompt)
            self.cancel_button.setEnabled(running and not job.get("live"))
            if prompt and self._asked_prompt != (self.active_id, text):
                self._asked_prompt = (self.active_id, text)
                answer = QMessageBox.question(
                    self, "CLI confirmation",
                    f"Review the job log before continuing.\n\n"
                    f"{text[-600:]}\n\nAnswer YES to the CLI prompt?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                self.answer("yes" if answer == QMessageBox.Yes else "no")
            if not running and self.tabs.currentWidget() == self.job_view:
                self.job_list.item(self.job_list.currentRow()).setText(
                    f"{job['command']} · {job['status']} · {job['started']}")
        except (ReviewError, AttributeError) as exc:
            self.job_log.setPlainText(str(exc))

    def answer(self, choice: str):
        try:
            self.jobs.input(self.active_id, choice)
        except ReviewError as exc:
            self.notify(exc)

    def cancel_job(self):
        try:
            if QMessageBox.question(self, "Cancel job",
                    "Stop this non-live job? Inspect output if a workbook save was interrupted."
                    ) == QMessageBox.Yes:
                self.jobs.cancel(self.active_id)
                self.refresh_jobs()
        except ReviewError as exc:
            self.notify(exc)


def launch(workspace: Workspace) -> int:
    app = QApplication.instance() or QApplication([])
    window = DesktopWindow(workspace)
    window.show()
    return app.exec()
