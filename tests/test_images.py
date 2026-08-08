"""images.py 封面缓存测试（ADR 0034 补）：扩展名识别 / 缓存写入 / 旧 .img 清理 / 失败原因"""
import hashlib
import os

import httpx

from app.images import (
    CoverDownloadError,
    _detect_image_ext,
    cache_external_image,
    download_and_cache_cover,
)

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 100
GIF = b"GIF89a" + b"z" * 100
WEBP = b"RIFF" + b"w" * 4 + b"WEBP" + b"v" * 100


def _resp(content, ct=None, url="https://x/cover"):
    headers = {"content-type": ct} if ct else {}
    return httpx.Response(200, headers=headers, content=content,
                          request=httpx.Request("GET", url))


class TestDetectImageExt:
    def test_content_type_wins(self):
        assert _detect_image_ext(_resp(JPEG, "image/jpeg")) == ".jpg"
        assert _detect_image_ext(_resp(PNG, "image/png")) == ".png"
        assert _detect_image_ext(_resp(GIF, "image/gif")) == ".gif"
        assert _detect_image_ext(_resp(WEBP, "image/webp")) == ".webp"

    def test_magic_bytes_when_no_content_type(self):
        assert _detect_image_ext(_resp(JPEG)) == ".jpg"
        assert _detect_image_ext(_resp(PNG)) == ".png"
        assert _detect_image_ext(_resp(GIF)) == ".gif"
        assert _detect_image_ext(_resp(WEBP)) == ".webp"

    def test_non_image_falls_back_to_url(self):
        assert _detect_image_ext(_resp(b"text", url="https://x/a.png")) == ".png"
        assert _detect_image_ext(_resp(b"text", url="https://x/a")) == ".img"


class TestDownloadCacheCover:
    def test_writes_correct_extension(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))
        monkeypatch.setattr("app.images._download", lambda url, proxy=None, timeout=None: _resp(PNG))
        path, msg = download_and_cache_cover("https://x/c1")
        assert path and path.endswith(".png")  # 不再写成 .img
        assert os.path.exists(path)
        assert msg.startswith("ok")

    def test_reuses_existing_correct_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))
        monkeypatch.setattr("app.images._download", lambda url, proxy=None, timeout=None: _resp(PNG))
        p1, _ = download_and_cache_cover("https://x/c2")

        def boom(url, proxy=None, timeout=None):
            raise CoverDownloadError("连接失败（网络不可达）")

        monkeypatch.setattr("app.images._download", boom)
        p2, msg = download_and_cache_cover("https://x/c2")
        assert p2 == p1  # 命中缓存，不再下载
        assert "已有正确缓存" in msg

    def test_stale_img_replaced_and_cleaned(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))
        base = hashlib.md5(b"https://x/c3").hexdigest()
        stale = os.path.join(str(tmp_path), base + ".img")  # 旧错误扩展名残留
        with open(stale, "wb") as f:
            f.write(JPEG)
        monkeypatch.setattr("app.images._download", lambda url, proxy=None, timeout=None: _resp(PNG))
        path, msg = download_and_cache_cover("https://x/c3")
        assert path.endswith(".png")
        assert os.path.exists(path)
        assert not os.path.exists(stale)  # 旧 .img 被清理

    def test_failure_returns_reason(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))

        def net_fail(url, proxy=None, timeout=None):
            raise CoverDownloadError("连接超时（网络不可达）")

        monkeypatch.setattr("app.images._download", net_fail)
        path, msg = download_and_cache_cover("https://x/c4")
        assert path is None
        assert "不可达" in msg

    def test_404_reason(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))

        def not_found(url, proxy=None, timeout=None):
            raise CoverDownloadError("图片不存在（404）")

        monkeypatch.setattr("app.images._download", not_found)
        path, msg = download_and_cache_cover("https://x/c5")
        assert path is None
        assert "404" in msg

    def test_non_image_content_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))
        monkeypatch.setattr("app.images._download",
                           lambda url, proxy=None, timeout=None: _resp(b"not an image", url="https://x/noext"))
        path, msg = download_and_cache_cover("https://x/noext")
        assert path is None
        assert "非图片内容" in msg

    def test_cache_external_image_wrapper(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.images.settings.thumbnails_dir", str(tmp_path))
        monkeypatch.setattr("app.images._download", lambda url, proxy=None, timeout=None: _resp(PNG))
        assert cache_external_image("https://x/c6").endswith(".png")
        assert cache_external_image(None) is None

