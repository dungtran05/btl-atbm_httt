from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .blockchain_manager import BlockRejected, BlockchainManager
from .recovery_manager import RecoveryFailed, RecoveryManager
from .verify_utils import verify_chain

logger = logging.getLogger(__name__)


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


def build_blockchain_router(root_dir: Path) -> APIRouter:
    router = APIRouter()

    blockchain = BlockchainManager(root_dir)
    replica_urls = [u.strip() for u in os.environ.get("REPLICA_URLS", "").split(",") if u.strip()]
    recovery = RecoveryManager(root_dir, blockchain, replica_urls=replica_urls)

    @router.get("/api/checksum")
    def api_checksum() -> dict[str, Any]:
        return {"checksum": blockchain.get_checksum()}

    # Inter-node endpoints (no /api prefix, per requirement)
    @router.get("/checksum")
    def node_checksum() -> dict[str, Any]:
        return {"checksum": blockchain.get_checksum()}

    @router.get("/api/verify")
    def api_verify() -> dict[str, Any]:
        ok, bad, reason = blockchain.verify_local()
        return {"ok": ok, "bad_index": bad, "reason": reason}

    @router.get("/verify")
    def node_verify() -> dict[str, Any]:
        ok, bad, reason = blockchain.verify_local()
        return {"ok": ok, "bad_index": bad, "reason": reason}

    @router.get("/chain")
    def node_chain() -> dict[str, Any]:
        # Replica endpoint: chain + checksum + length
        return blockchain.export_for_replica()

    @router.post("/api/add_block")
    def api_add_block(payload: AddBlockRequest) -> dict[str, Any]:
        try:
            block = blockchain.append_block_from_dict(payload.model_dump())
        except BlockRejected as exc:
            logger.warning("Reject block: %s", exc)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to append block")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error") from exc
        return {"status": "accepted", "block": block}

    @router.post("/api/recover")
    def api_recover() -> dict[str, Any]:
        try:
            result = recovery.recover()
        except RecoveryFailed as exc:
            logger.error("Recovery failed: %s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Recovery error")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error") from exc
        return result

    @router.get("/api/chain_raw")
    def api_chain_raw() -> dict[str, Any]:
        # Useful for debugging; frontend still uses /api/chain existing endpoint.
        payload = blockchain.load_chain_payload()
        chain = payload["chain"]
        ok, bad, reason = verify_chain(chain)
        return {"ok": ok, "bad_index": bad, "reason": reason, "payload": payload}

    return router

