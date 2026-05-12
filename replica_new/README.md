# Replica (`replica_new`) — node trong hệ DocumentChain

Replica **không mining**, **không tự tạo block**. Vai trò:

1. **Nhận block** từ Leader (`POST /replica/add_block`) — verify hash, chữ ký, `previous_hash`.
2. **Đồng bị định kỳ** với Leader: `GET {LEADER_URL}/chain` (cùng định dạng với backend `export_for_replica`).
3. **Verify định kỳ** chain cục bộ + file checksum — lỗi thì kích hoạt **recover** (backup → leader/peers).
4. **Giữ chain** an toàn (ghi JSON atomic + lock + backup).

## Tham gia chuẩn với Leader

Trên máy **Leader** (backend FastAPI), để replica đọc được chain:

- Leader phải expose **`GET /chain`** trả `{ chain, checksum, length, last_update }` (đã có trong router blockchain của project).

Trên **Replica**, trong `.env`:

- `LEADER_URL=http://IP_LEADER:PORT` — ví dụ `http://127.0.0.1:8000`
- `LEADER_SYNC_INTERVAL_S=5` — mỗi 5 giây kéo chain (đặt `0` để tắt; vẫn gọi tay `POST /replica/sync`).
- `SYNC_TRUST_LEADER=true` — khi fork hoặc cùng độ dài nhưng checksum khác: **ghi đè theo Leader** (khuyến nghị cho replica phụ).

Copy **`keys/public_key.pem`** từ Leader vào `replica_new/keys/` (hoặc `KEY_DIR`).

## Copy folder ra chạy riêng (không cần repo gốc)

1. Copy **nguyên cả thư mục** `replica_new` sang ổ khác / máy khác (xem `COPY_THIS_FOLDER.txt`).
2. **`app.py` tự đặt working directory** vào thư mục chứa nó → `KEY_DIR=./keys`, file `data/` luôn nằm đúng chỗ dù bạn chạy `python D:\path\app.py` từ `C:\`.
3. Khởi động nhanh:
   - Windows: `.\run.ps1`
   - Linux/macOS: `chmod +x run.sh && ./run.sh`
   - Hoặc: `python app.py` sau khi `cd` vào thư mục replica và đã `pip install -r requirements.txt`.

Sao chép **keys/public_key.pem** từ Leader vào `replica_new/keys/` (hoặc chỉnh `KEY_DIR` trong `.env`).

## Chạy (Windows PowerShell)

```powershell
cd replica_new
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Sửa file .env có sẵn (LEADER_URL, PORT, KEY_DIR...)
python app.py
```

## API

| Endpoint | Mô tả |
|----------|--------|
| `GET /health` | Trạng thái + `recovery_locked` |
| `GET /chain` | Chain cho Leader/recovery đọc |
| `GET /checksum` | Checksum toàn chain |
| `GET /verify` | Kiểm tra chain + checksum cục bộ |
| `POST /replica/add_block` | Leader broadcast block |
| `POST /replica/sync` | Đồng bị ngay với `LEADER_URL` |
| `POST /replica/recover` | Recover: backup → network (leader + `PEER_REPLICAS`) |

## Storage (trong thư mục replica)

- `data/blockchain.json`, `data/blockchain_backup.json`, `data/checksum.sha256`, `data/blockchain.lock`
- `corrupted/` — snapshot chain lỗi trước khi ghi đè

## Biến môi trường chính

Xem file `.env`: `VERIFY_INTERVAL_S`, `LEADER_SYNC_INTERVAL_S`, `SYNC_TRUST_LEADER`, `PEER_REPLICAS`, v.v.

## Khi không phục hồi được

`recovery_locked=true` trong `/health` — `POST /replica/add_block` trả 503 cho đến khi `recover` hoặc đồng bị leader thành công (`replaced`).

