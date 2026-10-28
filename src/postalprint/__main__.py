"""Starts the program: runs the local server and opens the window.

    python -m postalprint [--debug] [--no-browser] [--port 5050] [--data-dir DIR]

start.bat and the .exe both end up here.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import threading
import webbrowser
from pathlib import Path

from postalprint.paths import DATA_DIR
from postalprint.web.app import create_app

HOST = "127.0.0.1"
PORT = 5050


def port_in_use(port: int) -> bool:
    """Tells whether something (typically this program) already listens on ``port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, port)) == 0


def find_edge() -> str | None:
    """Returns the path to Microsoft Edge, which ships with Windows 11."""
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            candidate = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def open_browser(url: str) -> None:
    """Opens the program in its own window (Edge app mode), falling back to the default browser."""
    edge = find_edge()
    if edge:
        try:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1200,860"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def main() -> None:
    parser = argparse.ArgumentParser(prog="postalprint", description="PostalPrint")
    parser.add_argument("--debug", action="store_true", help="development mode with auto-reload")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="data folder (e.g. for testing)")
    args = parser.parse_args()
    url = f"http://{HOST}:{args.port}"
    # With --debug, Werkzeug re-runs the program in a child process that already owns the port
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    if not is_reloader_child and port_in_use(args.port):
        print("Programmet kører allerede – åbner vinduet.")
        open_browser(url)
        return

    if not args.debug:
        # Request logs may contain search terms from the history (names), so they are hidden
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app = create_app(args.data_dir)
    if not args.no_browser and not is_reloader_child:
        threading.Timer(1.0, open_browser, [url]).start()
    print(f"PostalPrint kører på {url}")
    print("Luk dette vindue for at stoppe programmet.")
    app.run(host=HOST, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
