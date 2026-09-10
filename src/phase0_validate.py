"""Acceptance check for the archived CanadaBuys OCDS pilot."""

import json
import sys
import zipfile
from pathlib import Path

from .validate import validate_releases


def pilot_releases(archive: Path):
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if name.startswith("records/eng/") and name.endswith(".json"):
                package = json.loads(source.read(name))
                for record in package.get("records", []):
                    yield record["compiledRelease"]


if __name__ == "__main__":
    print(f"validated {validate_releases(pilot_releases(Path(sys.argv[1])))} pilot releases")