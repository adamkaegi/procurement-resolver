"""Fetch and archive source payloads without modifying them."""

import hashlib
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def fetch(url: str, source_id: str, root: Path, filename: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = root / "data/raw" / source_id / stamp / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest}  {filename}\n")
    return destination