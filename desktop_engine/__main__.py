"""`python -m desktop_engine` / agnostos-engine.exe: stdio server, job worker or probe."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--worker"]:
        from desktop_engine.worker import run_worker
        return run_worker(args[1:])
    if args[:1] == ["--probe"]:
        from desktop_engine.worker import run_probe
        return run_probe(args[1:])
    if args == ["--version"]:
        from desktop_engine import __version__
        print(__version__)
        return 0
    if args in ([], ["--serve"]):
        from desktop_engine.server import serve
        return serve()
    print("usage: agnostos-engine [--serve | --version]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
