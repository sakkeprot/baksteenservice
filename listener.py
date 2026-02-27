import logging
import threading
import time
import unicodedata
from typing import Dict, List


import config
from config import ALLOWED_SENDERS, SENDER_PATTERN


logger = logging.getLogger("baksteenservice.listener")



def is_allowed(sender: str) -> bool:
    if not SENDER_PATTERN.match(sender):
        return False
    if ALLOWED_SENDERS and sender not in ALLOWED_SENDERS:
        return False
    return True



def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )



def decode_text(text: str) -> str:
    t = text.strip()
    if (
        len(t) >= 4
        and len(t) % 4 == 0
        and all(c in "0123456789ABCDEFabcdef" for c in t)
    ):
        try:
            t = bytes.fromhex(t).decode("utf-16-be")
        except Exception:
            pass
    return strip_accents(t)



class SMSListener:


    def __init__(self):
        self.pending: List[Dict] = []
        self.lock = threading.Lock()
        self.active = False
        self.thread = None
        self.ser = None


    def start(self):
        if config.DEV_MODE:
            logger.info("Listener ready (terminal mode).")
            return
        import serial
        self.ser = serial.Serial(port=config.MODEM_PORT, baudrate=config.MODEM_BAUD, timeout=1)
        time.sleep(1)
        self.ser.write(b"\x1b")
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.at("AT\r\n")
        self.at("AT+CMGF=1\r\n")
        self.at("AT+CNMI=0,0,0,0,0\r\n")
        self.at('AT+CMGDA="DEL ALL"\r\n', wait=2)
        self.active = True
        self.thread = threading.Thread(target=self.poll_loop, daemon=True)
        self.thread.start()
        logger.info(f"Listener started on {config.MODEM_PORT}.")


    def stop(self):
        self.active = False
        if self.thread:
            self.thread.join(timeout=5)
        if self.ser and self.ser.isOpen():
            self.ser.close()


    def get_next_message(self):
        return self.read_from_terminal() if config.DEV_MODE else self.wait_for_modem_message()


    def read_from_terminal(self):
        try:
            while True:
                sender = input("Sender (e.g. +32498765432): ").strip() or "+32400000000"
                text   = input("Message: ").strip()
                print()
                if is_allowed(sender):
                    return {"sender": sender, "text": strip_accents(text), "timestamp": time.time()}
                logger.warning(f"Blocked sender: {sender}")
                print(f"{sender} is geen geldig +32 nummer. Probeer opnieuw.")
        except (EOFError, KeyboardInterrupt):
            return None


    def wait_for_modem_message(self):
        while self.active:
            with self.lock:
                if self.pending:
                    return self.pending.pop(0)
            time.sleep(0.1)
        return None


    def poll_loop(self):
        while self.active:
            time.sleep(1)
            if self.lock.locked():
                continue
            try:
                messages = self._read_all_messages()
                for msg in messages:
                    with self.lock:
                        self.pending.append(msg)
                    logger.info(f"SMS received from {msg['sender']}: {msg['text']}")
            except Exception as e:
                logger.error(f"Poll error: {e}")


    def _read_all_messages(self) -> List[Dict]:
        self.ser.reset_input_buffer()
        self.ser.write(b'AT+CMGL="ALL"\r\n')
        time.sleep(1)
        raw = self.ser.read(self.ser.in_waiting).decode("utf-8", errors="ignore")

        messages = []
        indices  = []
        lines    = [l.strip() for l in raw.splitlines() if l.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("+CMGL:"):
                try:
                    parts  = line.split(",")
                    index  = int(parts[0].replace("+CMGL:", "").strip())
                    sender = parts[2].strip().strip('"') if len(parts) >= 3 else None
                    body   = decode_text(lines[i + 1]) if i + 1 < len(lines) else ""
                    if sender and body and body != "OK":
                        indices.append(index)
                        if is_allowed(sender):
                            messages.append({
                                "sender":    sender,
                                "text":      body,
                                "timestamp": time.time()
                            })
                        else:
                            logger.warning(f"Blocked sender: {sender}")
                except Exception as e:
                    logger.warning(f"Could not parse CMGL line: {line} — {e}")
            i += 1

        for index in indices:
            self.ser.write(f'AT+CMGD={index}\r\n'.encode())
            time.sleep(0.2)

        return messages


    def at(self, cmd, wait=0.3):
        self.ser.write(cmd.encode())
        time.sleep(wait)
        return self.ser.read(self.ser.in_waiting).decode("utf-8", errors="ignore")