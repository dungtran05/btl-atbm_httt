from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from checksum import calculate_chain_checksum
from manager import ReplicaChainManager
from peer_sync import PeerChain, choose_best_chain, fetch_peer_chain
from storage import JSONChainStorage, safe_write_json
from verify import verify_chain

logger = logging.getLogger(__name__)


class RecoveryFailed(RuntimeError):
    pass


class RecoveryManager:
    def __init__(self, root_dir: Path, storage: JSONChainStorage, manager: ReplicaChainManager) -> None:
        self.root_dir = root_dir
        self.storage = storage
        self.manager = manager
        self.leader_url = os.environ.get("LEADER_URL", "").strip()
        self.peer_urls = [u.strip() for u in os.environ.get("PEER_REPLICAS", "").split(",") if u.strip()]

    def _archive(self, payload: dict[str, Any]) -> Path:
        ts = int(time.time())
        out_dir = self.root_dir / "corrupted"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"blockchain_corrupted_{ts}.json"
        safe_write_json(path, payload)
        return path

    def recover_from_backup(self) -> dict[str, Any]:
        current = self.storage.load()
        archived = self._archive(current)
        backup_path = self.storage.backup_path
        if not backup_path.exists():
            raise RecoveryFailed("No backup available")
        backup: Any
        try:
            backup = json.loads(backup_path.read_text(encoding="utf-8"))
            if isinstance(backup, list):
                backup = {"chain": backup, "last_update": time.time()}
        except Exception as exc:
            raise RecoveryFailed(f"Failed to read backup: {exc}") from exc

        chain = backup.get("chain") if isinstance(backup, dict) else None
        if not isinstance(chain, list):
            raise RecoveryFailed("Backup format invalid")
        ok, bad, reason = verify_chain(chain)
        if not ok:
            raise RecoveryFailed(f"Backup chain invalid at {bad}: {reason}")

        self.manager.replace_chain(chain)
        logger.warning("Recovered chain from backup (len=%s). Archived=%s", len(chain), archived)
        return {"status": "recovered_from_backup", "archived": str(archived), "new_length": len(chain)}

    def recover_from_network(self) -> dict[str, Any]:
        current = self.storage.load()
        archived = self._archive(current)

        sources: list[str] = []
        if self.leader_url:
            sources.append(self.leader_url)
        sources.extend(self.peer_urls)
        sources = list(dict.fromkeys([s.rstrip("/") for s in sources if s.strip()]))
        if not sources:
            raise RecoveryFailed("No network sources configured (LEADER_URL / PEER_REPLICAS)")

        peers: list[PeerChain] = []
        for url in sources:
            st = fetch_peer_chain(url)
            peers.append(st)
            if st.ok:
                logger.info("Peer OK %s len=%s checksum=%s", st.url, st.length, st.checksum)
            else:
                logger.warning("Peer invalid %s reason=%s", st.url, st.reason)

        chosen, how = choose_best_chain(peers)
        if chosen is None:
            raise RecoveryFailed("No valid chain from network peers")

        ok, bad, reason = verify_chain(chosen)
        if not ok:
            raise RecoveryFailed(f"Chosen chain invalid at {bad}: {reason}")

        self.manager.replace_chain(chosen)
        logger.warning("Recovered chain from network (%s). Archived=%s len=%s", how, archived, len(chosen))
        return {
            "status": "recovered_from_network",
            "how": how,
            "archived": str(archived),
            "sources": [{"url": p.url, "ok": p.ok, "reason": p.reason, "length": p.length} for p in peers],
            "new_length": len(chosen),
        }

    @staticmethod
    def _prefix_hashes_match(local: list[dict[str, Any]], remote: list[dict[str, Any]], n: int) -> bool:
        if n <= 0:
            return True
        if len(local) < n or len(remote) < n:
            return False
        for i in range(n):
            if str(local[i].get("hash")) != str(remote[i].get("hash")):
                return False
        return True

    def sync_from_leader(self) -> dict[str, Any]:
        """
        Đồng bị định kỳ với Leader (GET /chain).
        - Local hỏng/rỗng: lấy nguyên chain từ leader (đã verify trong fetch_peer_chain).
        - Leader dài hơn và khớp prefix: kéo bản mới.
        - Cùng độ dài nhưng checksum khác: tuỳ SYNC_TRUST_LEADER.
        - Fork (prefix không khớp): tuỳ SYNC_TRUST_LEADER — nếu tin leader thì ghi đè.
        - Leader ngắn hơn local: không hạ cấp (leader có thể đang chậm).
        """
        url = self.leader_url
        if not url:
            return {"skipped": True, "reason": "no LEADER_URL", "replaced": False}

        peer = fetch_peer_chain(url)
        if not peer.ok or peer.chain is None:
            logger.debug("Đồng bộ leader bỏ qua: %s", peer.reason)
            return {"ok": False, "reason": peer.reason, "replaced": False}

        remote = peer.chain
        local: list[dict[str, Any]] = list(self.storage.load().get("chain") or [])
        local_ok, _, _ = verify_chain(local) if local else (False, None, "empty")

        trust_leader = os.environ.get("SYNC_TRUST_LEADER", "true").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        # Local rỗng hoặc verify fail → tin leader
        if not local or not local_ok:
            self.manager.replace_chain(remote)
            logger.info("Đồng bộ leader: thay toàn bộ chain (local không hợp lệ hoặc rỗng), len=%s", len(remote))
            return {"ok": True, "action": "full_replace_invalid_local", "replaced": True, "length": len(remote)}

        local_chk = calculate_chain_checksum(local)

        # Leader có nhiều block hơn
        if len(remote) > len(local):
            if self._prefix_hashes_match(local, remote, len(local)):
                self.manager.replace_chain(remote)
                logger.info("Đồng bộ leader: kéo dài chain %s -> %s", len(local), len(remote))
                return {"ok": True, "action": "extend", "replaced": True, "length": len(remote)}
            if trust_leader:
                self.manager.replace_chain(remote)
                logger.warning(
                    "Đồng bộ leader: fork tại prefix — SYNC_TRUST_LEADER=on, ghi đè bằng chain leader len=%s",
                    len(remote),
                )
                return {"ok": True, "action": "full_replace_fork", "replaced": True, "length": len(remote)}
            logger.warning("Đồng bộ leader: fork, không ghi đè (đặt SYNC_TRUST_LEADER=true để theo leader)")
            return {"ok": False, "reason": "divergence_prefix_mismatch", "replaced": False}

        # Cùng độ dài
        if len(remote) == len(local):
            if peer.checksum == local_chk:
                return {"ok": True, "action": "noop_identical", "replaced": False}
            if trust_leader:
                self.manager.replace_chain(remote)
                logger.warning("Đồng bộ leader: cùng độ dài nhưng checksum khác — đã ghi đè theo leader")
                return {"ok": True, "action": "replace_same_length", "replaced": True, "length": len(remote)}
            logger.warning("Đồng bộ leader: checksum khác, không ghi đè (SYNC_TRUST_LEADER=false)")
            return {"ok": False, "reason": "checksum_mismatch_same_length", "replaced": False}

        # Leader ngắn hơn (chưa kịp hoặc replica đi trước) — không xóa block local
        logger.debug(
            "Đồng bộ leader: bỏ qua (leader ngắn hơn local: leader=%s local=%s)",
            len(remote),
            len(local),
        )
        return {"ok": True, "action": "skip_leader_shorter", "replaced": False, "leader_len": len(remote), "local_len": len(local)}

    def recover(self) -> dict[str, Any]:
        try:
            return self.recover_from_backup()
        except RecoveryFailed as exc:
            logger.warning("Backup recovery failed: %s", exc)
        return self.recover_from_network()
