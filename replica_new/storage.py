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
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fh = None

    def __enter__(self) -> FileLock:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        except Exception as exc:
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
            tmp_path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Failed cleaning tmp file %s", tmp_path)
        raise StorageError(f"Failed to write JSON atomically: {path}") from exc


@contextmanager
def locked(lock_path: Path) -> Iterator[None]:
    with FileLock(lock_path):
        yield


class JSONChainStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "blockchain.json"
        self.backup_path = data_dir / "blockchain_backup.json"
        self.lock_path = data_dir / "blockchain.lock"

    def load(self) -> dict[str, Any]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return {"chain": [], "last_update": 0.0}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise StorageError(f"Failed to load blockchain JSON: {self.path}") from exc

        if isinstance(data, list):
            return {"chain": data, "last_update": time.time()}
        if not isinstance(data, dict) or "chain" not in data or not isinstance(data.get("chain"), list):
            raise StorageError("Invalid blockchain.json format")
        return {"chain": data.get("chain", []), "last_update": float(data.get("last_update") or 0.0)}

    def save(self, payload: dict[str, Any]) -> None:
        if "chain" not in payload or not isinstance(payload["chain"], list):
            raise StorageError("Refusing to save invalid payload")
        payload = {"chain": payload["chain"], "last_update": float(payload.get("last_update") or time.time())}
        with locked(self.lock_path):
            try:
                if self.path.exists():
                    prev = self.load()
                    safe_write_json(self.backup_path, prev)
            except Exception:
                logger.exception("Failed writing backup")
            safe_write_json(self.path, payload)
