"""Windows WebView2 launcher; only the selected v2 files are opened."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.request import urlopen

from desktop_review.app import start
from desktop_review.storage import Workspace


def config_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA is required for the Windows desktop app")
    return Path(base) / "Agnostos-v2-Review"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--health-check"]):
        raise ValueError("Only --health-check is supported")
    server, thread, token, address = start(Workspace(config_dir()))
    try:
        if args:
            with urlopen(address + "/health", timeout=5) as response:
                if response.status != 200 or response.read() != b'{"ok": true}':
                    raise RuntimeError("Desktop health check failed")
            return 0
        import webview

        class FolderPicker:
            def __init__(self):
                self.window = None

            def choose_workspace(self):
                dialog_type = (webview.FileDialog.FOLDER if hasattr(webview, "FileDialog")
                               else webview.FOLDER_DIALOG)
                result = self.window.create_file_dialog(dialog_type)
                return result[0] if result else None

        picker = FolderPicker()
        picker.window = webview.create_window(
            "Agnostos v2 · View & Review", address + "/#" + token,
            js_api=picker, width=1200, height=800, min_size=(800, 600))
        webview.start(gui="edgechromium")
        return 0
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Agnostos review could not start", 0x10)
        raise
