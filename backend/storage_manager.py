from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


class FileLock:
    """
    Cross-platform advisory file lock.

    Notes:
    - On Windows uses msvcrt locking.
    - On Unix uses fcntl locking.
    - Lock is held for the lifetime of the context manager.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fh = None

    def __enter__(self) -> "FileLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                # Lock 1 byte (non-blocking loops are noisy; use blocking lock).
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception as exc:  # pragma: no cover
            try:
                self._fh.close()
            finally:
                self._fh = None
            raise StorageError(f"Failed to acquire lock: {self.lock_path}") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._fh:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def safe_write_json(path: Path, obj: Any) -> None:
    """
    Safe JSON write:
    - write to temp file in same directory
    - flush + fsync
    - atomic replace
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as exc:
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Failed cleaning tmp file %s", tmp_path)
        raise StorageError(f"Failed to write JSON atomically: {path}") from exc


@contextmanager
def locked_storage(lock_path: Path) -> Iterator[None]:
    with FileLock(lock_path):
        yield


class JSONBlockchainStorage:
    """
    JSON storage format:
    {
      "chain": [...],
      "last_update": <float>
    }
    """

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.data_dir = self.root_dir / "data"
        self.path = self.data_dir / "blockchain.json"
        self.backup_path = self.data_dir / "blockchain_backup.json"
        self.lock_path = self.data_dir / "blockchain.lock"

    def load(self) -> dict[str, Any]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return {"chain": [], "last_update": 0.0}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as exc:
            raise StorageError(f"Failed to load blockchain JSON: {self.path}") from exc

        # Backward compatible: legacy file is a list[block]
        if isinstance(data, list):
            logger.warning("Legacy blockchain.json format detected (list). Wrapping into new format.")
            return {"chain": data, "last_update": time.time()}

        if not isinstance(data, dict) or "chain" not in data:
            raise StorageError("Invalid blockchain.json format (expected dict with 'chain').")
        if not isinstance(data.get("chain"), list):
            raise StorageError("Invalid blockchain.json: 'chain' must be a list.")
        return {"chain": data.get("chain", []), "last_update": float(data.get("last_update") or 0.0)}

    def backup(self, payload: dict[str, Any]) -> None:
        try:
            safe_write_json(self.backup_path, payload)
        except Exception:
            logger.exception("Failed to write backup blockchain JSON to %s", self.backup_path)

    def save(self, payload: dict[str, Any]) -> None:
        if "chain" not in payload or not isinstance(payload["chain"], list):
            raise StorageError("Refusing to save invalid payload (missing 'chain').")
        payload = {"chain": payload["chain"], "last_update": float(payload.get("last_update") or time.time())}
        with locked_storage(self.lock_path):
            # Backup previous content first (best-effort)
            try:
                prev = self.load() if self.path.exists() else None
                if prev:
                    self.backup(prev)
            except Exception:
                logger.exception("Failed reading previous chain for backup")
            safe_write_json(self.path, payload)

