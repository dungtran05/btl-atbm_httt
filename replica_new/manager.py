from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from checksum import calculate_chain_checksum, read_checksum, write_checksum
from crypto import load_public_key_from_repo_root, verify_signature
from models import Block, create_genesis_block_fixed
from storage import JSONChainStorage
from verify import verify_chain

logger = logging.getLogger(__name__)


class BlockRejected(ValueError):
    pass


class ReplicaChainManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.data_dir = root_dir / "data"
        self.storage = JSONChainStorage(self.data_dir)
        self.checksum_path = self.data_dir / "checksum.sha256"
        self.public_key = load_public_key_from_repo_root(root_dir)

        self._cached_checksum: str | None = None
        self._cached_checksum_at: float = 0.0

    def ensure_genesis(self) -> None:
        payload = self.storage.load()
        if payload["chain"]:
            return
        genesis = asdict(create_genesis_block_fixed())
        self.storage.save({"chain": [genesis], "last_update": time.time()})
        self._write_checksum([genesis])
        logger.info("Genesis block created")

    def load_chain_payload(self) -> dict[str, Any]:
        return self.storage.load()

    def load_chain(self) -> list[dict[str, Any]]:
        return self.storage.load()["chain"]

    def _write_checksum(self, chain: list[dict[str, Any]]) -> str:
        chk = calculate_chain_checksum(chain)
        write_checksum(self.checksum_path, chk)
        self._cached_checksum = chk
        self._cached_checksum_at = time.time()
        return chk

    def get_checksum(self) -> str:
        if self._cached_checksum and (time.time() - self._cached_checksum_at) < 10.0:
            return self._cached_checksum
        on_disk = read_checksum(self.checksum_path)
        if on_disk:
            self._cached_checksum = on_disk
            self._cached_checksum_at = time.time()
            return on_disk
        chain = self.load_chain()
        return self._write_checksum(chain)

    def verify_local(self) -> tuple[bool, int | None, str]:
        chain = self.load_chain()
        ok, bad, reason = verify_chain(chain)
        if not ok:
            return ok, bad, reason
        expected = calculate_chain_checksum(chain)
        got = read_checksum(self.checksum_path)
        if got and got != expected:
            return False, None, "Checksum mismatch (tampering detected)"
        if not got:
            self._write_checksum(chain)
        return True, None, "OK"

    def export_for_peer(self) -> dict[str, Any]:
        payload = self.load_chain_payload()
        chain = payload["chain"]
        chk = calculate_chain_checksum(chain)
        return {"chain": chain, "checksum": chk, "length": len(chain), "last_update": payload.get("last_update", 0.0)}

    def append_block_from_dict(self, block_dict: dict[str, Any]) -> dict[str, Any]:
        payload = self.storage.load()
        chain = payload["chain"]
        if not chain:
            self.ensure_genesis()
            payload = self.storage.load()
            chain = payload["chain"]

        incoming_hash = str(block_dict.get("hash") or "")
        if not incoming_hash:
            raise BlockRejected("Missing block hash")
        if any(str(b.get("hash")) == incoming_hash for b in chain):
            raise BlockRejected("Duplicate block")

        tip = chain[-1]
        expected_index = int(tip["index"]) + 1
        if int(block_dict.get("index", -1)) != expected_index:
            raise BlockRejected(f"Invalid index (expected {expected_index})")
        if str(block_dict.get("previous_hash")) != str(tip.get("hash")):
            raise BlockRejected("previous_hash does not match tip")

        blk = Block(
            index=int(block_dict["index"]),
            timestamp=float(block_dict["timestamp"]),
            document_hash=str(block_dict["document_hash"]),
            document_name=str(block_dict["document_name"]),
            owner=str(block_dict["owner"]),
            signature=str(block_dict["signature"]),
            previous_hash=str(block_dict["previous_hash"]),
            certificate_id=str(block_dict.get("certificate_id") or ""),
            metadata=block_dict.get("metadata"),
            file_path=str(block_dict.get("file_path") or ""),
            qr_path=str(block_dict.get("qr_path") or ""),
            nonce=int(block_dict.get("nonce") or 0),
            hash=str(block_dict.get("hash") or ""),
            issuer_name=str(block_dict.get("issuer_name") or ""),
        )

        if blk.hash != blk.calculate_hash():
            raise BlockRejected("Invalid block hash")

        if not verify_signature(self.public_key, blk.document_hash, blk.signature):
            raise BlockRejected("Invalid signature")

        if any(str(b.get("document_hash")) == blk.document_hash for b in chain):
            raise BlockRejected("Duplicate document_hash")

        chain.append(asdict(blk))
        payload["last_update"] = time.time()
        self.storage.save(payload)
        self._write_checksum(chain)
        logger.info("Appended block #%s hash=%s", blk.index, blk.hash)
        return asdict(blk)

    def replace_chain(self, chain: list[dict[str, Any]]) -> None:
        """Ghi đè chain sau khi đã verify (dùng cho đồng bộ leader / phục hồi)."""
        ok, bad, reason = verify_chain(chain)
        if not ok:
            raise ValueError(f"Chain không hợp lệ tại block {bad}: {reason}")
        self.storage.save({"chain": chain, "last_update": time.time()})
        self._write_checksum(chain)
        logger.info("Đã thay chain cục bộ (độ dài=%s)", len(chain))
