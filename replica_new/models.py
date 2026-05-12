from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Block:
    index: int
    timestamp: float
    document_hash: str
    document_name: str
    owner: str
    signature: str
    previous_hash: str
    certificate_id: str = ""
    metadata: dict[str, Any] | None = None
    file_path: str = ""
    qr_path: str = ""
    nonce: int = 0
    hash: str = ""
    issuer_name: str = ""

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("hash", None)
        if not self.certificate_id:
            data.pop("certificate_id", None)
        if not self.metadata:
            data.pop("metadata", None)
        if not self.file_path:
            data.pop("file_path", None)
        if not self.qr_path:
            data.pop("qr_path", None)
        if not self.issuer_name:
            data.pop("issuer_name", None)
        return data

    def calculate_hash(self) -> str:
        raw = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_genesis_block_fixed() -> Block:
    b = Block(
        index=0,
        timestamp=0.0,
        document_hash="GENESIS",
        document_name="Genesis Block",
        owner="system",
        signature="",
        previous_hash="0",
        nonce=0,
    )
    b.hash = b.calculate_hash()
    return b
