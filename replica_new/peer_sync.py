from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from checksum import calculate_chain_checksum
from verify import verify_chain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeerChain:
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


def fetch_peer_chain(base_url: str) -> PeerChain:
    base = base_url.rstrip("/")
    try:
        payload = _http_get_json(f"{base}/chain", timeout_s=5.0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return PeerChain(url=base, ok=False, reason=f"fetch_failed:{exc}")

    if not isinstance(payload, dict):
        return PeerChain(url=base, ok=False, reason="invalid_payload")
    chain = payload.get("chain")
    if not isinstance(chain, list):
        return PeerChain(url=base, ok=False, reason="missing_chain")

    ok, bad, reason = verify_chain(chain)
    if not ok:
        return PeerChain(url=base, ok=False, reason=f"chain_invalid@{bad}:{reason}")

    computed = calculate_chain_checksum(chain)
    reported = str(payload.get("checksum") or "")
    if reported and reported != computed:
        return PeerChain(url=base, ok=False, reason="checksum_mismatch")

    return PeerChain(url=base, ok=True, reason="ok", length=len(chain), checksum=computed, chain=chain)


def choose_best_chain(peers: list[PeerChain]) -> tuple[list[dict[str, Any]] | None, str]:
    valids = [p for p in peers if p.ok and p.chain is not None]
    if not valids:
        return None, "no_valid_peer"

    max_len = max(p.length for p in valids)
    candidates = [p for p in valids if p.length == max_len]
    if len(candidates) == 1:
        return candidates[0].chain, f"picked:{candidates[0].url}"

    votes: dict[str, int] = {}
    for p in candidates:
        votes[p.checksum] = votes.get(p.checksum, 0) + 1
    best_checksum = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    picked = [p for p in candidates if p.checksum == best_checksum][0]
    return picked.chain, f"majority:{votes[best_checksum]}/{len(candidates)}:{picked.url}"
