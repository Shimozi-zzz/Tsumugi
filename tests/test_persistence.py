"""声明式 Connector 配置持久化测试（Phase 4）"""
from app.connectors import persistence
from app.models import Source


class TestPersistence:
    def test_save_and_load(self, db):
        config = {
            "name": "my-api",
            "base_url": "https://api.example.com",
            "search_endpoint": "/search?q={query}",
            "field_map": {"title": "t", "external_id": "id"},
        }
        src = persistence.save_declarative_config(config, enabled=True)
        assert src.name == "my-api"
        assert src.type == "connector"
        assert src.enabled == 1

        configs = persistence.load_declarative_configs()
        assert len(configs) == 1
        assert configs[0]["name"] == "my-api"
        assert configs[0]["_enabled"] is True

    def test_save_overwrites_same_name(self, db):
        c1 = {"name": "x", "base_url": "http://a", "search_endpoint": "/s", "field_map": {"title": "t", "external_id": "i"}}
        c2 = {"name": "x", "base_url": "http://b", "search_endpoint": "/s", "field_map": {"title": "t", "external_id": "i"}}
        persistence.save_declarative_config(c1, enabled=True)
        persistence.save_declarative_config(c2, enabled=False)
        configs = persistence.load_declarative_configs()
        assert len(configs) == 1
        assert configs[0]["base_url"] == "http://b"
        assert configs[0]["_enabled"] is False

    def test_delete(self, db):
        config = {"name": "y", "base_url": "http://a", "search_endpoint": "/s", "field_map": {"title": "t", "external_id": "i"}}
        persistence.save_declarative_config(config, enabled=True)
        assert persistence.delete_declarative_config("y") is True
        assert persistence.delete_declarative_config("y") is False
        assert persistence.load_declarative_configs() == []

    def test_load_skips_bad_json(self, db):
        bad = Source(name="bad", type="connector", config_ref="{not json", enabled=1)
        db.add(bad)
        db.commit()
        assert persistence.load_declarative_configs() == []
