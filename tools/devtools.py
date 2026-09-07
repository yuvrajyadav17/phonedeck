"""Evaluate JavaScript inside the phone's WebView, from the PC.

The shell app enables WebView remote debugging, which exposes a Chrome
DevTools endpoint over an abstract unix socket on the device. This forwards
that socket and speaks just enough of the DevTools protocol to run an
expression and print the result.

    python tools/devtools.py "document.title"
    python tools/devtools.py --file probe.js

Without it, debugging the dashboard on the device is pure guesswork.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request

import websocket  # type: ignore[import-untyped]

LOCAL_PORT = 9222
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def adb(*args: str) -> str:
    return subprocess.run(["adb", *args], capture_output=True, text=True,
                          creationflags=NO_WINDOW).stdout


def forward_devtools() -> None:
    """Point tcp:9222 at whichever WebView is currently running."""
    unix = adb("shell", "cat", "/proc/net/unix")
    match = re.search(r"@(webview_devtools_remote_\d+)", unix)
    if not match:
        sys.exit("no debuggable WebView found -- is the PhoneDeck app running?")
    adb("forward", f"tcp:{LOCAL_PORT}", f"localabstract:{match.group(1)}")


def page_socket() -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{LOCAL_PORT}/json", timeout=10) as fh:
        pages = json.load(fh)
    for page in pages:
        if page.get("type") == "page":
            return page["webSocketDebuggerUrl"]
    sys.exit("no page target exposed by the WebView")


def evaluate(expression: str) -> object:
    ws = websocket.create_connection(page_socket(), timeout=15,
                                     suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                # Lets the expression use `await` at the top level.
                "replMode": True,
            },
        }))
        # Skip any unsolicited events until our reply arrives.
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                break
    finally:
        ws.close()

    result = message.get("result", {})
    if "exceptionDetails" in result:
        detail = result["exceptionDetails"]
        text = detail.get("exception", {}).get("description") or detail.get("text")
        raise RuntimeError(text)
    return result.get("result", {}).get("value")


def main() -> None:
    # The dashboard's labels are emoji; a Windows console defaults to cp1252
    # and would raise UnicodeEncodeError on the way out.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expression", nargs="?", help="JavaScript to evaluate")
    parser.add_argument("--file", help="read the expression from a file")
    args = parser.parse_args()

    if args.file:
        expression = open(args.file, encoding="utf-8").read()
    elif args.expression:
        expression = args.expression
    else:
        parser.error("give an expression or --file")

    forward_devtools()
    try:
        value = evaluate(expression)
    except RuntimeError as exc:
        print("JS EXCEPTION:", exc)
        raise SystemExit(1)
    print(json.dumps(value, indent=2, ensure_ascii=False)
          if isinstance(value, (dict, list)) else value)


if __name__ == "__main__":
    main()
