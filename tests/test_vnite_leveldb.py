from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import cramjam
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from backend.db.database import Base
from backend.db.models import Game
from backend.services import media_service
from backend.services.importers.executor import execute_external_import
from backend.services.importers.leveldb_reader import (
    COMP_NONE,
    COMP_SNAPPY,
    LEVELDB_LOG_BLOCK_SIZE,
    LEVELDB_TABLE_MAGIC,
    LOG_REC_FIRST,
    LOG_REC_FULL,
    LOG_REC_LAST,
    LOG_REC_MIDDLE,
    OP_DELETE,
    OP_PUT,
    encode_varint,
    parse_pouchdb_directory,
    read_leveldb_kv,
)
from backend.services.importers.vnite import VniteImporter


def _make_png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (120, 160)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_large_png_bytes(size: tuple[int, int] = (240, 240)) -> bytes:
    """生成 > 36KB 的真实 PNG，确保在 WAL 写入时跨 32KB 块触发 FIRST/MIDDLE/LAST 分片拼接"""
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = ((x * 7 + y * 13) % 256, (x * 19 + y * 3) % 256, (x * 5 + y * 29) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    raw = buf.getvalue()
    assert len(raw) > LEVELDB_LOG_BLOCK_SIZE + 4096, f"Expected >36KB PNG, got {len(raw)}"
    return raw


def _build_leveldb_block(entries: list[tuple[bytes, bytes]]) -> bytes:
    """按 LevelDB 前缀压缩规则编码 Data / Index Block"""
    out = bytearray()
    restarts = [0]
    prev_key = b""
    for idx, (key, val) in enumerate(entries):
        if idx > 0 and idx % 16 == 0:
            restarts.append(len(out))
            shared = 0
        else:
            shared = 0
            limit = min(len(prev_key), len(key))
            while shared < limit and prev_key[shared] == key[shared]:
                shared += 1
        delta = key[shared:]
        out.extend(encode_varint(shared))
        out.extend(encode_varint(len(delta)))
        out.extend(encode_varint(len(val)))
        out.extend(delta)
        out.extend(val)
        prev_key = key

    for off in restarts:
        out.extend(struct.pack("<I", off))
    out.extend(struct.pack("<I", len(restarts)))
    return bytes(out)


def _wrap_table_block(block: bytes, *, compress: bool = True) -> tuple[bytes, int]:
    if compress:
        payload = bytes(cramjam.snappy.compress_raw(block))
        comp_type = COMP_SNAPPY
    else:
        payload = block
        comp_type = COMP_NONE
    # 5B trailer: 1B compression_type + 4B crc placeholder
    return payload + struct.pack("<BI", comp_type, 0), len(payload)


def _build_leveldb_sstable(
    records: list[tuple[bytes, int, int, bytes]],
    *,
    compress: bool = True,
) -> bytes:
    """构造标准 LevelDB SSTable（.ldb），支持真实 Snappy 压缩与 48 字节标准 Footer"""
    # LevelDB InternalKey 排序：user_key 升序，同 key 按 seq 降序
    sorted_recs = sorted(records, key=lambda r: (r[0], -r[1]))
    internal_entries: list[tuple[bytes, bytes]] = []
    for user_key, seq, op_type, val in sorted_recs:
        trailer = (seq << 8) | (op_type & 0xFF)
        internal_entries.append((user_key + struct.pack("<Q", trailer), val))

    data_block_raw = _build_leveldb_block(internal_entries)
    data_chunk, data_size = _wrap_table_block(data_block_raw, compress=compress)

    buf = bytearray()
    data_offset = len(buf)
    buf.extend(data_chunk)

    # Metaindex block (empty)
    meta_raw = _build_leveldb_block([])
    meta_chunk, meta_size = _wrap_table_block(meta_raw, compress=False)
    meta_offset = len(buf)
    buf.extend(meta_chunk)

    # Index block pointing to our Data Block
    last_key = internal_entries[-1][0] if internal_entries else b""
    handle_bytes = encode_varint(data_offset) + encode_varint(data_size)
    index_raw = _build_leveldb_block([(last_key, handle_bytes)])
    index_chunk, index_size = _wrap_table_block(index_raw, compress=compress)
    index_offset = len(buf)
    buf.extend(index_chunk)

    # 48B Footer: metaindex_handle + index_handle + zero-padding to 40B + 8B magic
    handles = (
        encode_varint(meta_offset)
        + encode_varint(meta_size)
        + encode_varint(index_offset)
        + encode_varint(index_size)
    )
    footer = handles.ljust(40, b"\x00") + struct.pack("<Q", LEVELDB_TABLE_MAGIC)
    buf.extend(footer)
    return bytes(buf)


def _encode_write_batch(base_seq: int, ops: list[tuple[int, bytes, bytes]]) -> bytes:
    batch = bytearray(struct.pack("<QI", base_seq, len(ops)))
    for op_type, key, val in ops:
        batch.append(op_type & 0xFF)
        batch.extend(encode_varint(len(key)))
        batch.extend(key)
        if op_type == OP_PUT:
            batch.extend(encode_varint(len(val)))
            batch.extend(val)
    return bytes(batch)


def _build_leveldb_wal(batches: list[bytes]) -> bytes:
    """按 LevelDB 32KB 块规则封装 WAL (.log)，自动处理 FULL / FIRST / MIDDLE / LAST 分片与 0 填充"""
    out = bytearray()
    block_offset = 0

    for payload in batches:
        pos = 0
        first = True
        while pos < len(payload) or (first and len(payload) == 0):
            leftover = LEVELDB_LOG_BLOCK_SIZE - block_offset
            if leftover < 7:
                out.extend(b"\x00" * leftover)
                block_offset = 0
                leftover = LEVELDB_LOG_BLOCK_SIZE

            avail = leftover - 7
            remaining = len(payload) - pos
            frag_len = min(remaining, avail)
            frag = payload[pos : pos + frag_len]
            end = (pos + frag_len) >= len(payload)

            if first and end:
                rec_type = LOG_REC_FULL
            elif first:
                rec_type = LOG_REC_FIRST
            elif end:
                rec_type = LOG_REC_LAST
            else:
                rec_type = LOG_REC_MIDDLE

            out.extend(struct.pack("<IHB", 0, len(frag), rec_type))
            out.extend(frag)
            block_offset += 7 + len(frag)
            pos += frag_len
            first = False
            if block_offset == LEVELDB_LOG_BLOCK_SIZE:
                block_offset = 0

    return bytes(out)


class VniteLevelDBReaderTestCase(unittest.IsolatedAsyncioTestCase):
    """Vnite v3 LevelDB/PouchDB 只读直读与封面附件提取端到端测试"""

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmpdir.name)
        self.data_dir = self.tmp_dir / "tsumugi_data"
        self.assets_dir = self.data_dir / "assets"
        self.thumbs_dir = self.data_dir / "cache" / "thumbs"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.tmp_dir / "test_vnite_ldb.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.session_maker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self._patches = [
            patch.object(media_service, "DATA_DIR", self.data_dir),
            patch.object(media_service, "ASSETS_DIR", self.assets_dir),
            patch.object(media_service, "THUMBS_CACHE_DIR", self.thumbs_dir),
        ]
        for p in self._patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        await self.engine.dispose()
        self._tmpdir.cleanup()

    def _build_vnite_v3_database_fixture(self, db_root: Path) -> tuple[bytes, bytes]:
        """
        构造完整的 Vnite v3 PouchDB/LevelDB 目录 fixture：
        - database/game：Snappy 压缩 .ldb + 跨 32KB 块分片 .log + LOCK 文件
          * g_summer：rev 1 在 .ldb，winning rev 2 在 .log 更新时长与附件（封面在 .ldb，>36KB 背景图跨 WAL 块）
          * g_deleted_pouch：PouchDB document-store 标记已删除
          * g_deleted_ldb：.ldb Put 后被 .log LevelDB Delete 墓碑删除
        - database/game-local：Node.js sublevel-pouchdb UTF-8 \\xc3\\xbf 前缀，保存 g_summer 启动路径
        - database/config：非游戏配置子库（应自动忽略）
        """
        game_dir = db_root / "game"
        local_dir = db_root / "game-local"
        config_dir = db_root / "config"
        game_dir.mkdir(parents=True, exist_ok=True)
        local_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)

        # 模拟 Vnite 运行中存在的 LOCK 文件
        (game_dir / "LOCK").write_bytes(b"locked")
        (game_dir / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
        (local_dir / "LOCK").write_bytes(b"locked")
        (local_dir / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
        (config_dir / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")

        cover_png = _make_png_bytes((32, 130, 210), (140, 200))
        bg_png = _make_large_png_bytes((240, 240))

        # 1) database/game/.ldb (Snappy 压缩, 使用 !<sublevel>!<key> 格式)
        g1_rev1_doc = {
            "_id": "g_summer",
            "_rev": "1-oldrev",
            "metadata": {"name": "Summer Pockets (Old)"},
            "record": {"playTime": 1000000, "playStatus": "playing"},
        }
        g1_meta_v1 = {
            "id": "g_summer",
            "winningRev": "1-oldrev",
            "deleted": False,
            "rev_map": {"1-oldrev": 1},
            "rev_tree": [{"pos": 1, "ids": ["oldrev", {"status": "available"}, []]}],
        }

        g_del_pouch_doc = {
            "_id": "g_deleted_pouch",
            "_rev": "1-alive",
            "metadata": {"name": "Deleted In PouchDB"},
            "record": {"playTime": 60000},
        }
        g_del_pouch_meta = {
            "id": "g_deleted_pouch",
            "winningRev": "2-tombstone",
            "deleted": True,
            "rev_map": {"1-alive": 2, "2-tombstone": 3},
            "rev_tree": [
                {
                    "pos": 1,
                    "ids": [
                        "alive",
                        {"status": "available"},
                        [["tombstone", {"status": "available", "deleted": True}, []]],
                    ],
                }
            ],
        }

        g_del_ldb_doc = {
            "_id": "g_deleted_ldb",
            "_rev": "1-ldbdel",
            "metadata": {"name": "Deleted By LevelDB Tombstone"},
        }
        g_del_ldb_meta = {
            "id": "g_deleted_ldb",
            "winningRev": "1-ldbdel",
            "deleted": False,
            "rev_map": {"1-ldbdel": 4},
            "rev_tree": [{"pos": 1, "ids": ["ldbdel", {"status": "available"}, []]}],
        }

        ldb_records = [
            (b"!document-store!g_summer", 1, OP_PUT, json.dumps(g1_meta_v1).encode("utf-8")),
            (b"!by-sequence!0000000000000001", 2, OP_PUT, json.dumps(g1_rev1_doc).encode("utf-8")),
            (b"!document-store!g_deleted_pouch", 3, OP_PUT, json.dumps(g_del_pouch_meta).encode("utf-8")),
            (b"!by-sequence!0000000000000002", 4, OP_PUT, json.dumps(g_del_pouch_doc).encode("utf-8")),
            (b"!document-store!g_deleted_ldb", 5, OP_PUT, json.dumps(g_del_ldb_meta).encode("utf-8")),
            (b"!by-sequence!0000000000000004", 6, OP_PUT, json.dumps(g_del_ldb_doc).encode("utf-8")),
            (b"!attach-binary-store!md5-cover-summer==", 7, OP_PUT, cover_png),
        ]
        (game_dir / "000005.ldb").write_bytes(_build_leveldb_sstable(ldb_records, compress=True))

        # 2) database/game/.log (WAL：更新 g_summer 到 winningRev 2-winrev、写入 >36KB 跨块背景附件、Delete g_deleted_ldb)
        g1_rev2_doc = {
            "_id": "g_summer",
            "_rev": "2-winrev",
            "metadata": {
                "name": "Summer Pockets",
                "originalName": "サマーポケッツ",
                "releaseDate": "2018-06-29",
                "description": "<p>在濑户内海的鸟白岛度过的暑假。</p>",
                "developers": ["Key"],
                "publishers": ["Visual Arts"],
                "genres": ["视觉小说"],
                "tags": ["催泪", "夏日"],
                "vndbId": "v20424",
                "steamId": "897220",
                "relatedSites": [
                    {"label": "Bangumi", "url": "https://bgm.tv/subject/200763"},
                    {"label": "YMGal", "url": "https://www.ymgal.games/GA12345"},
                ],
            },
            "record": {
                "playTime": 5400000,  # 90 分钟（毫秒）
                "lastRunDate": "2026-10-01T10:30:00.000Z",
                "playStatus": "finished",
                "timers": [
                    {"start": "2026-10-01T09:00:00.000Z", "end": "2026-10-01T10:30:00.000Z"}
                ],
            },
            "_attachments": {
                "cover.png": {
                    "content_type": "image/png",
                    "digest": "md5-cover-summer==",
                    "stub": True,
                },
                "background.png": {
                    "content_type": "image/png",
                    "digest": "md5-bg-summer==",
                    "stub": True,
                },
            },
        }
        g1_meta_v2 = {
            "id": "g_summer",
            "winningRev": "2-winrev",
            "deleted": False,
            "rev_map": {"1-oldrev": 1, "2-winrev": 5},
            "rev_tree": [
                {
                    "pos": 1,
                    "ids": [
                        "oldrev",
                        {"status": "available"},
                        [["winrev", {"status": "available"}, []]],
                    ],
                }
            ],
        }

        wal_batches = [
            _encode_write_batch(
                20,
                [
                    (OP_PUT, b"!by-sequence!0000000000000005", json.dumps(g1_rev2_doc, ensure_ascii=False).encode("utf-8")),
                    (OP_PUT, b"!document-store!g_summer", json.dumps(g1_meta_v2).encode("utf-8")),
                    (OP_DELETE, b"!document-store!g_deleted_ldb", b""),
                    (OP_DELETE, b"!by-sequence!0000000000000004", b""),
                ],
            ),
            # 超过 32KB 的单条 WriteBatch：强制触发 WAL FIRST / MIDDLE / LAST 分片拼接
            _encode_write_batch(
                30,
                [
                    (OP_PUT, b"!attach-binary-store!md5-bg-summer==", bg_png),
                ],
            ),
        ]
        (game_dir / "000006.log").write_bytes(_build_leveldb_wal(wal_batches))

        # 3) database/game-local/.ldb (使用 Node.js sublevel-pouchdb UTF-8 \xc3\xbf 分隔符保存本地启动路径)
        sep = "\xff".encode("utf-8")  # b"\xc3\xbf"
        local_doc = {
            "_id": "g_summer",
            "_rev": "1-loc1",
            "path": {"gamePath": "D:\\Galgame\\SummerPockets\\SiglusEngine.exe"},
            "launcher": {
                "mode": "file",
                "fileConfig": {"path": "D:\\Galgame\\SummerPockets\\SiglusEngine.exe"},
            },
        }
        local_meta = {
            "id": "g_summer",
            "winningRev": "1-loc1",
            "deleted": False,
            "rev_map": {"1-loc1": 1},
        }
        local_ldb_records = [
            (sep + b"document-store" + sep + b"g_summer", 1, OP_PUT, json.dumps(local_meta).encode("utf-8")),
            (sep + b"by-sequence" + sep + b"0000000000000001", 2, OP_PUT, json.dumps(local_doc).encode("utf-8")),
        ]
        (local_dir / "000003.ldb").write_bytes(_build_leveldb_sstable(local_ldb_records, compress=True))

        # 4) database/config/.ldb (无关配置库，应自动忽略)
        cfg_records = [
            (b"!document-store!theme", 1, OP_PUT, json.dumps({"id": "theme", "winningRev": "1-a", "rev_map": {"1-a": 1}}).encode("utf-8")),
            (b"!by-sequence!0000000000000001", 2, OP_PUT, json.dumps({"_id": "theme", "dark": True}).encode("utf-8")),
        ]
        (config_dir / "000001.ldb").write_bytes(_build_leveldb_sstable(cfg_records, compress=True))

        return cover_png, bg_png

    async def test_vnite_leveldb_direct_scan_merge_attachments_and_execute(self) -> None:
        vnite_root = self.tmp_dir / "vnite"
        db_root = vnite_root / "app" / "database"
        self._build_vnite_v3_database_fixture(db_root)

        importer = VniteImporter()
        candidates = importer.scan(str(db_root))

        # 仅返回 1 条有效游戏：PouchDB 已删除文档与 LevelDB 墓碑删除文档均被正确剔除
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.external_id, "g_summer")
        self.assertEqual(c.name, "Summer Pockets")
        self.assertEqual(c.original_name, "サマーポケッツ")
        self.assertEqual(c.release_date, "2018-06-29")
        self.assertEqual(c.developers, ["Key"])
        self.assertEqual(c.publishers, ["Visual Arts"])
        self.assertEqual(c.playtime_seconds, 5400)
        self.assertEqual(c.play_status, "done")
        self.assertEqual(c.vndb_id, "v20424")
        self.assertEqual(c.steam_appid, "897220")
        self.assertEqual(c.bangumi_id, "200763")
        self.assertEqual(c.ymgal_id, "GA12345")
        self.assertEqual(c.executable_path, "D:\\Galgame\\SummerPockets\\SiglusEngine.exe")
        self.assertTrue(Path(c.cover_path).is_file(), f"Extracted cover missing: {c.cover_path}")
        self.assertTrue(Path(c.background_path).is_file(), f"Extracted background missing: {c.background_path}")

        # 端到端执行导入到 Tsumugi 数据库，验证封面/缩略图/背景均独立落盘
        async with self.session_maker() as db:
            summary = await execute_external_import(db, candidates, duplicate_strategy="skip")
            self.assertEqual(summary.imported, 1)
            self.assertEqual(len(summary.errors), 0)

            stmt = (
                select(Game)
                .where(Game.title == "Summer Pockets")
                .options(selectinload(Game.media), selectinload(Game.play_record))
            )
            saved = (await db.execute(stmt)).scalar_one()
            self.assertEqual(saved.play_record.total_seconds, 5400)
            self.assertEqual(saved.media.exe_path, "D:\\Galgame\\SummerPockets\\SiglusEngine.exe")
            self.assertEqual(saved.external_ids.get("vndb"), "v20424")
            self.assertEqual(saved.external_ids.get("ymgal"), "GA12345")
            self.assertTrue((self.data_dir / saved.media.cover_path).is_file())
            self.assertTrue((self.data_dir / saved.media.cover_thumb_path).is_file())
            self.assertTrue((self.data_dir / saved.media.hero_bg_path).is_file())

            # 删除原 Vnite 数据库目录后，Tsumugi 资产依然完全独立可用
            shutil.rmtree(vnite_root)
            self.assertTrue((self.data_dir / saved.media.cover_path).is_file())
            self.assertTrue((self.data_dir / saved.media.hero_bg_path).is_file())

    def test_vnite_zip_backup_with_leveldb_and_legacy_sublevel_fallback(self) -> None:
        # 1) 将完整 LevelDB 目录打包进 .zip 备份，验证 _scan_zip_file 自动解压直读
        src_db = self.tmp_dir / "zip_src_db"
        self._build_vnite_v3_database_fixture(src_db)
        zip_path = self.tmp_dir / "vnite_ldb_backup.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for file in src_db.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=f"database/{file.relative_to(src_db).as_posix()}")

        importer = VniteImporter()
        zip_cands = importer.scan(str(zip_path))
        self.assertEqual(len(zip_cands), 1)
        self.assertEqual(zip_cands[0].name, "Summer Pockets")
        self.assertEqual(zip_cands[0].executable_path, "D:\\Galgame\\SummerPockets\\SiglusEngine.exe")
        self.assertTrue(Path(zip_cands[0].cover_path).is_file())

        # 2) 验证旧版单字节 \xff<sublevel>\xff<key> 与无 document-store 降级直读（跳过 _deleted: true）
        flat_dir = self.tmp_dir / "flat_ldb"
        flat_dir.mkdir(parents=True, exist_ok=True)
        (flat_dir / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")

        flat_records = [
            (
                b"\xffgames\xffg_live",
                1,
                OP_PUT,
                json.dumps({"_id": "g_live", "name": "Clannad", "playTime": 3600}).encode("utf-8"),
            ),
            (
                b"\xffgames\xffg_removed",
                2,
                OP_PUT,
                json.dumps({"_id": "g_removed", "name": "Removed Game", "_deleted": True}).encode("utf-8"),
            ),
        ]
        (flat_dir / "000001.ldb").write_bytes(_build_leveldb_sstable(flat_records, compress=True))

        kv = read_leveldb_kv(flat_dir)
        self.assertEqual(len(kv), 2)
        parsed = parse_pouchdb_directory(flat_dir)
        self.assertFalse(parsed.is_pouchdb)
        self.assertEqual(list(parsed.documents.keys()), ["g_live"])

        flat_cands = importer.scan(str(flat_dir))
        self.assertEqual(len(flat_cands), 1)
        self.assertEqual(flat_cands[0].name, "Clannad")
        self.assertEqual(flat_cands[0].playtime_seconds, 3600)


if __name__ == "__main__":
    unittest.main()
