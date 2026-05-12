from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from werkzeug.security import generate_password_hash

from .blockchain import Block, DocumentBlockchain
from .blockchain_manager import BlockchainManager
from .verify_utils import verify_chain


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "documents.db"
BLOCKCHAIN_FILE = ROOT_DIR / "data" / "blockchain.json"
ROLES = {"admin", "issuer", "verifier"}


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL NOT NULL,
                document_hash TEXT NOT NULL,
                document_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                signature TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                certificate_id TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                file_path TEXT DEFAULT '',
                qr_path TEXT DEFAULT '',
                nonce INTEGER NOT NULL,
                hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'issuer', 'verifier')),
                organization_name TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        migrate_blocks(conn)
        migrate_users(conn)
        admin_exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        if not admin_exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, organization_name) VALUES (?, ?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "admin", ""),
            )


def migrate_blocks(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(blocks)").fetchall()}
    migrations = {
        "certificate_id": "ALTER TABLE blocks ADD COLUMN certificate_id TEXT DEFAULT ''",
        "metadata":       "ALTER TABLE blocks ADD COLUMN metadata TEXT DEFAULT '{}'",
        "file_path":      "ALTER TABLE blocks ADD COLUMN file_path TEXT DEFAULT ''",
        "qr_path":        "ALTER TABLE blocks ADD COLUMN qr_path TEXT DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)


def migrate_users(conn: sqlite3.Connection) -> None:
    """Đảm bảo bảng users có cột organization_name và role hợp lệ."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if not columns:
        return

    # Thêm cột organization_name nếu chưa có
    if "organization_name" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN organization_name TEXT DEFAULT ''")

    # Sửa các role cũ nếu có
    conn.execute("UPDATE users SET role = 'issuer' WHERE role IN ('user', 'isser')")
    conn.execute("UPDATE users SET role = 'verifier' WHERE role = 'viewer'")


def load_blockchain() -> DocumentBlockchain:
    BLOCKCHAIN_FILE.parent.mkdir(exist_ok=True)
    if BLOCKCHAIN_FILE.exists():
        # New storage format is handled by BlockchainManager (backward-compatible with legacy list).
        manager = BlockchainManager(ROOT_DIR)
        payload = manager.load_chain_payload()
        chain_data = payload["chain"]
        # Best-effort integrity check at load time (do not throw to keep old flows alive).
        ok, bad, reason = verify_chain(chain_data) if isinstance(chain_data, list) else (False, None, "invalid_payload")
        if not ok:
            # Caller (main startup/background verifier) can trigger recovery; here we just warn.
            print(f"WARNING: blockchain.json integrity issue at {bad}: {reason}")
        blocks = [
            Block(
                index=block_data["index"],
                timestamp=block_data["timestamp"],
                document_hash=block_data["document_hash"],
                document_name=block_data["document_name"],
                owner=block_data["owner"],
                signature=block_data["signature"],
                previous_hash=block_data["previous_hash"],
                certificate_id=block_data.get("certificate_id", ""),
                metadata=block_data.get("metadata"),
                file_path=block_data.get("file_path", ""),
                qr_path=block_data.get("qr_path", ""),
                nonce=block_data.get("nonce", 0),
                hash=block_data.get("hash", ""),
                issuer_name=block_data.get("issuer_name", ""),
            )
            for block_data in (chain_data or [])
        ]
        blockchain = DocumentBlockchain(blocks=blocks)
    else:
        init_db()
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM blocks ORDER BY block_index").fetchall()
        if rows:
            blocks = [
                Block(
                    index=row["block_index"],
                    timestamp=row["timestamp"],
                    document_hash=row["document_hash"],
                    document_name=row["document_name"],
                    owner=row["owner"],
                    signature=row["signature"],
                    previous_hash=row["previous_hash"],
                    certificate_id=row["certificate_id"] or "",
                    metadata=json.loads(row["metadata"] or "{}"),
                    file_path=row["file_path"] or "",
                    qr_path=row["qr_path"] or "",
                    nonce=row["nonce"],
                    hash=row["hash"],
                    issuer_name="",
                )
                for row in rows
            ]
            blockchain = DocumentBlockchain(blocks=blocks)
            save_blockchain(blockchain)
            print("Migrated blockchain from SQLite to JSON")
        else:
            blockchain = DocumentBlockchain()
            save_blockchain(blockchain)
    return blockchain


def save_block(block: Block) -> None:
    blockchain = load_blockchain()
    if not any(b.index == block.index for b in blockchain.chain):
        blockchain.chain.append(block)
    save_blockchain(blockchain)


def save_blockchain(blockchain: DocumentBlockchain) -> None:
    BLOCKCHAIN_FILE.parent.mkdir(exist_ok=True)
    manager = BlockchainManager(ROOT_DIR)
    data = [block.__dict__ for block in blockchain.chain]
    # Store in new format + update checksum (safe write + backup handled internally).
    manager.storage.save({"chain": data, "last_update": time.time()})
    # Keep checksum consistent for tamper-detection.
    manager._write_checksum(data)


def list_blocks() -> list[dict]:
    blockchain = load_blockchain()
    return [json.loads(json.dumps(block.__dict__)) for block in reversed(blockchain.chain)]


def list_blocks_for_user(user: dict[str, Any]) -> list[dict]:
    blocks = list_blocks()
    if user["role"] == "admin":
        return blocks
    if user["role"] == "issuer":
        return [block for block in blocks if block["owner"] == user["username"]]
    return []


def find_user_by_username(username: str) -> sqlite3.Row | None:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, role, organization_name, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()


def find_user_by_id(user_id: int) -> sqlite3.Row | None:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, role, organization_name, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def list_users() -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, role, organization_name, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def create_user(username: str, password: str, role: str, organization_name: str = "") -> None:
    if role not in ROLES:
        raise ValueError("Invalid role")
    init_db()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, organization_name) VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), role, organization_name),
        )


def update_user(user_id: int, username: str, role: str, password: str | None = None, organization_name: str = "") -> None:
    if role not in ROLES:
        raise ValueError("Invalid role")
    init_db()
    with get_connection() as conn:
        if password:
            conn.execute(
                """
                UPDATE users
                SET username = ?, role = ?, password_hash = ?, organization_name = ?
                WHERE id = ?
                """,
                (username, role, generate_password_hash(password), organization_name, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET username = ?, role = ?, organization_name = ? WHERE id = ?",
                (username, role, organization_name, user_id),
            )
        if conn.total_changes == 0:
            raise LookupError("User not found")


def delete_user(user_id: int) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if conn.total_changes == 0:
            raise LookupError("User not found")
