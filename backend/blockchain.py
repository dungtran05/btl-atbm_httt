from __future__ import annotations

import hashlib
import json
import time
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
    issuer_name: str = ""  # Tên đơn vị của issuer gắn trực tiếp lên block

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
        raw = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def mine(self, difficulty: int) -> None:
        prefix = "0" * difficulty
        while True:
            digest = self.calculate_hash()
            if digest.startswith(prefix):
                self.hash = digest
                return
            self.nonce += 1


class DocumentBlockchain:
    def __init__(self, blocks: list[Block] | None = None, difficulty: int = 3) -> None:
        self.difficulty = difficulty
        self.chain = blocks[:] if blocks else [self._create_genesis_block()]

    def _create_genesis_block(self) -> Block:
        block = Block(
            index=0,
            timestamp=time.time(),
            document_hash="GENESIS",
            document_name="Genesis Block",
            owner="system",
            signature="",
            previous_hash="0",
        )
        block.mine(self.difficulty)
        return block

    def add_document(
        self,
        document_hash: str,
        document_name: str,
        owner: str,
        signature: str,
        certificate_id: str = "",
        metadata: dict[str, Any] | None = None,
        file_path: str = "",
        qr_path: str = "",
        issuer_name: str = "",
    ) -> Block:
        previous = self.chain[-1]
        block = Block(
            index=len(self.chain),
            timestamp=time.time(),
            document_hash=document_hash,
            document_name=document_name,
            owner=owner,
            signature=signature,
            previous_hash=previous.hash,
            certificate_id=certificate_id,
            metadata=metadata,
            file_path=file_path,
            qr_path=qr_path,
            issuer_name=issuer_name,
        )
        block.mine(self.difficulty)
        self.chain.append(block)
        return block

    def verify_chain(self) -> tuple[bool, str]:
        for index, block in enumerate(self.chain):
            if block.hash != block.calculate_hash():
                return False, f"Block {index} has an invalid hash."
            if index > 0 and block.previous_hash != self.chain[index - 1].hash:
                return False, f"Block {index} is not linked to the previous block."
            if not block.hash.startswith("0" * self.difficulty):
                return False, f"Block {index} does not satisfy proof-of-work."
        return True, "Blockchain is valid."

    def find_by_document_hash(self, document_hash: str) -> Block | None:
        for block in reversed(self.chain):
            if block.document_hash == document_hash:
                return block
        return None

    def find_by_certificate_id(self, certificate_id: str) -> Block | None:
        for block in reversed(self.chain):
            if block.certificate_id == certificate_id:
                return block
        return None
