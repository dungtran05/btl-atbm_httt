from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict
from typing import Any, Iterable, Tuple

from .blockchain import Block

logger = logging.getLogger(__name__)


class ChainVerifyError(RuntimeError):
    pass


REQUIRED_FIELDS: tuple[str, ...] = (
    "index",
    "timestamp",
    "document_hash",
    "document_name",
    "owner",
    "signature",
    "previous_hash",
    "nonce",
    "hash",
)


def _is_valid_timestamp(ts: Any, *, now: float | None = None) -> bool:
    if not isinstance(ts, (int, float)):
        return False
    if not math.isfinite(float(ts)):
        return False
    if float(ts) < 0:
        return False
    # Allow small future drift (clock skew)
    now = time.time() if now is None else now
    return float(ts) <= now + 60.0


def _ensure_required_fields(block_dict: dict[str, Any]) -> tuple[bool, str]:
    for k in REQUIRED_FIELDS:
        if k not in block_dict:
            return False, f"Missing field '{k}'"
    return True, ""


def block_from_dict(data: dict[str, Any]) -> Block:
    # Keep compatibility with optional fields in Block dataclass
    return Block(
        index=int(data["index"]),
        timestamp=float(data["timestamp"]),
        document_hash=str(data["document_hash"]),
        document_name=str(data["document_name"]),
        owner=str(data["owner"]),
        signature=str(data["signature"]),
        previous_hash=str(data["previous_hash"]),
        certificate_id=str(data.get("certificate_id") or ""),
        metadata=data.get("metadata"),
        file_path=str(data.get("file_path") or ""),
        qr_path=str(data.get("qr_path") or ""),
        nonce=int(data.get("nonce") or 0),
        hash=str(data.get("hash") or ""),
        issuer_name=str(data.get("issuer_name") or ""),
    )


def verify_chain(chain: Iterable[dict[str, Any]]) -> tuple[bool, int | None, str]:
    """
    Verify whole chain integrity.

    Returns:
      (ok, bad_index, reason)
    """

    now = time.time()
    prev_hash: str | None = None
    expected_index = 0
    seen_hashes: set[str] = set()

    chain_list = list(chain)
    if not chain_list:
        return False, None, "Empty chain"

    for pos, block_dict in enumerate(chain_list):
        if not isinstance(block_dict, dict):
            return False, pos, "Block is not an object"
        ok, reason = _ensure_required_fields(block_dict)
        if not ok:
            return False, pos, reason

        try:
            index = int(block_dict["index"])
        except Exception:
            return False, pos, "Invalid 'index' type"
        if index != expected_index:
            return False, pos, f"Non-contiguous index (expected {expected_index}, got {index})"

        ts = block_dict.get("timestamp")
        if not _is_valid_timestamp(ts, now=now):
            return False, pos, "Invalid timestamp"

        current_hash = str(block_dict.get("hash") or "")
        if not current_hash or len(current_hash) != 64:
            return False, pos, "Missing/invalid block hash"
        if current_hash in seen_hashes:
            return False, pos, "Duplicate block hash detected"
        seen_hashes.add(current_hash)

        try:
            blk = block_from_dict(block_dict)
        except Exception as exc:
            return False, pos, f"Cannot parse block: {exc}"

        calculated = blk.calculate_hash()
        if current_hash != calculated:
            return False, pos, "Block content tampering detected (hash mismatch)"

        if pos == 0:
            if str(block_dict.get("previous_hash")) != "0":
                return False, pos, "Genesis previous_hash must be '0'"
        else:
            if prev_hash is None:
                return False, pos, "Internal verify error (prev_hash missing)"
            if str(block_dict.get("previous_hash")) != prev_hash:
                return False, pos, "Broken link: previous_hash mismatch"

        prev_hash = current_hash
        expected_index += 1

    return True, None, "Chain is valid"


def normalize_chain(chain: Iterable[Block]) -> list[dict[str, Any]]:
    return [asdict(b) for b in chain]

