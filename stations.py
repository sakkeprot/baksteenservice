"""baksteenservice - stations.py — loads stations.txt preserving FILE ORDER."""
import os
from typing import Dict, List, Tuple
from normalise import normalise

STATIONS_FILE = os.path.join(os.path.dirname(__file__), "stations.txt")

def load_stations() -> Tuple[Dict[str, str], List[str]]:
    stations_dict: Dict[str, str] = {}
    ordered_keys:  List[str]      = []
    if not os.path.exists(STATIONS_FILE): return stations_dict, ordered_keys
    with open(STATIONS_FILE, encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name or name.startswith("#"): continue
            key = normalise(name)
            if key not in stations_dict:
                stations_dict[key] = name; ordered_keys.append(key)
    return stations_dict, ordered_keys
