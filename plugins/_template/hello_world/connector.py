"""Hello World 示例插件（可复制修改，详见 plugins/README.md）

一个最小可用的 Connector 插件：调用 Open Library 公开搜索 API，把结果映射为
SearchResult。复制本目录 + 改 manifest.json 的 name/base_url 和这里的实现即可。

要点：
- connector.py 必须暴露 build_connector() 工厂函数；
- 实现 search(query, **filters) -> list[SearchResult]（必选）；
- manifest.json 声明了 get_detail，所以还必须实现 get_detail()；
- name/manifest 会在加载时被 manifest.json 覆盖，代码里不用重复构造；
- 用绝对导入 `from app.connectors.base import ...` 访问框架提供的数据结构。
"""
from app.connectors.base import ItemDetail, SearchResult, http_get


class HelloWorldConnector:
    """实现 Connector Protocol 的 search/get_detail。"""

    name = ""          # 加载时被 manifest.json 的 name 覆盖
    manifest = None    # 同上
    proxy_url = None   # 出站代理（registry 注入；直连为 None）

    def search(self, query, **filters):
        if not query or not query.strip():
            return []
        data = http_get(
            "https://openlibrary.org/search.json",
            proxy=self.proxy_url,
            params={"q": query.strip(), "limit": 5},
        ).json()
        results = []
        for doc in data.get("docs", [])[:5]:
            title = doc.get("title")
            if not title:
                continue
            authors = doc.get("author_name") or []
            first_sentence = doc.get("first_sentence")
            results.append(SearchResult(
                source=self.name,
                title=title,
                external_id=str(doc.get("key", "").replace("/works/", "") or title),
                subtitle=authors[0] if authors else None,
                description=(first_sentence.get("text") if isinstance(first_sentence, dict) else first_sentence) or "",
                raw=doc,
            ))
        return results

    def get_detail(self, external_id):
        detail = http_get(
            f"https://openlibrary.org/works/{external_id}.json",
            proxy=self.proxy_url,
        ).json()
        desc = detail.get("description") or ""
        if isinstance(desc, dict):
            desc = desc.get("value") or ""
        return ItemDetail(
            source=self.name,
            title=detail.get("title", external_id),
            external_id=external_id,
            description=desc,
            metadata={"authors": detail.get("authors", [])},
        )


def build_connector():
    return HelloWorldConnector()
