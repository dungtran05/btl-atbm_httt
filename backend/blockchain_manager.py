from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .blockchain import Block
from .checksum_utils import calculate_chain_checksum, read_checksum_file, write_checksum_file
from .crypto_utils import verify_signature
from .storage_manager import JSONBlockchainStorage, StorageError
from .verify_utils import verify_chain

logger = logging.getLogger(__name__)


class BlockRejected(ValueError):
    pass


class BlockchainManager:
    """
    Thread-safe blockchain access and append-only rules.

    Leader responsibilities:
    - verify block hash
    - verify signature
    - verify previous_hash matches tip
    - reject duplicates
    """

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.storage = JSONBlockchainStorage(root_dir)
        self.checksum_path = root_dir / "data" / "checksum.sha256"

        self._cached_checksum: str | None = None
        self._cached_checksum_at: float = 0.0

    def load_chain_payload(self) -> dict[str, Any]:
        return self.storage.load()

    def load_chain(self) -> list[dict[str, Any]]:
        return self.load_chain_payload()["chain"]

    def get_checksum(self) -> str:
        # Cache in-memory for performance (updated on writes).
        if self._cached_checksum and (time.time() - self._cached_checksum_at) < 10.0:
            return self._cached_checksum
        on_disk = read_checksum_file(self.checksum_path)
        if on_disk:
            self._cached_checksum = on_disk
            self._cached_checksum_at = time.time()
            return on_disk
        # If missing, compute once and write.
        chain = self.load_chain()
        chk = calculate_chain_checksum(chain)
        write_checksum_file(self.checksum_path, chk)
        self._cached_checksum = chk
        self._cached_checksum_at = time.time()
        return chk

    def _write_checksum(self, chain: list[dict[str, Any]]) -> str:
        chk = calculate_chain_checksum(chain)
        write_checksum_file(self.checksum_path, chk)
        self._cached_checksum = chk
        self._cached_checksum_at = time.time()
        return chk

    def verify_local(self) -> tuple[bool, int | None, str]:
        chain = self.load_chain()
        ok, bad, reason = verify_chain(chain)
        if not ok:
            return ok, bad, reason
        expected = calculate_chain_checksum(chain)
        got = read_checksum_file(self.checksum_path)
        if got and got != expected:
            return False, None, "Checksum mismatch (JSON tampering detected)"
        if not got:
            # Self-heal: write checksum if missing
            self._write_checksum(chain)
        return True, None, "OK"

    @staticmethod
    def create_genesis_block_fixed() -> Block:
        """
        Fixed genesis block. Its hash is deterministic and does not depend on mining.
        """

        b = Block(
            index=0,
            timestamp=0.0,
            document_hash="GENESIS",
            document_name="Genesis Block",
            owner="system",
            signature="",
            previous_hash="0",
            certificate_id="",
            metadata=None,
            file_path="",
            qr_path="",
            nonce=0,
            hash="",
            issuer_name="",
        )
        b.hash = b.calculate_hash()
        return b

    def ensure_genesis(self) -> None:
        payload = self.load_chain_payload()
        chain = payload["chain"]
        if chain:
            return
        genesis = asdict(self.create_genesis_block_fixed())
        payload = {"chain": [genesis], "last_update": time.time()}
        self.storage.save(payload)
        self._write_checksum(payload["chain"])
        logger.info("Genesis block created")

    def append_block_from_dict(self, block_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Append a fully-formed block (created by client).
        Enforces immutability of existing history by requiring previous_hash == tip.hash.
        """

        if not isinstance(block_dict, dict):
            raise BlockRejected("Invalid block payload")

        payload = self.load_chain_payload()
        chain: list[dict[str, Any]] = payload["chain"]

        if not chain:
            self.ensure_genesis()
            payload = self.load_chain_payload()
            chain = payload["chain"]

        # Duplicate checks
        incoming_hash = str(block_dict.get("hash") or "")
        if not incoming_hash:
            raise BlockRejected("Missing block hash")
        if any(str(b.get("hash")) == incoming_hash for b in chain):
            raise BlockRejected("Duplicate block (hash already exists)")

        tip = chain[-1]
        expected_index = int(tip["index"]) + 1
        if int(block_dict.get("index", -1)) != expected_index:
            raise BlockRejected(f"Invalid index (expected {expected_index})")
        if str(block_dict.get("previous_hash")) != str(tip.get("hash")):
            raise BlockRejected("previous_hash does not match current tip (reject rewriting history)")

        # Verify hash deterministically
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

        calculated = blk.calculate_hash()
        if blk.hash != calculated:
            raise BlockRejected("Invalid block hash (tampering detected)")

        # Verify signature over document_hash
        if not verify_signature(blk.document_hash, blk.signature):
            raise BlockRejected("Invalid signature")

        # Reject duplicate document_hash
        if any(str(b.get("document_hash")) == blk.document_hash for b in chain):
            raise BlockRejected("Duplicate document_hash")

        chain.append(asdict(blk))
        payload["last_update"] = time.time()
        try:
            self.storage.save(payload)
        except StorageError as exc:
            logger.exception("Failed saving chain")
            raise

        self._write_checksum(chain)
        logger.info("Appended block #%s hash=%s", blk.index, blk.hash)
        return asdict(blk)

    def overwrite_chain(self, new_chain: list[dict[str, Any]]) -> None:
        ok, bad, reason = verify_chain(new_chain)
        if not ok:
            raise BlockRejected(f"Refusing to overwrite with invalid chain: {bad} {reason}")
        payload = {"chain": new_chain, "last_update": time.time()}
        self.storage.save(payload)
        self._write_checksum(new_chain)
        logger.warning("Local chain overwritten via recovery (length=%s)", len(new_chain))

    def export_for_replica(self) -> dict[str, Any]:
        payload = self.load_chain_payload()
        chain = payload["chain"]
        chk = calculate_chain_checksum(chain)
        return {"chain": chain, "checksum": chk, "length": len(chain), "last_update": payload.get("last_update", 0.0)}

