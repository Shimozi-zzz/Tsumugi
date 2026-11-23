"""
纯 Python 只读 LevelDB + PouchDB 解析器（用于直读 Vnite v3 本地数据库目录）

核心能力：
1. 防锁快照拷贝：将目标 LevelDB 目录拷贝到临时目录（跳过 LOCK 文件），兼容源应用运行中只读解析；
2. 标准 SSTable（.ldb / .sst）解析：校验 48B Footer 魔数 0xdb4775248b80fb57、解码 index_handle、
   支持 Snappy（cramjam.snappy.decompress_raw）与未压缩 Data Block、前缀压缩条目与 InternalKey；
3. 标准 WAL（.log）解析：32KB 物理块分片拼接（FULL=1 / FIRST=2 / MIDDLE=3 / LAST=4，跳过 0 填充）与 WriteBatch 解码；
4. 多文件按最大 seq 合并最新存活键值（自动剔除 Delete 墓碑记录）；
5. PouchDB 还原：同时兼容 \\xff<sublevel>\\xff<key> 与 !<sublevel>!<key> 两种子库前缀，
   还原 document-store winning revision -> by-sequence JSON 文档与 attach-binary-store 二进制附件。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import shutil
import struct
import tempfile
from typing import Any, Iterator

import cramjam

logger = logging.getLogger("tsumugi.services.importers.leveldb_reader")

# LevelDB 常量
LEVELDB_TABLE_MAGIC = 0xDB4775248B80FB57
LEVELDB_FOOTER_SIZE = 48
LEVELDB_BLOCK_TRAILER_SIZE = 5
LEVELDB_LOG_BLOCK_SIZE = 32768
LEVELDB_LOG_HEADER_SIZE = 7

# InternalKey / WriteBatch ValueType
OP_DELETE = 0
OP_PUT = 1

# WAL RecordType
LOG_REC_ZERO = 0
LOG_REC_FULL = 1
LOG_REC_FIRST = 2
LOG_REC_MIDDLE = 3
LOG_REC_LAST = 4

# CompressionType
COMP_NONE = 0
COMP_SNAPPY = 1
COMP_ZSTD = 2

_LEVELDB_DATA_SUFFIXES = {".ldb", ".sst", ".log"}


@dataclass
class PouchDBParseResult:
    """单个 LevelDB / PouchDB 目录的只读解析结果"""

    db_dir: Path
    subdb_name: str
    is_pouchdb: bool = False
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    attachments_by_digest: dict[str, bytes] = field(default_factory=dict)
    attachment_refs: dict[str, list[str]] = field(default_factory=dict)
    raw_entry_count: int = 0
    sublevels: list[str] = field(default_factory=list)


# ──────────────────── 1. 底层编码工具 ────────────────────


def decode_varint(buf: bytes | memoryview, pos: int) -> tuple[int, int]:
    """解码无符号 LEB128 varint64，返回 (value, next_pos)"""
    result = 0
    shift = 0
    end = len(buf)
    while pos < end:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("Invalid varint64: exceeds 64 bits")
    raise ValueError("Truncated varint64")


def encode_varint(value: int) -> bytes:
    """编码无符号 LEB128 varint64（供单元测试与工具复用）"""
    if value < 0:
        raise ValueError("varint must be non-negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _decompress_block(raw_block: bytes, compression_type: int) -> bytes:
    if compression_type == COMP_NONE:
        return raw_block
    if compression_type == COMP_SNAPPY:
        return bytes(cramjam.snappy.decompress_raw(raw_block))
    if compression_type == COMP_ZSTD:
        return bytes(cramjam.zstd.decompress(raw_block))
    raise ValueError(f"Unsupported LevelDB block compression type: {compression_type}")


def _iter_block_entries(block: bytes) -> Iterator[tuple[bytes, bytes]]:
    """按 LevelDB Block 前缀压缩格式迭代 (key, value)"""
    if len(block) < 4:
        return
    num_restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    restarts_bytes = num_restarts * 4
    limit = len(block) - 4 - restarts_bytes
    if limit <= 0 or limit > len(block):
        return

    mv = memoryview(block)
    pos = 0
    prev_key = b""
    while pos < limit:
        try:
            shared, pos = decode_varint(mv, pos)
            non_shared, pos = decode_varint(mv, pos)
            val_len, pos = decode_varint(mv, pos)
        except ValueError:
            break
        if pos + non_shared + val_len > limit:
            break
        delta_key = block[pos : pos + non_shared]
        pos += non_shared
        val = block[pos : pos + val_len]
        pos += val_len
        if shared > len(prev_key):
            break
        key = prev_key[:shared] + delta_key
        prev_key = key
        yield key, val


def _read_table_block(data: bytes, offset: int, size: int) -> bytes:
    end = offset + size
    if offset < 0 or size < 0 or end + LEVELDB_BLOCK_TRAILER_SIZE > len(data):
        raise ValueError(f"Block handle out of bounds: offset={offset}, size={size}")
    raw_block = data[offset:end]
    compression_type = data[end]
    return _decompress_block(raw_block, compression_type)


# ──────────────────── 2. SSTable (.ldb / .sst) 与 WAL (.log) 解析 ────────────────────


def parse_sstable_bytes(data: bytes) -> Iterator[tuple[bytes, int, int, bytes]]:
    """
    解析单个 LevelDB SSTable（.ldb / .sst）字节流。
    依次产出 (user_key, seq, op_type, value)，其中 op_type: 1=Put, 0=Delete。
    """
    if len(data) < LEVELDB_FOOTER_SIZE:
        return

    footer = data[-LEVELDB_FOOTER_SIZE:]
    magic = struct.unpack_from("<Q", footer, 40)[0]
    if magic != LEVELDB_TABLE_MAGIC:
        return

    try:
        # Footer 前 40 字节依次存放 metaindex_handle 与 index_handle
        _meta_off, pos = decode_varint(footer, 0)
        _meta_sz, pos = decode_varint(footer, pos)
        index_off, pos = decode_varint(footer, pos)
        index_sz, _pos = decode_varint(footer, pos)
        index_block = _read_table_block(data, index_off, index_sz)
    except Exception as exc:
        logger.debug("Failed reading SSTable index block: %s", exc)
        return

    for _idx_key, handle_bytes in _iter_block_entries(index_block):
        try:
            blk_off, pos = decode_varint(handle_bytes, 0)
            blk_sz, _ = decode_varint(handle_bytes, pos)
            data_block = _read_table_block(data, blk_off, blk_sz)
        except Exception as exc:
            logger.debug("Skipping unreadable SSTable data block: %s", exc)
            continue

        for internal_key, value in _iter_block_entries(data_block):
            if len(internal_key) < 8:
                continue
            user_key = internal_key[:-8]
            trailer = struct.unpack_from("<Q", internal_key, len(internal_key) - 8)[0]
            op_type = trailer & 0xFF
            seq = trailer >> 8
            if op_type in (OP_DELETE, OP_PUT):
                yield user_key, seq, op_type, value


def _iter_wal_records(data: bytes) -> Iterator[bytes]:
    """按 32KB 物理块解析 LevelDB WAL (.log) 逻辑记录（支持 FULL / FIRST / MIDDLE / LAST 拼接）"""
    total = len(data)
    block_start = 0
    fragments: list[bytes] = []

    while block_start < total:
        block_end = min(block_start + LEVELDB_LOG_BLOCK_SIZE, total)
        pos = block_start

        while pos + LEVELDB_LOG_HEADER_SIZE <= block_end:
            _crc, length, rec_type = struct.unpack_from("<IHB", data, pos)
            if rec_type == LOG_REC_ZERO:
                # 0 填充表示当前 32KB 块剩余部分无效，跳到下一个 32KB 块
                break
            payload_start = pos + LEVELDB_LOG_HEADER_SIZE
            payload_end = payload_start + length
            if payload_end > block_end:
                # 损坏或截断的日志块：丢弃未完成分片并跳过当前块
                fragments.clear()
                break
            payload = data[payload_start:payload_end]
            pos = payload_end

            if rec_type == LOG_REC_FULL:
                fragments.clear()
                yield payload
            elif rec_type == LOG_REC_FIRST:
                fragments = [payload]
            elif rec_type == LOG_REC_MIDDLE:
                if fragments:
                    fragments.append(payload)
            elif rec_type == LOG_REC_LAST:
                if fragments:
                    fragments.append(payload)
                    yield b"".join(fragments)
                    fragments.clear()
            else:
                # 忽略未知/扩展记录类型
                fragments.clear()

        block_start += LEVELDB_LOG_BLOCK_SIZE


def parse_wal_bytes(data: bytes) -> Iterator[tuple[bytes, int, int, bytes]]:
    """
    解析单个 LevelDB WAL (.log) 字节流中的全部 WriteBatch。
    依次产出 (user_key, seq, op_type, value)。
    """
    for batch in _iter_wal_records(data):
        if len(batch) < 12:
            continue
        base_seq, count = struct.unpack_from("<QI", batch, 0)
        mv = memoryview(batch)
        pos = 12
        seq = base_seq

        for _ in range(count):
            if pos >= len(batch):
                break
            tag = batch[pos]
            pos += 1
            if tag == OP_PUT:
                try:
                    klen, pos = decode_varint(mv, pos)
                    if pos + klen > len(batch):
                        break
                    user_key = batch[pos : pos + klen]
                    pos += klen
                    vlen, pos = decode_varint(mv, pos)
                    if pos + vlen > len(batch):
                        break
                    val = batch[pos : pos + vlen]
                    pos += vlen
                except ValueError:
                    break
                yield user_key, seq, OP_PUT, val
                seq += 1
            elif tag == OP_DELETE:
                try:
                    klen, pos = decode_varint(mv, pos)
                    if pos + klen > len(batch):
                        break
                    user_key = batch[pos : pos + klen]
                    pos += klen
                except ValueError:
                    break
                yield user_key, seq, OP_DELETE, b""
                seq += 1
            else:
                break


# ──────────────────── 3. 快照拷贝与目录级键值读取 ────────────────────


def is_leveldb_directory(directory: Path) -> bool:
    """判断目录本身是否为一个 LevelDB 实例目录（直接包含 CURRENT、*.ldb、*.sst 或 *.log）"""
    if not directory.is_dir():
        return False
    try:
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            lname = entry.name.lower()
            if lname == "current" or lname.startswith("manifest-") or entry.suffix.lower() in _LEVELDB_DATA_SUFFIXES:
                return True
    except OSError:
        return False
    return False


def discover_leveldb_directories(root_dir: Path) -> list[Path]:
    """递归发现 root_dir 下全部 LevelDB 子目录（按相对路径去重排序）"""
    if not root_dir.is_dir():
        return []
    found: list[Path] = []
    seen: set[Path] = set()

    def _walk(cur: Path, depth: int = 0) -> None:
        if depth > 6:
            return
        try:
            resolved = cur.resolve()
        except OSError:
            return
        if resolved in seen:
            return
        if is_leveldb_directory(cur):
            seen.add(resolved)
            found.append(cur)
        try:
            children = sorted(cur.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for child in children:
            if child.is_dir() and not child.name.startswith("."):
                _walk(child, depth + 1)

    _walk(root_dir)
    return found


def _snapshot_leveldb_dir(db_dir: Path, dst_dir: Path) -> list[Path]:
    """将 LevelDB 目录中的数据文件以防锁方式拷贝到临时快照目录（跳过 LOCK 与非关键锁文件）"""
    copied: list[Path] = []
    try:
        entries = list(db_dir.iterdir())
    except OSError as exc:
        logger.warning("Cannot list LevelDB directory %s: %s", db_dir.name, exc)
        return copied

    for item in entries:
        if not item.is_file():
            continue
        lname = item.name.lower()
        if lname == "lock" or lname in {"log", "log.old"}:
            continue
        if item.suffix.lower() not in _LEVELDB_DATA_SUFFIXES:
            continue
        target = dst_dir / item.name
        try:
            shutil.copyfile(item, target)
            copied.append(target)
        except OSError as exc:
            # 容忍运行中 Vnite 瞬时占用个别非关键文件
            logger.debug("Skipping locked/unreadable file %s during snapshot: %s", item.name, exc)
    return copied


def read_leveldb_kv(db_dir: Path) -> dict[bytes, bytes]:
    """
    只读解析单个 LevelDB 目录，返回合并后所有最新存活的 {user_key: value}。
    同一 user_key 仅保留最大 seq 的记录，最新状态为 Delete 时剔除。
    """
    latest: dict[bytes, tuple[int, int, bytes]] = {}

    def _apply(user_key: bytes, seq: int, op_type: int, value: bytes) -> None:
        prev = latest.get(user_key)
        if prev is None or seq > prev[0] or (seq == prev[0] and op_type == OP_DELETE):
            latest[user_key] = (seq, op_type, value)

    with tempfile.TemporaryDirectory(prefix="tsumugi_ldb_snap_") as snap_root:
        copied = _snapshot_leveldb_dir(db_dir, Path(snap_root))
        for fp in copied:
            suffix = fp.suffix.lower()
            try:
                raw = fp.read_bytes()
            except OSError as exc:
                logger.debug("Skipping unreadable snapshot file %s: %s", fp.name, exc)
                continue
            if not raw:
                continue
            if suffix in (".ldb", ".sst"):
                for uk, seq, op, val in parse_sstable_bytes(raw):
                    _apply(uk, seq, op, val)
            elif suffix == ".log":
                for uk, seq, op, val in parse_wal_bytes(raw):
                    _apply(uk, seq, op, val)

    return {k: val for k, (_seq, op_type, val) in latest.items() if op_type == OP_PUT}


# ──────────────────── 4. PouchDB sublevel 解析与文档/附件还原 ────────────────────


def split_sublevel_key(raw_key: bytes) -> tuple[str | None, bytes]:
    """
    兼容常见的 PouchDB / Level sublevel 键前缀格式：
    - 旧版二进制 sublevel：\\xff<sublevel>\\xff<key>
    - Node.js sublevel-pouchdb UTF-8 编码：\\xc3\\xbf<sublevel>\\xc3\\xbf<key>
    - level v8+ / subleveldown：!<sublevel>!<key>
    """
    if len(raw_key) >= 5 and raw_key.startswith(b"\xc3\xbf"):
        sep = raw_key.find(b"\xc3\xbf", 2)
        if sep > 2:
            sub = raw_key[2:sep].decode("utf-8", errors="ignore").strip()
            return sub, raw_key[sep + 2 :]
    if len(raw_key) >= 3:
        first = raw_key[0]
        if first == 0xFF:
            sep = raw_key.find(b"\xff", 1)
            if sep > 1:
                sub = raw_key[1:sep].decode("utf-8", errors="ignore").strip()
                return sub, raw_key[sep + 1 :]
        elif first == 0x21:  # b'!'
            sep = raw_key.find(b"!", 1)
            if sep > 1:
                sub = raw_key[1:sep].decode("utf-8", errors="ignore").strip()
                return sub, raw_key[sep + 1 :]
    return None, raw_key


def _safe_json_loads(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        try:
            return json.loads(raw.decode("utf-8-sig", errors="strict"))
        except Exception:
            return None


def _collect_rev_tree_leaves(rev_tree: Any) -> list[tuple[int, str, bool]]:
    """
    遍历 PouchDB rev_tree 提取全部叶子版本 (pos, rev_hash, is_deleted)。
    结构示例：[{"pos": 1, "ids": ["hash1", {"status": "available"}, [["hash2", {"deleted": true}, []]]]}]
    """
    leaves: list[tuple[int, str, bool]] = []
    if not isinstance(rev_tree, list):
        return leaves

    def _walk_node(pos: int, node: Any) -> None:
        if not isinstance(node, list) or len(node) < 2:
            return
        rev_hash = str(node[0] or "").strip()
        opts = node[1] if isinstance(node[1], dict) else {}
        children = node[2] if len(node) > 2 and isinstance(node[2], list) else []
        if not children:
            is_deleted = bool(opts.get("deleted")) or opts.get("status") == "missing"
            if rev_hash:
                leaves.append((pos, rev_hash, is_deleted))
            return
        for child in children:
            _walk_node(pos + 1, child)

    for branch in rev_tree:
        if not isinstance(branch, dict):
            continue
        start_pos = int(branch.get("pos") or 1)
        ids_node = branch.get("ids")
        _walk_node(start_pos, ids_node)
    return leaves


def _resolve_winning_rev(meta: dict[str, Any]) -> tuple[str | None, bool]:
    """
    从 PouchDB document-store 元数据中确定 winning revision 及是否已删除。
    返回 (winning_rev, is_deleted)。
    """
    explicit_deleted = meta.get("deleted")
    winning_rev = str(meta.get("winningRev") or meta.get("winning_rev") or "").strip() or None

    leaves = _collect_rev_tree_leaves(meta.get("rev_tree"))
    if winning_rev:
        # 若 rev_tree 明确标记该 winning_rev 已删除，则视为删除
        if explicit_deleted is True:
            return winning_rev, True
        for pos, rhash, is_del in leaves:
            if f"{pos}-{rhash}" == winning_rev:
                return winning_rev, is_del
        return winning_rev, bool(explicit_deleted)

    if leaves:
        # CouchDB/PouchDB 规则：优先未删除叶子；同状态取 (pos, rev_hash) 最大者
        live_leaves = [lf for lf in leaves if not lf[2]]
        pool = live_leaves if live_leaves else leaves
        pool.sort(key=lambda item: (item[0], item[1]), reverse=True)
        pos, rhash, is_del = pool[0]
        return f"{pos}-{rhash}", is_del or bool(explicit_deleted)

    return None, bool(explicit_deleted)


def _decode_attachment_bytes(raw_val: bytes) -> bytes | None:
    """将 attach-binary-store 中的二进制值或 JSON/base64 包装还原为原始图片字节"""
    if not raw_val:
        return None

    # 1. 直接匹配常见图片文件头魔数
    if _looks_like_image_bytes(raw_val):
        return raw_val

    # 2. 兼容 Node Buffer JSON 序列化 {"type": "Buffer", "data": [...]} 或 JSON base64 字符串
    if raw_val[:1] in (b"{", b'"'):
        parsed = _safe_json_loads(raw_val)
        if isinstance(parsed, dict) and parsed.get("type") == "Buffer" and isinstance(parsed.get("data"), list):
            try:
                return bytes(int(x) & 0xFF for x in parsed["data"])
            except Exception:
                return None
        if isinstance(parsed, str):
            decoded = _try_decode_base64_image(parsed)
            if decoded:
                return decoded

    # 3. 兼容纯 ASCII base64 文本存储
    if len(raw_val) >= 16 and all(32 <= b <= 126 or b in (9, 10, 13) for b in raw_val[:64]):
        decoded = _try_decode_base64_image(raw_val.decode("ascii", errors="ignore"))
        if decoded:
            return decoded

    # 4. 其余视为原始二进制字节直接返回
    return raw_val


def _looks_like_image_bytes(data: bytes) -> bool:
    if len(data) < 8:
        return False
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    if data.startswith((b"GIF87a", b"GIF89a", b"BM")):
        return True
    return False


def _try_decode_base64_image(text: str) -> bytes | None:
    cleaned = text.strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1].strip()
    if not cleaned:
        return None
    try:
        decoded = base64.b64decode(cleaned, validate=False)
        if decoded and _looks_like_image_bytes(decoded):
            return decoded
    except Exception:
        pass
    return None


def sniff_image_extension(data: bytes, content_type: str = "", filename: str = "") -> str:
    """根据魔数、MIME 类型或附件名推断合法图片后缀"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"BM"):
        return ".bmp"

    ct = (content_type or "").lower()
    if "webp" in ct:
        return ".webp"
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if "bmp" in ct:
        return ".bmp"

    ext = Path(filename or "").suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return ext
    return ".png"


def parse_pouchdb_directory(db_dir: Path, *, subdb_name: str = "") -> PouchDBParseResult:
    """
    只读解析单个 PouchDB / LevelDB 目录，还原所有未删除的最新文档与二进制附件。
    - 若存在 document-store / by-sequence：严格按 winning revision -> seq 还原最新存活文档；
    - 若不存在 document-store：自动降级为直接解析全部存活 JSON 对象并按 _id 去重（跳过 _deleted: true）。
    """
    label = subdb_name or db_dir.name
    kv = read_leveldb_kv(db_dir)
    result = PouchDBParseResult(
        db_dir=db_dir,
        subdb_name=label,
        raw_entry_count=len(kv),
    )
    if not kv:
        return result

    sublevel_buckets: dict[str, dict[bytes, bytes]] = {}
    plain_entries: dict[bytes, bytes] = {}

    for raw_k, raw_v in kv.items():
        sub, inner_k = split_sublevel_key(raw_k)
        if sub:
            sublevel_buckets.setdefault(sub, {})[inner_k] = raw_v
        else:
            plain_entries[raw_k] = raw_v

    result.sublevels = sorted(sublevel_buckets.keys())

    # 1. 提取 attach-binary-store 与 attach 映射表（支持带/不带 md5- 前缀双向索引）
    attach_bin = sublevel_buckets.get("attach-binary-store", {})
    for raw_digest_key, raw_bytes in attach_bin.items():
        digest = raw_digest_key.decode("utf-8", errors="ignore").strip()
        if not digest:
            continue
        decoded = _decode_attachment_bytes(raw_bytes)
        if not decoded:
            continue
        result.attachments_by_digest[digest] = decoded
        if digest.startswith("md5-"):
            result.attachments_by_digest.setdefault(digest[4:], decoded)
        else:
            result.attachments_by_digest.setdefault(f"md5-{digest}", decoded)

    attach_meta = sublevel_buckets.get("attach", {})
    for raw_digest_key, raw_meta in attach_meta.items():
        digest = raw_digest_key.decode("utf-8", errors="ignore").strip()
        parsed = _safe_json_loads(raw_meta)
        if not digest or not isinstance(parsed, dict):
            continue
        refs = parsed.get("refs")
        if isinstance(refs, dict):
            doc_ids: list[str] = []
            for ref_key, active in refs.items():
                if not active:
                    continue
                ref_doc_id = str(ref_key).split("@", 1)[0].strip()
                if ref_doc_id and ref_doc_id not in doc_ids:
                    doc_ids.append(ref_doc_id)
            if doc_ids:
                result.attachment_refs[digest] = doc_ids

    # 2. PouchDB 标准 document-store + by-sequence 还原
    doc_store = sublevel_buckets.get("document-store", {})
    by_seq_store = sublevel_buckets.get("by-sequence", {})

    if doc_store:
        result.is_pouchdb = True

        # 为 by-sequence 建立文本键索引以及 (doc_id, rev) 兜底索引
        seq_docs: dict[str, dict[str, Any]] = {}
        by_id_rev: dict[tuple[str, str], dict[str, Any]] = {}
        latest_by_id: dict[str, tuple[str, dict[str, Any]]] = {}

        for raw_seq_k, raw_doc_v in by_seq_store.items():
            seq_key = raw_seq_k.decode("utf-8", errors="ignore").strip()
            parsed_doc = _safe_json_loads(raw_doc_v)
            if not isinstance(parsed_doc, dict):
                continue
            seq_docs[seq_key] = parsed_doc
            # 同时登记去前导零的纯数字键
            stripped_seq = seq_key.lstrip("0") or "0"
            seq_docs.setdefault(stripped_seq, parsed_doc)
            d_id = str(parsed_doc.get("_id") or "").strip()
            d_rev = str(parsed_doc.get("_rev") or "").strip()
            if d_id and d_rev:
                by_id_rev[(d_id, d_rev)] = parsed_doc
            if d_id:
                prev_pair = latest_by_id.get(d_id)
                if prev_pair is None or seq_key > prev_pair[0]:
                    latest_by_id[d_id] = (seq_key, parsed_doc)

        for raw_doc_id, raw_meta in doc_store.items():
            doc_id = raw_doc_id.decode("utf-8", errors="ignore").strip()
            if not doc_id or doc_id.startswith(("_design/", "_local/")):
                continue
            meta = _safe_json_loads(raw_meta)
            if not isinstance(meta, dict):
                continue

            winning_rev, is_deleted = _resolve_winning_rev(meta)
            if is_deleted:
                continue

            doc_body: dict[str, Any] | None = None
            rev_map = meta.get("rev_map") if isinstance(meta.get("rev_map"), dict) else {}

            if winning_rev and winning_rev in rev_map:
                seq_val = rev_map[winning_rev]
                cand_keys: list[str] = [str(seq_val).strip()]
                try:
                    seq_int = int(seq_val)
                    cand_keys.extend([f"{seq_int:016d}", str(seq_int)])
                except (TypeError, ValueError):
                    pass
                for ck in cand_keys:
                    if ck in seq_docs:
                        doc_body = seq_docs[ck]
                        break

            if doc_body is None and winning_rev:
                doc_body = by_id_rev.get((doc_id, winning_rev))

            if doc_body is None and doc_id in latest_by_id:
                doc_body = latest_by_id[doc_id][1]

            if not isinstance(doc_body, dict):
                continue
            if doc_body.get("_deleted") is True:
                continue

            merged_doc = dict(doc_body)
            merged_doc.setdefault("_id", doc_id)
            if winning_rev and "_rev" not in merged_doc:
                merged_doc["_rev"] = winning_rev
            result.documents[doc_id] = merged_doc

        return result

    # 3. 降级模式：无 document-store 时，解析全部存活 JSON 文档并按 _id 去重（跳过 _deleted: true）
    skip_sublevels = {"meta-store", "local-store", "attach-binary-store", "attach"}
    candidates_pool: list[tuple[str, bytes, bytes]] = []
    for sub, entries in sublevel_buckets.items():
        if sub in skip_sublevels:
            continue
        for inner_k, raw_v in entries.items():
            candidates_pool.append((sub, inner_k, raw_v))
    for raw_k, raw_v in plain_entries.items():
        candidates_pool.append(("", raw_k, raw_v))

    # 若存在 by-sequence，按 key 升序迭代使高序列号自然覆盖低序列号
    candidates_pool.sort(key=lambda item: (item[0], item[1]))

    for _sub, inner_k, raw_v in candidates_pool:
        parsed = _safe_json_loads(raw_v)
        if not isinstance(parsed, dict):
            continue
        doc_id = str(
            parsed.get("_id")
            or parsed.get("id")
            or inner_k.decode("utf-8", errors="ignore").strip()
        ).strip()
        if not doc_id or doc_id.startswith(("_design/", "_local/")):
            continue
        if parsed.get("_deleted") is True:
            result.documents.pop(doc_id, None)
            continue
        doc_copy = dict(parsed)
        doc_copy.setdefault("_id", doc_id)
        result.documents[doc_id] = doc_copy

    return result
