"""PhoneDeck entry point.

    python run.py

Starts the dashboard server and the ADB watchdog together.
"""
from server.app import main

if __name__ == "__main__":
    main()
