# PyInstaller spec for the headless sidecar engine (built by build-engine.ps1).
# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

hidden = (collect_submodules("outreach") + collect_submodules("desktop_engine")
          + ["desktop_review.commands", "desktop_review.jobs", "desktop_review.settings",
             "desktop_review.storage", "googleapiclient.discovery", "google_auth_oauthlib.flow",
             "ddgs", "docx", "pdfplumber", "openai", "httpx", "truststore", "certifi",
             "dotenv", "ruamel.yaml", "openpyxl", "tzdata"])

datas = (collect_data_files("tzdata") + collect_data_files("certifi")
         + [(os.path.join(ROOT, "sources.yaml"), "."),
            (os.path.join(ROOT, "LICENSE"), "licenses")])

excludes = ["PySide6", "shiboken6", "numpy", "pandas", "PIL", "pypdfium2", "aiohttp",
            "websockets", "mcp", "fastapi", "starlette", "uvicorn", "watchfiles", "httptools",
            "bcrypt", "setuptools", "pkg_resources", "IPython", "playwright", "tkinter",
            "matplotlib", "scipy", "desktop_review.native", "desktop_review.app",
            "desktop_review.launcher", "pytest", "jedi"]

a = Analysis(
    [os.path.join(ROOT, "desktop_engine", "__main__.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# googleapiclient's hook ships ~580 discovery documents; the CLI only uses Calendar v3.
def _keep(entry):
    dest = entry[0].replace("\\", "/")
    if "googleapiclient/discovery_cache/documents/" in dest:
        return dest.endswith("/calendar.v3.json")
    return True

a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="agnostos-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    icon=os.path.join(ROOT, "docs", "assets", "agnostos.ico"),
)
