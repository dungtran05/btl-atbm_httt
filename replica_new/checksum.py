from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def calculate_chain_checksum(chain: list[dict[str, Any]]) -> str:
    raw = json.dumps(chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_checksum(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def write_checksum(path: Path, checksum: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(checksum.strip() + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
