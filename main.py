#!/usr/bin/env python3
"""baksteenservice - main.py"""
import glob
import logging
import os
import signal
import sys
import threading

from listener import SMSListener
from analyser import SMSAnalyser
from action import ActionHandler
from returner import SMSReturner
import config


def get_next_log_path(log_dir: str) -> str:
    os.makedirs(log_dir, exist_ok=True)
    existing = glob.glob(os.path.join(log_dir, "log*.log"))
    numbers = []
    for f in existing:
        try:
            numbers.append(int(os.path.basename(f).replace("log", "").replace(".log", "")))
        except ValueError:
            pass
    next_num = max(numbers, default=0) + 1
    return os.path.join(log_dir, f"log{next_num}.log")


LOG_DIR = "/home/sander/baksteenservice/logs"
log_path = get_next_log_path(LOG_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("baksteenservice.main")
logger.info(f"Logging to {log_path}")

_running = True
_listener = None  # global ref so signal handler can stop it immediately


def handle_signal(sig, frame):
    global _running
    logger.info("Shutdown signal received.")
    _running = False
    if _listener:
        _listener.active = False  # ← unblocks wait_for_modem_message immediately


def handle_message(msg, analyser, action_handler, returner):
    try:
        logger.info(f"Message from {msg['sender']}: {msg['text']}")
        analysis = analyser.analyse(msg)
        action_result = action_handler.execute(analysis)
        reply = returner.build_reply(analysis, action_result)
        returner.send(msg["sender"], reply)
    except Exception as e:
        logger.error(f"Error handling message from {msg['sender']}: {e}")


def main():
    global _listener

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    mode = "TERMINAL (dev)" if config.DEV_MODE else f"SIM800C on {config.MODEM_PORT}"
    logger.info(f"baksteenservice starting — mode: {mode}")

    _listener = SMSListener()
    analyser = SMSAnalyser()
    action_handler = ActionHandler()
    returner = SMSReturner(listener=_listener)
    _listener.start()

    try:
        while _running:
            msg = _listener.get_next_message()
            if msg is None:
                break
            t = threading.Thread(target=handle_message, args=(msg, analyser, action_handler, returner), daemon=True)
            t.start()
    except KeyboardInterrupt:
        pass
    finally:
        _listener.stop()
        logger.info("baksteenservice stopped.")


if __name__ == "__main__":
    main()
    