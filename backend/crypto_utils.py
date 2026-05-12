from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT_DIR = Path(__file__).resolve().parent.parent
KEY_DIR = ROOT_DIR / "keys"
PRIVATE_KEY_PATH = KEY_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEY_DIR / "public_key.pem"


def ensure_key_pair() -> None:
    """Ensure the single system-wide key pair exists. Generated once and reused for all issuers."""
    KEY_DIR.mkdir(exist_ok=True)
    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PUBLIC_KEY_PATH.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def get_public_key_pem() -> str:
    """Return the system public key as PEM string."""
    ensure_key_pair()
    return PUBLIC_KEY_PATH.read_text(encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_private_key():
    ensure_key_pair()
    return serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)


def load_public_key():
    ensure_key_pair()
    return serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())


def sign_hash(document_hash: str) -> str:
    """Sign a document hash with the single system-wide private key."""
    private_key = load_private_key()
    signature = private_key.sign(
        document_hash.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def verify_signature(document_hash: str, signature_b64: str) -> bool:
    """Verify a signature using the single system-wide public key."""
    public_key = load_public_key()
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
