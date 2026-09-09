"""PhoneDeck Notes -- the window that opens when you tap the notes card.

Deliberately tiny: a textarea that saves as you type. Tap the card on the
phone, type here with a real keyboard, close the window. There is no save
button because there is nothing to press.

Shares editor_app.py's machinery for finding the server and its token.
"""
from __future__ import annotations

import sys

import webview

from editor_app import ICON_FILE, fail, read_token, server_is_up, start_server

NOTES_URL = "http://127.0.0.1:8770/notes?t={token}"


def main() -> None:
    if not server_is_up() and not start_server():
        fail("<h3>PhoneDeck is not running</h3>"
             "<p>The notes window could not reach the server on port 8770.</p>")

    token = read_token()
    if token is None:
        fail("<h3>No access token yet</h3>"
             "<p>Start PhoneDeck once so it can create "
             "<code>.state/token.txt</code>.</p>")

    # Small on purpose: this is a scratchpad, not a document editor, and it
    # should not bury whatever you were doing.
    webview.create_window(
        "PhoneDeck Notes",
        NOTES_URL.format(token=token),
        width=560,
        height=620,
        min_size=(380, 320),
        background_color="#0d1219",
        on_top=True,
    )
    webview.start(icon=str(ICON_FILE) if ICON_FILE.exists() else None)


if __name__ == "__main__":
    main()
