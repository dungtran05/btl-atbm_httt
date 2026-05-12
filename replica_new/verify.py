from __future__ import annotations

import math
import time
from typing import Any, Iterable

from models import Block

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


def _is_valid_timestamp(ts: Any, *, now: float) -> bool:
    if not isinstance(ts, (int, float)):
        return False
    if not math.isfinite(float(ts)):
        return False
    if float(ts) < 0:
        return False
    return float(ts) <= now + 60.0


def block_from_dict(data: dict[str, Any]) -> Block:
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
    chain_list = list(chain)
    if not chain_list:
        return False, None, "Empty chain"

    now = time.time()
    expected_index = 0
    prev_hash: str | None = None
    seen_hashes: set[str] = set()

    for pos, b in enumerate(chain_list):
        if not isinstance(b, dict):
            return False, pos, "Block is not an object"
        for field in REQUIRED_FIELDS:
            if field not in b:
                return False, pos, f"Missing field '{field}'"

        try:
            index = int(b["index"])
        except Exception:
            return False, pos, "Invalid index"
        if index != expected_index:
            return False, pos, f"Non-contiguous index (expected {expected_index}, got {index})"

        if not _is_valid_timestamp(b.get("timestamp"), now=now):
            return False, pos, "Invalid timestamp"

        h = str(b.get("hash") or "")
        if not h or len(h) != 64:
            return False, pos, "Missing/invalid hash"
        if h in seen_hashes:
            return False, pos, "Duplicate block hash"
        seen_hashes.add(h)

        blk = block_from_dict(b)
        if blk.hash != blk.calculate_hash():
            return False, pos, "Block tampering detected (hash mismatch)"

        if pos == 0:
            if str(b.get("previous_hash")) != "0":
                return False, pos, "Genesis previous_hash must be '0'"
        else:
            if str(b.get("previous_hash")) != (prev_hash or ""):
                return False, pos, "previous_hash mismatch"

        prev_hash = h
        expected_index += 1

    return True, None, "OK"
