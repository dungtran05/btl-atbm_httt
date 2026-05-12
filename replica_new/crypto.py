from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def load_public_key_from_repo_root(repo_root: Path) -> object | None:
    raw = os.environ.get("KEY_DIR", str(repo_root / "keys"))
    key_dir = Path(raw)
    if not key_dir.is_absolute():
        key_dir = (repo_root / key_dir).resolve()
    pub_path = key_dir / "public_key.pem"
    if not pub_path.exists():
        return None
    data = pub_path.read_bytes()
    return serialization.load_pem_public_key(data)


def verify_signature(public_key: object | None, document_hash: str, signature_b64: str) -> bool:
    if public_key is None:
        return False
    try:
        public_key.verify(
            base64.b64decode(signature_b64.encode("ascii")),
            document_hash.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError):
        return False
