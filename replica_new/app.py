from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Thư mục chứa app.py = gốc replica; luôn đưa vào sys.path để import module cùng cấp (models, manager, …)
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Khi copy folder ra chỗ khác / chạy từ CMD khác thư mục: cwd = thư mục replica
# để .env (KEY_DIR=./keys), data/, logs không lệch chỗ.
try:
    os.chdir(ROOT_DIR)
except OSError:
    pass

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from background import BackgroundLeaderSync, BackgroundVerifier
from manager import BlockRejected, ReplicaChainManager
from recovery import RecoveryFailed, RecoveryManager


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class AddBlockRequest(BaseModel):
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
    hash: str
    issuer_name: str = ""


_configure_logging()
logger = logging.getLogger("replica")

os.environ.setdefault("NODE_ROLE", "replica")

app = FastAPI(title="DocumentChain Replica")
manager = ReplicaChainManager(ROOT_DIR)
recovery = RecoveryManager(ROOT_DIR, manager.storage, manager)
RECOVERY_LOCKED = False


def _leader_sync_tick() -> None:
    """Đồng bị với leader; nếu ghi đè chain thành công thì mở khóa recovery_locked."""
    global RECOVERY_LOCKED
    try:
        out = recovery.sync_from_leader()
        if isinstance(out, dict) and out.get("replaced"):
            RECOVERY_LOCKED = False
            logger.info("Đồng bộ leader xong, đã mở recovery_locked")
    except Exception:
        logger.exception("Lỗi đồng bị leader")


@app.on_event("startup")
def startup() -> None:
    global RECOVERY_LOCKED
    manager.ensure_genesis()
    if manager.public_key is None:
        logger.warning("Missing public_key.pem. Replica will reject /replica/add_block until KEY_DIR is configured.")

    ok, bad, reason = manager.verify_local()
    if ok:
        logger.info("Startup verify OK")
    else:
        logger.error("Startup verify FAIL bad=%s reason=%s", bad, reason)
        try:
            recovery.recover()
            RECOVERY_LOCKED = False
        except RecoveryFailed:
            logger.exception("Replica auto-recovery failed")
            RECOVERY_LOCKED = True

    # Một lần đồng bị ngay khi có LEADER_URL (sau phục hồi cục bộ).
    if os.environ.get("LEADER_URL", "").strip():
        _leader_sync_tick()

    def on_corruption(reason: str) -> None:
        global RECOVERY_LOCKED
        logger.error("Tampering/corruption detected: %s", reason)
        try:
            recovery.recover()
            RECOVERY_LOCKED = False
        except RecoveryFailed:
            logger.exception("Replica recovery failed")
            RECOVERY_LOCKED = True

    verify_interval = float(os.environ.get("VERIFY_INTERVAL_S", "30"))
    BackgroundVerifier(manager.verify_local, on_corruption, interval_s=verify_interval).start()

    leader_url = os.environ.get("LEADER_URL", "").strip()
    sync_interval = float(os.environ.get("LEADER_SYNC_INTERVAL_S", "5"))
    if leader_url and sync_interval > 0:
        BackgroundLeaderSync(_leader_sync_tick, interval_s=sync_interval).start()
    elif leader_url and sync_interval <= 0:
        logger.warning("LEADER_SYNC_INTERVAL_S<=0: chỉ đồng bị thủ công qua POST /replica/sync")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "role": "replica", "recovery_locked": str(RECOVERY_LOCKED).lower()}


@app.get("/chain")
def chain() -> dict[str, Any]:
    return manager.export_for_peer()


@app.get("/checksum")
def checksum() -> dict[str, Any]:
    return {"checksum": manager.get_checksum()}


@app.get("/verify")
def verify() -> dict[str, Any]:
    ok, bad, reason = manager.verify_local()
    return {"ok": ok, "bad_index": bad, "reason": reason}


@app.post("/replica/sync")
def replica_sync() -> dict[str, Any]:
    """Đồng bị thủ công với LEADER_URL (cùng logic luồng định kỳ)."""
    global RECOVERY_LOCKED
    try:
        out = recovery.sync_from_leader()
        if isinstance(out, dict) and out.get("replaced"):
            RECOVERY_LOCKED = False
        return out if isinstance(out, dict) else {"result": out}
    except Exception as exc:
        logger.exception("replica_sync failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.post("/replica/recover")
def replica_recover() -> dict[str, Any]:
    """Backup → rồi leader/peers (giống pipeline recover nội bộ)."""
    global RECOVERY_LOCKED
    try:
        result = recovery.recover()
        RECOVERY_LOCKED = False
        return result
    except RecoveryFailed as exc:
        RECOVERY_LOCKED = True
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/replica/add_block")
def replica_add_block(payload: AddBlockRequest) -> dict[str, Any]:
    if RECOVERY_LOCKED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Replica is corrupted and cannot recover (waiting for leader/peers).",
        )
    try:
        block = manager.append_block_from_dict(payload.model_dump())
    except BlockRejected as exc:
        logger.warning("Reject broadcast block: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to append broadcast block")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error") from exc
    return {"status": "accepted", "block": block}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run("app:app", host=host, port=port, reload=False)
