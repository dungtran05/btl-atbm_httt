from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .checksum_utils import calculate_chain_checksum
from .verify_utils import verify_chain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplicaState:
    url: str
    ok: bool
    reason: str
    length: int = 0
    checksum: str = ""
    chain: list[dict[str, Any]] | None = None


def _http_get_json(url: str, timeout_s: float = 5.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def fetch_replica_state(base_url: str) -> ReplicaState:
    base = base_url.rstrip("/")
    try:
        chain_payload = _http_get_json(f"{base}/chain", timeout_s=5.0)
        checksum_payload = _http_get_json(f"{base}/checksum", timeout_s=5.0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return ReplicaState(url=base, ok=False, reason=f"fetch_failed: {exc}")

    chain = chain_payload.get("chain") if isinstance(chain_payload, dict) else None
    if not isinstance(chain, list):
        return ReplicaState(url=base, ok=False, reason="invalid_chain_payload")

    # Verify integrity and checksum consistency
    ok, bad, reason = verify_chain(chain)
    if not ok:
        return ReplicaState(url=base, ok=False, reason=f"chain_invalid@{bad}:{reason}")

    reported_checksum = ""
    if isinstance(checksum_payload, dict):
        reported_checksum = str(checksum_payload.get("checksum") or "")
    computed_checksum = calculate_chain_checksum(chain)
    if reported_checksum and reported_checksum != computed_checksum:
        return ReplicaState(url=base, ok=False, reason="checksum_mismatch_replica")

    return ReplicaState(
        url=base,
        ok=True,
        reason="ok",
        length=len(chain),
        checksum=computed_checksum,
        chain=chain,
    )


def choose_majority_chain(states: list[ReplicaState]) -> tuple[list[dict[str, Any]] | None, str]:
    """
    Select chain by:
    - only valid states
    - prefer longest chain
    - if multiple longest: pick checksum with most votes (majority consensus)
    """

    valids = [s for s in states if s.ok and s.chain is not None]
    if not valids:
        return None, "no_valid_replica_chain"

    max_len = max(s.length for s in valids)
    candidates = [s for s in valids if s.length == max_len]
    if len(candidates) == 1:
        return candidates[0].chain, f"picked:{candidates[0].url}"

    votes: dict[str, int] = {}
    for s in candidates:
        votes[s.checksum] = votes.get(s.checksum, 0) + 1
    # pick highest vote; stable tie-breaker by checksum value
    best_checksum = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    picked = [s for s in candidates if s.checksum == best_checksum][0]
    return picked.chain, f"majority:{votes[best_checksum]}/{len(candidates)}:{picked.url}"

