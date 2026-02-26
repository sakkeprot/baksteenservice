import logging
import time
import unicodedata

import config

logger = logging.getLogger("baksteenservice.returner")


class SMSReturner:

    def __init__(self, listener=None):
        self.listener = listener

    def sanitize(self, text: str) -> str:
        symbol_replacements = {
            "°": "", "€": "EUR", "→": "->", "➡": "->",
            "–": "-", "—": "-", "…": "...",
            "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
            "\u00b0": "", "×": "x", "÷": "/",
            "½": "1/2", "¼": "1/4", "¾": "3/4",
            "²": "2", "³": "3", "µ": "u",
            "©": "(c)", "®": "(r)", "™": "(tm)",
            "•": "-", "·": ".",
        }
        for char, replacement in symbol_replacements.items():
            text = text.replace(char, replacement)
        normalized = unicodedata.normalize("NFD", text)
        text = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
        return text.encode("ascii", errors="ignore").decode("ascii")

    def build_reply(self, analysis, action_result):
        return action_result.get("message")

    def send(self, recipient, text):
        if config.DEV_MODE:
            print(f"[Reply to {recipient}]")
            for line in text.splitlines():
                print(f"  {line}")
            print(f"  ({len(text)} chars)")
        else:
            self.sendsms(recipient, text)

    def sendsms(self, recipient, text):
        text = self.sanitize(text)
        ser = self.listener.ser
        lock = self.listener.lock
        try:
            with lock:  # poll_loop skips while this is held
                ser.reset_input_buffer()
                ser.write(f'AT+CMGS="{recipient}"\r'.encode())

                # Wait for '>' prompt before sending body
                deadline = time.time() + 5
                buf = ""
                while time.time() < deadline:
                    buf += ser.read(ser.in_waiting or 1).decode("utf-8", errors="ignore")
                    if ">" in buf:
                        break
                    time.sleep(0.05)

                if ">" not in buf:
                    logger.warning(f"No '>' prompt received, aborting send to {recipient}.")
                    ser.write(b"\x1b")  # ESC to cancel
                    return

                ser.write(f'{text}\x1a'.encode())

                # Wait for +CMGS confirmation
                deadline = time.time() + 10
                resp = ""
                while time.time() < deadline:
                    resp += ser.read(ser.in_waiting or 1).decode("utf-8", errors="ignore")
                    if "+CMGS" in resp or "ERROR" in resp:
                        break
                    time.sleep(0.2)

                if "+CMGS" in resp:
                    logger.info(f"SMS sent to {recipient}")
                else:
                    logger.warning(f"Modem response: {resp.strip()}")
        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
