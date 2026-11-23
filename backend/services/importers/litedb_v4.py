"""
纯 Python 只读 LiteDB v4 (FILE_VERSION=7) 二进制解析器。
严格遵循 mbdavid/LiteDB@v4.1.4 的 4096 字节页布局与 BSON 编码（含 .NET 混合端序 GUID、
ExtendPage 大文档跨页拼接与 DateTime 极值保护），用于安全读取 Playnite 10+ 的 *.db 文件。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from pathlib import Path
import struct
from typing import Any
import uuid

from backend.services.importers.base import ImporterError

logger = logging.getLogger("tsumugi.services.importers.litedb_v4")

PAGE_SIZE = 4096
PAGE_HEADER_SIZE = 25
PAGE_AVAILABLE_BYTES = PAGE_SIZE - PAGE_HEADER_SIZE
HEADER_INFO = b"** This is a LiteDB file **"
FILE_VERSION_V4 = 7
FILE_VERSION_V5 = 8
UINT32_MAX = 0xFFFFFFFF

PAGE_EMPTY = 0
PAGE_HEADER = 1
PAGE_COLLECTION = 2
PAGE_INDEX = 3
PAGE_DATA = 4
PAGE_EXTEND = 5

_DOTNET_DATETIME_MAX_MS = 253402300800000
_DOTNET_DATETIME_MIN_MS = -62135596800000


class _ByteReader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.buf = data
        self.pos = pos

    def remaining(self) -> int:
        return len(self.buf) - self.pos

    def skip(self, n: int) -> None:
        self.pos += n

    def read_bytes(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.buf):
            raise EOFError("LiteDB 数据读取越界")
        chunk = self.buf[self.pos : end]
        self.pos = end
        return chunk

    def read_byte(self) -> int:
        val = self.buf[self.pos]
        self.pos += 1
        return val

    def read_bool(self) -> bool:
        return self.read_byte() != 0

    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self.read_bytes(4))[0]

    def read_int64(self) -> int:
        return struct.unpack("<q", self.read_bytes(8))[0]

    def read_double(self) -> float:
        return struct.unpack("<d", self.read_bytes(8))[0]

    def read_decimal(self) -> float:
        lo, mid, hi, flags = struct.unpack("<IIIi", self.read_bytes(16))
        scale = (flags >> 16) & 0xFF
        negative = bool(flags & 0x80000000)
        mantissa = lo + (mid << 32) + (hi << 64)
        dec = Decimal(mantissa) / (Decimal(10) ** scale)
        if negative:
            dec = -dec
        return float(dec)

    def read_litedb_string(self) -> str:
        length = self.read_int32()
        if length <= 0:
            return ""
        return self.read_bytes(length).decode("utf-8", errors="replace")

    def read_bson_string(self) -> str:
        length = self.read_int32()
        if length <= 0:
            return ""
        raw = self.read_bytes(length - 1)
        self.skip(1)  # trailing NUL
        return raw.decode("utf-8", errors="replace")

    def read_cstring(self) -> str:
        nul = self.buf.find(b"\x00", self.pos)
        if nul == -1:
            raise EOFError("BSON CString 缺少终止符")
        raw = self.buf[self.pos : nul]
        self.pos = nul + 1
        return raw.decode("utf-8", errors="replace")


def _read_bson_document(reader: _ByteReader) -> dict[str, Any]:
    start = reader.pos
    length = reader.read_int32()
    if length < 5 or start + length > len(reader.buf):
        raise ValueError("无效的 BSON 文档长度")
    end = start + length - 1
    doc: dict[str, Any] = {}
    while reader.pos < end:
        key, val = _read_bson_element(reader)
        doc[key] = val
    reader.pos = start + length
    return doc


def _read_bson_array(reader: _ByteReader) -> list[Any]:
    start = reader.pos
    length = reader.read_int32()
    if length < 5 or start + length > len(reader.buf):
        raise ValueError("无效的 BSON 数组长度")
    end = start + length - 1
    arr: list[Any] = []
    while reader.pos < end:
        _, val = _read_bson_element(reader)
        arr.append(val)
    reader.pos = start + length
    return arr


def _read_bson_element(reader: _ByteReader) -> tuple[str, Any]:
    btype = reader.read_byte()
    name = reader.read_cstring()

    if btype == 0x01:  # Double
        return name, reader.read_double()
    if btype == 0x02:  # String
        return name, reader.read_bson_string()
    if btype == 0x03:  # Document
        return name, _read_bson_document(reader)
    if btype == 0x04:  # Array
        return name, _read_bson_array(reader)
    if btype == 0x05:  # Binary
        length = reader.read_int32()
        subtype = reader.read_byte()
        raw = reader.read_bytes(length)
        if subtype in (0x03, 0x04) and len(raw) == 16:
            return name, str(uuid.UUID(bytes_le=raw))
        return name, raw
    if btype == 0x07:  # ObjectId
        return name, reader.read_bytes(12).hex()
    if btype == 0x08:  # Boolean
        return name, reader.read_bool()
    if btype == 0x09:  # DateTime (ms since Unix epoch)
        ts_ms = reader.read_int64()
        if ts_ms >= _DOTNET_DATETIME_MAX_MS or ts_ms <= _DOTNET_DATETIME_MIN_MS:
            return name, None
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            return name, dt
        except (OverflowError, OSError, ValueError):
            return name, None
    if btype == 0x0A:  # Null
        return name, None
    if btype == 0x10:  # Int32
        return name, reader.read_int32()
    if btype == 0x12:  # Int64
        return name, reader.read_int64()
    if btype == 0x13:  # .NET Decimal (16 bytes)
        return name, reader.read_decimal()
    if btype in (0xFF, 0x7F):  # MinKey / MaxKey
        return name, None

    raise ValueError(f"不支持的 BSON 类型字节: 0x{btype:02x}")


def decode_bson_document(raw: bytes) -> dict[str, Any]:
    return _read_bson_document(_ByteReader(raw))


def _parse_page_header(page_bytes: bytes) -> tuple[int, int, int, int, int, int]:
    page_id, page_type, prev_id, next_id, item_count, free_bytes = struct.unpack_from(
        "<IBIIHH", page_bytes, 0
    )
    return page_id, page_type, prev_id, next_id, item_count, free_bytes


def _read_extend_chain(pages: list[bytes], start_page_id: int) -> bytes:
    chunks: list[bytes] = []
    visited: set[int] = set()
    curr = start_page_id
    while curr != UINT32_MAX and curr not in visited:
        if curr >= len(pages):
            break
        visited.add(curr)
        page_buf = pages[curr]
        _, page_type, _, next_id, item_count, _ = _parse_page_header(page_buf)
        if page_type != PAGE_EXTEND:
            break
        data_len = min(item_count, PAGE_AVAILABLE_BYTES)
        chunks.append(page_buf[PAGE_HEADER_SIZE : PAGE_HEADER_SIZE + data_len])
        curr = next_id
    return b"".join(chunks)


def _extract_collection_pk_addresses(
    pages: list[bytes],
    collection_page_id: int,
) -> list[tuple[int, int]] | None:
    """
    沿 CollectionPage 的主索引（Indexes[0]）level-0 双向链表收集所有活跃文档的 DataBlock 地址。
    若索引为空或结构不完整则返回 None，由调用方退回 DataPage 扫描模式。
    """
    if collection_page_id >= len(pages):
        return None
    col_buf = pages[collection_page_id]
    _, page_type, _, _, _, _ = _parse_page_header(col_buf)
    if page_type != PAGE_COLLECTION:
        return None

    reader = _ByteReader(col_buf, PAGE_HEADER_SIZE)
    try:
        _col_name = reader.read_litedb_string()
        _doc_count = reader.read_int64()
        _free_data_page = reader.read_uint32()

        # 读取第一个索引（PK _id 索引）
        _field = reader.read_litedb_string()
        _unique = reader.read_bool()
        head_page_id = reader.read_uint32()
        head_index = reader.read_uint16()
        tail_page_id = reader.read_uint32()
        tail_index = reader.read_uint16()
    except Exception:
        return None

    if head_page_id == UINT32_MAX:
        return None

    # 解析涉及到的 IndexPage 节点表（延迟按页解析）
    parsed_index_pages: dict[int, dict[int, tuple[tuple[int, int], tuple[int, int]]]] = {}

    def _get_index_page(pid: int) -> dict[int, tuple[tuple[int, int], tuple[int, int]]]:
        if pid in parsed_index_pages:
            return parsed_index_pages[pid]
        if pid >= len(pages):
            parsed_index_pages[pid] = {}
            return {}
        buf = pages[pid]
        _, ptype, _, _, icount, _ = _parse_page_header(buf)
        if ptype != PAGE_INDEX:
            parsed_index_pages[pid] = {}
            return {}
        r = _ByteReader(buf, PAGE_HEADER_SIZE)
        nodes: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {}
        try:
            for _ in range(icount):
                idx = r.read_uint16()
                levels = r.read_byte()
                _slot = r.read_byte()
                _prev_node_p, _prev_node_i = r.read_uint32(), r.read_uint16()
                _next_node_p, _next_node_i = r.read_uint32(), r.read_uint16()
                key_len = r.read_uint16()
                _bson_type = r.read_byte()
                r.skip(key_len)
                data_page_id = r.read_uint32()
                data_idx = r.read_uint16()
                next_lvl0 = (UINT32_MAX, 0)
                for lvl in range(levels):
                    _p_pid, _p_idx = r.read_uint32(), r.read_uint16()
                    n_pid, n_idx = r.read_uint32(), r.read_uint16()
                    if lvl == 0:
                        next_lvl0 = (n_pid, n_idx)
                nodes[idx] = ((data_page_id, data_idx), next_lvl0)
        except Exception:
            parsed_index_pages[pid] = {}
            return {}
        parsed_index_pages[pid] = nodes
        return nodes

    addresses: list[tuple[int, int]] = []
    visited: set[tuple[int, int]] = set()
    curr = (head_page_id, head_index)
    tail = (tail_page_id, tail_index)

    while curr[0] != UINT32_MAX and curr not in visited:
        visited.add(curr)
        nodes = _get_index_page(curr[0])
        entry = nodes.get(curr[1])
        if entry is None:
            return None
        data_addr, next_addr = entry
        if curr != (head_page_id, head_index) and curr != tail:
            if data_addr[0] != UINT32_MAX:
                addresses.append(data_addr)
        if curr == tail:
            break
        curr = next_addr

    return addresses


def read_litedb_v4_documents(
    db_path: Path | str,
    collection: str | None = None,
) -> list[dict[str, Any]]:
    """
    只读解析 LiteDB v4 (.db) 文件，返回指定集合（或全部数据页）的 BSON 文档列表。
    """
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"LiteDB 文件不存在: {path}")

    raw_bytes = path.read_bytes()
    if len(raw_bytes) < PAGE_SIZE:
        raise ImporterError(f"文件 {path.name} 体积过小，不是有效的 LiteDB v4 数据库")

    page_count = len(raw_bytes) // PAGE_SIZE
    pages = [raw_bytes[i * PAGE_SIZE : (i + 1) * PAGE_SIZE] for i in range(page_count)]

    # 校验 HeaderPage (Page 0)
    page_id, page_type, _, _, _, _ = _parse_page_header(pages[0])
    if page_id != 0 or page_type != PAGE_HEADER:
        raise ImporterError(f"文件 {path.name} 头部页无效，不是有效的 LiteDB v4 数据库")

    hdr = _ByteReader(pages[0], PAGE_HEADER_SIZE)
    magic = hdr.read_bytes(len(HEADER_INFO))
    file_version = hdr.read_byte()

    if magic != HEADER_INFO:
        raise ImporterError(f"文件 {path.name} 签名不匹配，不是有效的 LiteDB 数据库")
    if file_version == FILE_VERSION_V5:
        raise ImporterError(
            f"检测到 LiteDB v5 格式文件 ({path.name})，当前 Playnite 适配器支持 LiteDB v4 或 Playnite 9 JSON 目录"
        )
    if file_version != FILE_VERSION_V4:
        raise ImporterError(f"不支持的 LiteDB 文件版本: {file_version}")

    _change_id = hdr.read_uint16()
    _free_empty_page_id = hdr.read_uint32()
    _last_page_id = hdr.read_uint32()
    _user_version = hdr.read_uint16()
    password_hash = hdr.read_bytes(20)
    _salt = hdr.read_bytes(16)

    if any(b != 0 for b in password_hash):
        raise ImporterError(f"数据库 {path.name} 已启用密码加密，无法直接读取")

    col_count = hdr.read_byte()
    collections: dict[str, int] = {}
    for _ in range(col_count):
        cname = hdr.read_litedb_string()
        cpid = hdr.read_uint32()
        collections[cname] = cpid

    # 解析所有 DataPage 块：{(page_id, block_index): raw_bson_bytes}
    data_blocks: dict[tuple[int, int], bytes] = {}
    ordered_blocks: list[bytes] = []

    for pid, buf in enumerate(pages):
        _, ptype, _, _, icount, _ = _parse_page_header(buf)
        if ptype != PAGE_DATA or icount == 0:
            continue
        r = _ByteReader(buf, PAGE_HEADER_SIZE)
        for _ in range(icount):
            try:
                blk_idx = r.read_uint16()
                extend_pid = r.read_uint32()
                size = r.read_uint16()
                inline_data = r.read_bytes(size)
            except EOFError:
                break
            payload = (
                _read_extend_chain(pages, extend_pid)
                if extend_pid != UINT32_MAX
                else inline_data
            )
            if payload:
                data_blocks[(pid, blk_idx)] = payload
                ordered_blocks.append(payload)

    # 若存在多个集合且目标集合明确，优先沿 PK 索引精确提取该集合的活跃文档
    selected_payloads: list[bytes] | None = None
    target_col = collection
    if target_col is None and len(collections) > 1 and "items" in collections:
        target_col = "items"

    if target_col and target_col in collections:
        addrs = _extract_collection_pk_addresses(pages, collections[target_col])
        if addrs is not None:
            selected_payloads = [data_blocks[a] for a in addrs if a in data_blocks]

    payloads = selected_payloads if selected_payloads is not None else ordered_blocks

    docs: list[dict[str, Any]] = []
    for raw_doc in payloads:
        try:
            docs.append(decode_bson_document(raw_doc))
        except Exception as exc:
            logger.debug("Skipping malformed BSON block in %s: %s", path.name, exc)
    return docs


# ──────────────────── LiteDB v4 BSON 编码与最小文件构造（用于单元测试） ────────────────────


def encode_bson_document(doc: dict[str, Any]) -> bytes:
    """将 Python 字典编码为兼容 LiteDB v4 的 BSON 文档字节流（支持 .NET GUID 编码）"""
    body = bytearray()
    for key, value in doc.items():
        body.extend(_encode_bson_element(str(key), value))
    body.append(0x00)
    total_len = 4 + len(body)
    return struct.pack("<i", total_len) + bytes(body)


def _encode_bson_array(items: list[Any]) -> bytes:
    body = bytearray()
    for idx, item in enumerate(items):
        body.extend(_encode_bson_element(str(idx), item))
    body.append(0x00)
    total_len = 4 + len(body)
    return struct.pack("<i", total_len) + bytes(body)


def _encode_bson_element(key: str, value: Any) -> bytes:
    kbytes = key.encode("utf-8") + b"\x00"
    if value is None:
        return b"\x0a" + kbytes
    if isinstance(value, bool):
        return b"\x08" + kbytes + (b"\x01" if value else b"\x00")
    if isinstance(value, uuid.UUID):
        raw_guid = value.bytes_le
        return b"\x05" + kbytes + struct.pack("<iB", 16, 0x04) + raw_guid
    if isinstance(value, int):
        if -(2**31) <= value < 2**31:
            return b"\x10" + kbytes + struct.pack("<i", value)
        return b"\x12" + kbytes + struct.pack("<q", value)
    if isinstance(value, float):
        return b"\x01" + kbytes + struct.pack("<d", value)
    if isinstance(value, str):
        sbytes = value.encode("utf-8") + b"\x00"
        return b"\x02" + kbytes + struct.pack("<i", len(sbytes)) + sbytes
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        ms = int(round(dt.timestamp() * 1000))
        return b"\x09" + kbytes + struct.pack("<q", ms)
    if isinstance(value, bytes):
        return b"\x05" + kbytes + struct.pack("<iB", len(value), 0x00) + value
    if isinstance(value, dict):
        return b"\x03" + kbytes + encode_bson_document(value)
    if isinstance(value, (list, tuple)):
        return b"\x04" + kbytes + _encode_bson_array(list(value))
    # Fallback to string
    sbytes = str(value).encode("utf-8") + b"\x00"
    return b"\x02" + kbytes + struct.pack("<i", len(sbytes)) + sbytes


def write_litedb_v4_documents(
    db_path: Path | str,
    documents: list[dict[str, Any]],
    collection_name: str = "items",
) -> None:
    """
    写入标准 LiteDB v4 (FILE_VERSION=7) 二进制数据库文件（含 DataPage 与大文档 ExtendPage 拆页），
    供本地自动化单元测试构造真实的 Playnite *.db 样本。
    """
    pages: list[bytearray] = [bytearray(PAGE_SIZE)]  # Page 0: HeaderPage (稍后回填)

    # Page 1: CollectionPage（简化占位，指向无索引，使读取器走 DataPage 顺序读取）
    col_page = bytearray(PAGE_SIZE)
    struct.pack_into("<IBIIHH", col_page, 0, 1, PAGE_COLLECTION, UINT32_MAX, UINT32_MAX, 1, 0)
    cname_bytes = collection_name.encode("utf-8")
    pos = PAGE_HEADER_SIZE
    struct.pack_into("<i", col_page, pos, len(cname_bytes))
    pos += 4
    col_page[pos : pos + len(cname_bytes)] = cname_bytes
    pos += len(cname_bytes)
    struct.pack_into("<qI", col_page, pos, len(documents), UINT32_MAX)
    pages.append(col_page)

    # 分配 DataPage 与 ExtendPage
    curr_data_page_id = len(pages)
    curr_data_blocks: list[tuple[int, int, bytes]] = []  # (idx, extend_pid, inline_bytes)
    curr_used_bytes = 0
    next_block_idx = 0

    def _flush_data_page() -> None:
        nonlocal curr_data_page_id, curr_data_blocks, curr_used_bytes, next_block_idx
        if not curr_data_blocks:
            return
        buf = bytearray(PAGE_SIZE)
        free_bytes = max(0, PAGE_AVAILABLE_BYTES - curr_used_bytes)
        struct.pack_into(
            "<IBIIHH",
            buf,
            0,
            curr_data_page_id,
            PAGE_DATA,
            UINT32_MAX,
            UINT32_MAX,
            len(curr_data_blocks),
            free_bytes,
        )
        p = PAGE_HEADER_SIZE
        for bidx, ext_pid, inline in curr_data_blocks:
            struct.pack_into("<HIH", buf, p, bidx, ext_pid, len(inline))
            p += 8
            buf[p : p + len(inline)] = inline
            p += len(inline)
        # Ensure pages list has slot for curr_data_page_id
        while len(pages) <= curr_data_page_id:
            pages.append(bytearray(PAGE_SIZE))
        pages[curr_data_page_id] = buf
        curr_data_page_id = len(pages)
        curr_data_blocks = []
        curr_used_bytes = 0
        next_block_idx = 0

    for doc in documents:
        bson_bytes = encode_bson_document(doc)
        if len(bson_bytes) + 8 > PAGE_AVAILABLE_BYTES // 2:
            # 写入 ExtendPage 链以覆盖大文档跨页逻辑
            if curr_used_bytes + 8 > PAGE_AVAILABLE_BYTES:
                _flush_data_page()
            # Reserve slot for current data page first
            while len(pages) <= curr_data_page_id:
                pages.append(bytearray(PAGE_SIZE))
            first_ext_pid = len(pages)
            chunks = [
                bson_bytes[i : i + PAGE_AVAILABLE_BYTES]
                for i in range(0, len(bson_bytes), PAGE_AVAILABLE_BYTES)
            ]
            for c_idx, chunk in enumerate(chunks):
                ext_pid = first_ext_pid + c_idx
                prev_pid = ext_pid - 1 if c_idx > 0 else UINT32_MAX
                next_pid = ext_pid + 1 if c_idx + 1 < len(chunks) else UINT32_MAX
                ext_buf = bytearray(PAGE_SIZE)
                struct.pack_into(
                    "<IBIIHH",
                    ext_buf,
                    0,
                    ext_pid,
                    PAGE_EXTEND,
                    prev_pid,
                    next_pid,
                    len(chunk),
                    PAGE_AVAILABLE_BYTES - len(chunk),
                )
                ext_buf[PAGE_HEADER_SIZE : PAGE_HEADER_SIZE + len(chunk)] = chunk
                pages.append(ext_buf)
            curr_data_blocks.append((next_block_idx, first_ext_pid, b""))
            curr_used_bytes += 8
            next_block_idx += 1
        else:
            if curr_used_bytes + 8 + len(bson_bytes) > PAGE_AVAILABLE_BYTES:
                _flush_data_page()
            curr_data_blocks.append((next_block_idx, UINT32_MAX, bson_bytes))
            curr_used_bytes += 8 + len(bson_bytes)
            next_block_idx += 1

    _flush_data_page()

    # 填充 Page 0 (HeaderPage)
    hdr = pages[0]
    struct.pack_into("<IBIIHH", hdr, 0, 0, PAGE_HEADER, UINT32_MAX, UINT32_MAX, 0, 0)
    p = PAGE_HEADER_SIZE
    hdr[p : p + len(HEADER_INFO)] = HEADER_INFO
    p += len(HEADER_INFO)
    hdr[p] = FILE_VERSION_V4
    p += 1
    struct.pack_into("<HIIH", hdr, p, 1, UINT32_MAX, len(pages) - 1, 0)
    p += 12
    p += 20  # zero password
    p += 16  # zero salt
    hdr[p] = 1  # 1 collection
    p += 1
    struct.pack_into("<i", hdr, p, len(cname_bytes))
    p += 4
    hdr[p : p + len(cname_bytes)] = cname_bytes
    p += len(cname_bytes)
    struct.pack_into("<I", hdr, p, 1)  # CollectionPage = 1

    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"".join(pages))
