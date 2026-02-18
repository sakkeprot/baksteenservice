"""baksteenservice - returner.py — DEV_MODE=True: terminal | False: SIM800C"""
import logging, time
from typing import Dict
import config

logger = logging.getLogger("baksteenservice.returner")

class SMSReturner:
    def __init__(self):
        self._ser = None
        if not config.DEV_MODE:
            import serial
            self._ser = serial.Serial(port=config.MODEM_PORT, baudrate=config.MODEM_BAUD, timeout=2)
            time.sleep(0.5); self._at("AT+CMGF=1")

    def build_reply(self, analysis, action_result):
        return action_result.get("message", "")

    def send(self, recipient, text):
        if config.DEV_MODE:
            print(f"  ┌─ Reply to {recipient}")
            for line in text.splitlines():
                print(f"  │  {line}")
            print(f"  └─ ({len(text)} chars)")
            print()
        else:
            self._send_sms(recipient, text)

    def _send_sms(self, recipient, text):
        try:
            self._ser.write(f'AT+CMGS="{recipient}"\r'.encode()); time.sleep(0.5)
            self._ser.write(f'{text}\x1A'.encode()); time.sleep(3)
            resp = self._ser.read(self._ser.in_waiting).decode("utf-8", errors="ignore")
            if "+CMGS" in resp: logger.info(f"SMS sent to {recipient}")
            else: logger.warning(f"Modem response: {resp.strip()}")
        except Exception as e: logger.error(f"Failed to send SMS: {e}")

    def _at(self, cmd, wait=0.3):
        self._ser.write((cmd + "\r").encode()); time.sleep(wait)
        return self._ser.read(self._ser.in_waiting).decode("utf-8", errors="ignore")
