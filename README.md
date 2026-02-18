# baksteenservice

## Commands

| SMS | Example | Reply |
|-----|---------|-------|
| `gpt <anything>` | `gpt wat is de hoofdstad van Japan` | Max 160 chars |
| `janee <question>` | `janee is kip lekkerder dan rund` | `Ja` or `Nee` |
| `trein <dep> <arr> [time]` | `trein leuven brussel 17` | Train info |

## API key setup
Edit `secrets.py`:
```python
DEEPSEEK_API_KEY = "sk-your-real-key-here"
```
`secrets.py` is in `.gitignore` — never commit it.

## Dev mode
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Switch to SIM800C
```python
# config.py
DEV_MODE = False
MODEM_PORT = "/dev/ttyUSB0"
```
```bash
sudo usermod -aG dialout sander
```
