"""baksteenservice - normalise.py — accent-stripping normalisation."""
import unicodedata, re

def normalise(s: str) -> str:
    no_accents = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", no_accents.lower().strip())
