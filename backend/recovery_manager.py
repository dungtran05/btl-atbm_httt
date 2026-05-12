from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .blockchain_manager import BlockchainManager
from .storage_manager import JSONBlockchainStorage, safe_write_json
from .replica_sync_service import ReplicaState, choose_majority_chain, fetch_replica_state
from .verify_utils import verify_chain

logger = logging.getLogger(__name__)


class RecoveryFailed(RuntimeError):
    pass


class RecoveryManager:
    """
    Self-healing strategy (documented):
    - detect local corruption via verify_chain/checksum mismatch
    - ask all replicas for their chain + checksum
    - discard invalid replica responses
    - choose the longest valid chain
    - if multiple longest chains exist, select the one with the most replica votes (majority by checksum)
    - overwrite local chain with the selected chain
    - archive the corrupted local chain to corrupted/blockchain_corrupted_TIMESTAMP.json
    """

    def __init__(self, root_dir: Path, blockchain: BlockchainManager, replica_urls: list[str]) -> None:
        self.root_dir = root_dir
        self.blockchain = blockchain
        self.replica_urls = [u.strip() for u in replica_urls if u.strip()]
        self.storage = JSONBlockchainStorage(root_dir)

    def _archive_corrupted(self, payload: dict[str, Any]) -> Path:
        ts = int(time.time())
        out_dir = self.root_dir / "corrupted"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"blockchain_corrupted_{ts}.json"
        safe_write_json(path, payload)
        return path

    def recover(self) -> dict[str, Any]:
        local_payload = self.storage.load()
        local_chain = local_payload.get("chain", [])

        # Archive local state first (even if it's valid, it's still useful for audit when manual recover is triggered)
        archived = self._archive_corrupted(local_payload)
        logger.warning("Archived local chain snapshot to %s", archived)

        if not self.replica_urls:
            raise RecoveryFailed("No replicas configured")

        states: list[ReplicaState] = []
        for url in self.replica_urls:
            st = fetch_replica_state(url)
            states.append(st)
            if st.ok:
                logger.info("Replica OK %s len=%s checksum=%s", st.url, st.length, st.checksum)
            else:
                logger.warning("Replica invalid %s reason=%s", st.url, st.reason)

        chosen_chain, how = choose_majority_chain(states)
        if chosen_chain is None:
            raise RecoveryFailed("No valid chain from replicas")

        ok, bad, reason = verify_chain(chosen_chain)
        if not ok:
            raise RecoveryFailed(f"Chosen chain failed verification: {bad} {reason}")

        self.blockchain.overwrite_chain(chosen_chain)
        logger.warning("Recovery completed (%s). Local overwritten from replicas.", how)
        return {
            "status": "recovered",
            "how": how,
            "archived_local": str(archived),
            "replicas": [{"url": s.url, "ok": s.ok, "reason": s.reason, "length": s.length} for s in states],
            "old_length": len(local_chain) if isinstance(local_chain, list) else 0,
            "new_length": len(chosen_chain),
        }

