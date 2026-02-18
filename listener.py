"""baksteenservice - listener.py"""
import logging, threading, time
from typing import Dict, List
import config

logger = logging.getLogger("baksteenservice.listener")

class SMSListener:
    def __init__(self):
        self._pending: List[Dict] = []; self._lock = threading.Lock()
        self._active = False; self._thread = None; self._ser = None

    def start(self):
        if config.DEV_MODE: logger.info("Listener ready — terminal mode."); return
        import serial
        self._ser = serial.Serial(port=config.MODEM_PORT, baudrate=config.MODEM_BAUD, timeout=1)
        time.sleep(0.5); self._at("AT"); self._at("AT+CMGF=1"); self._at("AT+CNMI=1,2,0,0,0")
        self._active = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True); self._thread.start()
        logger.info(f"Listener started on {config.MODEM_PORT}.")

    def stop(self):
        self._active = False
        if self._thread: self._thread.join(timeout=5)
        if self._ser and self._ser.is_open: self._ser.close()

    def get_next_message(self):
        return self._read_from_terminal() if config.DEV_MODE else self._wait_for_modem_message()

    def _read_from_terminal(self):
        try:
            print()
            sender = input("  Sender (+32...): ").strip() or "+32400000000"
            text   = input("  Message       : ").strip()
            print(); return {"sender": sender, "text": text, "timestamp": "now"}
        except (EOFError, KeyboardInterrupt): return None

    def _wait_for_modem_message(self):
        while self._active:
            with self._lock:
                if self._pending: return self._pending.pop(0)
            time.sleep(0.2)
        return None

    def _poll_loop(self):
        pending_sender = None
        while self._active:
            try:
                line = self._ser.readline().decode("utf-8", errors="ignore").strip()
                if not line: continue
                if line.startswith("+CMT:"):
                    pending_sender = line.split(",")[0].replace("+CMT:", "").strip().strip('"\' ')
                elif pending_sender:
                    with self._lock: self._pending.append({"sender": pending_sender, "text": line, "timestamp": ""})
                    logger.info(f"SMS received from {pending_sender}"); pending_sender = None
            except Exception as e: logger.error(f"Serial read error: {e}"); time.sleep(1)

    def _at(self, cmd, wait=0.3):
        self._ser.write((cmd + "\r").encode()); time.sleep(wait)
        return self._ser.read(self._ser.in_waiting).decode("utf-8", errors="ignore")
