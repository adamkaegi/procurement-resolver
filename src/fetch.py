"""Fetch and archive source payloads without modifying them."""

import hashlib
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def fetch(url: str, source_id: str, root: Path, filename: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = root / "data/raw" / source_id / stamp / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url) as response:
            destination.write_bytes(response.read())
    except urllib.error.HTTPError:
        # Observed on canadabuys.canada.ca and ArcGIS-hosted downloads: the
        # CDN 403s urllib's request (and any custom User-Agent, tried first)
        # but serves curl's plain default UA -- a bot-mitigation heuristic,
        # not an access control the public licence doesn't already grant.
        # Falling back to curl, unmodified, is still a plain anonymous GET.
        subprocess.run(["curl", "-sL", "--max-time", "60", "-o", str(destination), url], check=True)
    content = destination.read_bytes()
    if content[:15].lstrip().lower().startswith(b"<html") or content[:15].lstrip().lower().startswith(b"<!doctype"):
        destination.unlink()
        raise RuntimeError(f"{url} returned an HTML page (likely a CDN block or error page), not the expected payload")
    digest = hashlib.sha256(content).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest}  {filename}\n")
    return destination