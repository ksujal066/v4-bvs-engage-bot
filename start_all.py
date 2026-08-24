"""
Run bot + dashboard together in one process (for single-service hosts).
Usage: python start_all.py
"""
import os
import threading
import subprocess
import sys


def run_bot():
    subprocess.call([sys.executable, "bot.py"])


def run_dashboard():
    # Dashboard binds to PORT if provided by the host (Railway/Render)
    port = os.getenv("PORT", "8080")
    os.environ["PORT"] = str(port)
    subprocess.call([sys.executable, "dashboard.py"])


if __name__ == "__main__":
    mode = os.getenv("RUN_MODE", "both").lower()

    if mode == "bot":
        run_bot()
    elif mode == "dashboard":
        run_dashboard()
    else:
        print("Starting bot + dashboard...")
        t = threading.Thread(target=run_bot, daemon=True)
        t.start()
        run_dashboard()  # main thread = web (so host healthchecks work)
