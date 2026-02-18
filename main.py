#!/usr/bin/env python3
"""baksteenservice - main.py"""
import logging, signal, sys
from listener import SMSListener
from analyser import SMSAnalyser
from action import ActionHandler
from returner import SMSReturner
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("baksteenservice.main")
_running = True

def handle_signal(sig, frame):
    global _running; logger.info("Shutdown signal received."); _running = False

def main():
    signal.signal(signal.SIGTERM, handle_signal); signal.signal(signal.SIGINT, handle_signal)
    mode = "TERMINAL (dev)" if config.DEV_MODE else f"SIM800C on {config.MODEM_PORT}"
    logger.info(f"baksteenservice starting — mode: {mode}")
    listener = SMSListener(); analyser = SMSAnalyser()
    action_handler = ActionHandler(); returner = SMSReturner()
    listener.start()
    try:
        while _running:
            msg = listener.get_next_message()
            if msg is None: break
            logger.info(f"Message from {msg['sender']}: {msg['text']}")
            analysis = analyser.analyse(msg)
            action_result = action_handler.execute(analysis)
            reply = returner.build_reply(analysis, action_result)
            returner.send(msg["sender"], reply)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop(); logger.info("baksteenservice stopped.")

if __name__ == "__main__":
    main()
