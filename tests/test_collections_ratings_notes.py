from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.database import Base, get_db, init_db
from backend.db.models import Game, GameMediaPath, PlayRecord
from backend.main import app


class SmoothLegacyMigrationTestCase(unittest.IsolatedAsyncioTestCase):
    """1. 验证老库启动时自动平滑建表、补齐评分/合集列，并将旧 collection_games 无损迁入 collection_items"""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tsumugi_legacy_mig_")
        self.db_path = Path(self._tmp.name) / "legacy.db"
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path.as_posix()}", future=True
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self._tmp.cleanup()

    async def test_legacy_sqlite_smooth_migration_preserves_data_and_is_idempotent(self) -> None:
        # 构造模拟老版本数据库（无 rating 列、无 collection 新列、无 collection_items/game_notes，仅含旧 collection_games）
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE games (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title VARCHAR(255) NOT NULL,
                        sub_title VARCHAR(255) DEFAULT '',
                        pinyin_initials VARCHAR(128) DEFAULT '',
                        developer VARCHAR(128) DEFAULT '',
                        publisher VARCHAR(128) DEFAULT '',
                        release_date VARCHAR(32) DEFAULT '',
                        synopsis TEXT DEFAULT '',
                        tags JSON DEFAULT '[]',
                        external_ids JSON DEFAULT '{}',
                        locked_fields JSON DEFAULT '[]',
                        status VARCHAR(20) DEFAULT 'todo',
                        edition VARCHAR(20) DEFAULT 'collector',
                        is_nsfw BOOLEAN DEFAULT 0,
                        source_platform VARCHAR(32) DEFAULT 'PC',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE collections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(64) NOT NULL,
                        sort_order INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE collection_games (
                        collection_id INTEGER NOT NULL,
                        game_id INTEGER NOT NULL,
                        PRIMARY KEY (collection_id, game_id)
                    )
                    """
                )
            )
            await conn.execute(text("INSERT INTO games (id, title, status) VALUES (1, 'White Album 2 IC', 'done')"))
            await conn.execute(text("INSERT INTO games (id, title, status) VALUES (2, 'White Album 2 CC', 'playing')"))
            await conn.execute(text("INSERT INTO collections (id, name, sort_order) VALUES (10, '白色相簿系列', 0)"))
            await conn.execute(text("INSERT INTO collection_games (collection_id, game_id) VALUES (10, 1)"))
            await conn.execute(text("INSERT INTO collection_games (collection_id, game_id) VALUES (10, 2)"))

        # 第一次执行平滑迁移
        applied_first = await init_db(self.engine)
        self.assertIn("games.rating_overall", applied_first)
        self.assertIn("games.rating_dimensions", applied_first)
        self.assertIn("games.short_review", applied_first)
        self.assertIn("collections.description", applied_first)
        self.assertIn("collections.collection_type", applied_first)
        self.assertIn("collections.updated_at", applied_first)
        self.assertTrue(any(item.startswith("collection_games->collection_items(2)") for item in applied_first))

        # 第二次执行迁移应幂等（不重复迁移、不报错）
        applied_second = await init_db(self.engine)
        self.assertEqual(applied_second, [])

        # 验证老数据完整保留且已平滑迁入 collection_items
        async with self.engine.connect() as conn:
            tables = {
                r[0]
                for r in (
                    await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
                ).fetchall()
            }
            self.assertIn("collection_items", tables)
            self.assertIn("game_notes", tables)
            self.assertNotIn("collection_games", tables)

            games_rows = (
                await conn.execute(
                    text("SELECT id, title, rating_overall, short_review FROM games ORDER BY id ASC")
                )
            ).fetchall()
            self.assertEqual(len(games_rows), 2)
            self.assertEqual(games_rows[0][1], "White Album 2 IC")
            self.assertIsNone(games_rows[0][2])
            self.assertEqual(games_rows[0][3], "")

            col_row = (
                await conn.execute(
                    text("SELECT id, name, description, collection_type, updated_at FROM collections WHERE id = 10")
                )
            ).fetchone()
            self.assertIsNotNone(col_row)
            assert col_row is not None
            self.assertEqual(col_row[1], "白色相簿系列")
            self.assertEqual(col_row[2], "")
            self.assertEqual(col_row[3], "series")
            self.assertIsNotNone(col_row[4])

            item_rows = (
                await conn.execute(
                    text(
                        "SELECT collection_id, game_id, position, relation_label "
                        "FROM collection_items ORDER BY position ASC"
                    )
                )
            ).fetchall()
            self.assertEqual(item_rows, [(10, 1, 0, ""), (10, 2, 1, "")])


class SeriesCollectionsRatingsAndNotesApiTestCase(unittest.IsolatedAsyncioTestCase):
    """2. 端到端校验系列合集排序/删除隔离、详情同系列条、多维评分自动均分、手记 CRUD 与 YAML Markdown 导出"""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tsumugi_col_notes_test_")
        self.db_path = Path(self._tmp.name) / "test.db"
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path.as_posix()}", future=True
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_maker = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async def _override_get_db():
            async with self.session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()
        self._tmp.cleanup()

    async def _seed_games(self) -> list[int]:
        async with self.session_maker() as db:
            g1 = Game(
                title="Summer Pockets",
                sub_title="サマーポケッツ",
                developer="Key",
                publisher="Visual Arts",
                release_date="2018-06-29",
                tags=["催泪", "日常"],
                status="done",
            )
            g1.media = GameMediaPath(cover_path="assets/1/cover.webp")
            g1.play_record = PlayRecord(total_seconds=153000)  # 42.5h

            g2 = Game(
                title="Summer Pockets REFLECTION BLUE",
                sub_title="サマーポケッツ リフレクションブルー",
                developer="Key",
                status="playing",
            )
            g2.media = GameMediaPath(cover_path="assets/2/cover.webp")
            g2.play_record = PlayRecord(total_seconds=36000)

            g3 = Game(
                title="Summer Pockets Short Stories",
                developer="Key",
                status="todo",
            )
            g3.media = GameMediaPath()
            g3.play_record = PlayRecord(total_seconds=0)

            db.add_all([g1, g2, g3])
            await db.commit()
            return [g1.id, g2.id, g3.id]

    async def test_collections_create_reorder_delete_and_game_detail_series(self) -> None:
        g1, g2, g3 = await self._seed_games()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. 创建系列合集并附带初始顺序与关系标签
            r_create = await client.post(
                "/api/collections",
                json={
                    "name": "鸟白岛系列",
                    "description": "按发售与补完顺序游玩",
                    "collection_type": "series",
                    "items": [
                        {"game_id": g1, "relation_label": "本篇"},
                        {"game_id": g2, "relation_label": "加强版"},
                    ],
                },
            )
            self.assertEqual(r_create.status_code, 200)
            col = r_create.json()
            col_id = col["id"]
            self.assertEqual(col["collection_type"], "series")
            self.assertEqual(col["description"], "按发售与补完顺序游玩")
            self.assertEqual(col["total_count"], 2)
            self.assertEqual(col["completed_count"], 1)
            self.assertEqual(col["playing_count"], 1)
            self.assertEqual([it["game_id"] for it in col["items"]], [g1, g2])
            self.assertEqual([it["relation_label"] for it in col["items"]], ["本篇", "加强版"])

            # 2. 快捷添加第三部作品
            r_add = await client.post(
                f"/api/collections/{col_id}/items",
                json={"game_id": g3, "relation_label": "外传"},
            )
            self.assertEqual(r_add.status_code, 200)
            self.assertEqual([it["game_id"] for it in r_add.json()["items"]], [g1, g2, g3])
            self.assertEqual([it["position"] for it in r_add.json()["items"]], [0, 1, 2])

            # 3. 原子化重排顺序与修改关系标签（直接传有序列表）
            r_reorder = await client.put(
                f"/api/collections/{col_id}/items",
                json=[
                    {"game_id": g3, "relation_label": "前传"},
                    {"game_id": g1, "relation_label": "本篇"},
                    {"game_id": g2, "relation_label": "FD"},
                ],
            )
            self.assertEqual(r_reorder.status_code, 200)
            reordered = r_reorder.json()
            self.assertEqual([it["game_id"] for it in reordered["items"]], [g3, g1, g2])
            self.assertEqual([it["position"] for it in reordered["items"]], [0, 1, 2])
            self.assertEqual([it["relation_label"] for it in reordered["items"]], ["前传", "本篇", "FD"])

            # 4. GET /api/games/{id} 详情响应必须直接附带同系列按 position 排列的成员摘要
            r_detail = await client.get(f"/api/games/{g1}", params={"record_active": "false"})
            self.assertEqual(r_detail.status_code, 200)
            detail = r_detail.json()
            self.assertEqual(len(detail["collections"]), 1)
            membership = detail["collections"][0]
            self.assertEqual(membership["name"], "鸟白岛系列")
            self.assertEqual(membership["relation_label"], "本篇")
            self.assertEqual(membership["position"], 1)
            self.assertEqual([it["game_id"] for it in membership["items"]], [g3, g1, g2])
            self.assertEqual(membership["completed_count"], 1)
            self.assertEqual(membership["total_count"], 3)

            # 5. 快捷移出单部作品并校验 position 自动紧凑重排
            r_rm_item = await client.delete(f"/api/collections/{col_id}/items/{g1}")
            self.assertEqual(r_rm_item.status_code, 200)
            after_rm = r_rm_item.json()
            self.assertEqual([it["game_id"] for it in after_rm["items"]], [g3, g2])
            self.assertEqual([it["position"] for it in after_rm["items"]], [0, 1])

            # 6. 删除合集绝不删除游戏本体
            r_del = await client.delete(f"/api/collections/{col_id}")
            self.assertEqual(r_del.status_code, 200)

            r_cols = await client.get("/api/collections")
            self.assertEqual(r_cols.json(), [])
            r_games = await client.get("/api/games")
            self.assertEqual(len(r_games.json()), 3)

    async def test_multidimensional_rating_auto_average_and_clear(self) -> None:
        g1, _, _ = await self._seed_games()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. 只填 4 个维度未填综合分 -> 自动计算均值并保留 1 位小数 (9.5+9.5+9.0+9.5)/4 = 9.375 -> 9.4
            r_rate = await client.put(
                f"/api/games/{g1}/rating",
                json={
                    "rating_dimensions": {
                        "story": 9.5,
                        "visual": 9.5,
                        "music": 9.0,
                        "atmosphere": 9.5,
                    },
                    "short_review": "只有炫目未曾忘却的盛夏物语。",
                },
            )
            self.assertEqual(r_rate.status_code, 200)
            body = r_rate.json()
            self.assertEqual(body["rating_overall"], 9.4)
            self.assertEqual(
                body["rating_dimensions"],
                {"story": 9.5, "visual": 9.5, "music": 9.0, "atmosphere": 9.5},
            )
            self.assertEqual(body["short_review"], "只有炫目未曾忘却的盛夏物语。")

            # 2. 手动覆盖综合分
            r_override = await client.put(
                f"/api/games/{g1}/rating",
                json={"rating_overall": 9.8},
            )
            self.assertEqual(r_override.status_code, 200)
            self.assertEqual(r_override.json()["rating_overall"], 9.8)
            self.assertEqual(r_override.json()["rating_dimensions"]["story"], 9.5)

            # 3. 非法维度或越界分值应被拒绝
            r_bad_dim = await client.put(
                f"/api/games/{g1}/rating",
                json={"rating_dimensions": {"invalid_dim": 8.0}},
            )
            self.assertEqual(r_bad_dim.status_code, 400)

            r_bad_val = await client.put(
                f"/api/games/{g1}/rating",
                json={"rating_dimensions": {"story": 11.0}},
            )
            self.assertEqual(r_bad_val.status_code, 400)

            # 4. 清空评分
            r_clear = await client.put(
                f"/api/games/{g1}/rating",
                json={"clear": True},
            )
            self.assertEqual(r_clear.status_code, 200)
            cleared = r_clear.json()
            self.assertIsNone(cleared["rating_overall"])
            self.assertIsNone(cleared["rating_dimensions"])
            self.assertEqual(cleared["short_review"], "")

    async def test_notes_crud_and_yaml_frontmatter_markdown_export(self) -> None:
        g1, _, _ = await self._seed_games()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 绑定系列合集与评分，验证导出整合元数据
            await client.post(
                "/api/collections",
                json={
                    "name": "Key 社夏日三部曲",
                    "items": [{"game_id": g1, "relation_label": "本篇"}],
                },
            )
            await client.put(
                f"/api/games/{g1}/rating",
                json={
                    "rating_dimensions": {
                        "story": 9.5,
                        "visual": 9.0,
                        "music": 9.5,
                        "atmosphere": 9.5,
                    },
                    "short_review": "鸟白岛永不褪色的蝉鸣。",
                },
            )

            # 创建作品总评与置顶角色手记
            r_n1 = await client.post(
                f"/api/games/{g1}/notes",
                json={
                    "note_type": "work",
                    "title": "通关总评",
                    "content_md": "## 结构亮点\n\n日常铺垫扎实，>!ALKA 线与 Pocket 线回收惊艳!<。",
                },
            )
            self.assertEqual(r_n1.status_code, 200)
            n1_id = r_n1.json()["id"]

            r_n2 = await client.post(
                f"/api/games/{g1}/notes",
                json={
                    "note_type": "character",
                    "title": "鸣濑白羽",
                    "content_md": "泳池边的初次相遇令人难忘。",
                    "is_pinned": True,
                },
            )
            self.assertEqual(r_n2.status_code, 200)
            n2_id = r_n2.json()["id"]

            # 列表查询：置顶优先，且支持按类型筛选
            r_list = await client.get(f"/api/games/{g1}/notes")
            self.assertEqual(r_list.status_code, 200)
            notes = r_list.json()
            self.assertEqual([n["id"] for n in notes], [n2_id, n1_id])

            r_char = await client.get(f"/api/games/{g1}/notes", params={"note_type": "character"})
            self.assertEqual(len(r_char.json()), 1)
            self.assertEqual(r_char.json()[0]["title"], "鸣濑白羽")

            # 更新手记
            r_patch = await client.patch(
                f"/api/games/{g1}/notes/{n2_id}",
                json={"content_md": "泳池边的初次相遇与夏日祭烟火同样难忘。"},
            )
            self.assertEqual(r_patch.status_code, 200)
            self.assertIn("夏日祭烟火", r_patch.json()["content_md"])

            # 验证详情接口 notes_count == 2
            r_game = await client.get(f"/api/games/{g1}", params={"record_active": "false"})
            self.assertEqual(r_game.json()["notes_count"], 2)

            # 导出完整 Markdown（带标准 YAML Frontmatter）
            r_exp = await client.get(f"/api/games/{g1}/notes/export")
            self.assertEqual(r_exp.status_code, 200)
            self.assertIn("text/markdown", r_exp.headers.get("content-type", ""))
            self.assertIn("attachment;", r_exp.headers.get("content-disposition", ""))
            md = r_exp.text
            self.assertTrue(md.startswith("---\n"))
            fm_end = md.index("\n---\n", 4)
            frontmatter = md[4:fm_end]
            self.assertIn('title: "Summer Pockets"', frontmatter)
            self.assertIn('developer: "Key"', frontmatter)
            self.assertIn("play_time_hours: 42.5", frontmatter)
            self.assertIn("rating_overall: 9.4", frontmatter)
            self.assertIn("story: 9.5", frontmatter)
            self.assertIn("visual: 9.0", frontmatter)
            self.assertIn("music: 9.5", frontmatter)
            self.assertIn("atmosphere: 9.5", frontmatter)
            self.assertIn('"Key 社夏日三部曲"', frontmatter)
            self.assertIn("鸟白岛永不褪色的蝉鸣。", md)
            self.assertIn("### [作品总评] 通关总评", md)
            self.assertIn("### [角色手记] 鸣濑白羽", md)
            self.assertIn("夏日祭烟火", md)

            # 按 note_id 仅导出单篇手记
            r_exp_single = await client.get(
                f"/api/games/{g1}/notes/export",
                params={"note_id": n2_id},
            )
            self.assertEqual(r_exp_single.status_code, 200)
            self.assertIn("### [角色手记] 鸣濑白羽", r_exp_single.text)
            self.assertNotIn("### [作品总评] 通关总评", r_exp_single.text)

            # 删除手记并校验数量更新
            r_del_note = await client.delete(f"/api/games/{g1}/notes/{n1_id}")
            self.assertEqual(r_del_note.status_code, 200)
            r_game_after = await client.get(f"/api/games/{g1}", params={"record_active": "false"})
            self.assertEqual(r_game_after.json()["notes_count"], 1)

    async def test_bangumi_sync_with_rating_comment_and_safe_omission(self) -> None:
        g1, _g2, g3 = await self._seed_games()
        sent_payloads: list[tuple[str, dict]] = []

        orig_post = httpx.AsyncClient.post

        async def _fake_bgm_post(self_client, url, **kwargs):
            if "api.bgm.tv" in str(url):
                sent_payloads.append((str(url), dict(kwargs.get("json") or {})))
                return httpx.Response(202, request=httpx.Request("POST", str(url)))
            return await orig_post(self_client, url, **kwargs)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 给 g1 设置 Bangumi ID、0.5 步进评分 8.5 与短评
            r_patch = await client.patch(f"/api/games/{g1}", json={"bangumi_id": "234157"})
            self.assertEqual(r_patch.status_code, 200)
            r_rate = await client.put(
                f"/api/games/{g1}/rating",
                json={"rating_overall": 8.5, "short_review": "鸟白岛的夏日记忆"},
            )
            self.assertEqual(r_rate.status_code, 200)

            r_patch_g3 = await client.patch(f"/api/games/{g3}", json={"bangumi_id": "1195"})
            self.assertEqual(r_patch_g3.status_code, 200)

            with (
                patch("backend.api.games.resolve_bangumi_token", return_value="bgm_token_test"),
                patch.object(httpx.AsyncClient, "post", new=_fake_bgm_post),
            ):
                # 1. 自动从本地评分四舍五入(8.5->9) + 同步短评 + 仅自己可见
                r_sync1 = await client.post(
                    f"/api/games/{g1}/sync/bangumi",
                    json={"private": True},
                )
                self.assertEqual(r_sync1.status_code, 200)
                body1 = r_sync1.json()
                self.assertEqual(body1["synced_rate"], 9)
                self.assertEqual(body1["synced_comment"], "鸟白岛的夏日记忆")
                self.assertTrue(body1["private"])
                self.assertEqual(
                    sent_payloads[-1][1],
                    {
                        "type": 2,
                        "rate": 9,
                        "comment": "鸟白岛的夏日记忆",
                        "private": True,
                    },
                )

                # 2. 显式关闭评分与评论同步时，仅传收藏状态 type
                r_sync2 = await client.post(
                    f"/api/games/{g1}/sync/bangumi",
                    json={"sync_rating": False, "sync_comment": False},
                )
                self.assertEqual(r_sync2.status_code, 200)
                self.assertEqual(sent_payloads[-1][1], {"type": 2})

                # 3. 本地未评分且无短评的作品（g3）默认同步时绝不发送 rate/comment 覆盖远端
                r_sync3 = await client.post(f"/api/games/{g3}/sync/bangumi", json={})
                self.assertEqual(r_sync3.status_code, 200)
                self.assertEqual(sent_payloads[-1][1], {"type": 1})


if __name__ == "__main__":
    unittest.main()
