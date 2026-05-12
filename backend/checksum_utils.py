from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChecksumError(RuntimeError):
    pass


def calculate_chain_checksum(chain: list[dict[str, Any]]) -> str:
    """
    Deterministic checksum over the entire chain.

    We hash the JSON dump of the list of blocks with sort_keys=True.
    This detects tampering even if attacker edits multiple fields in a consistent-looking way.
    """

    raw = json.dumps(chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_checksum_file(path: Path, checksum: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(checksum.strip() + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            logger.exception("Failed cleaning checksum tmp file %s", tmp)
        raise ChecksumError(f"Failed to write checksum file: {path}") from exc


def read_checksum_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except Exception as exc:
        raise ChecksumError(f"Failed to read checksum file: {path}") from exc

