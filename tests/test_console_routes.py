import httpx
import pytest

from hyperagent import server


@pytest.fixture
def console_dir(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><body>HyperAgent console</body></html>")
    monkeypatch.setattr(server, "web_dist", tmp_path)
    return tmp_path


async def test_chat_deep_links_serve_the_console(console_dir):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
        for path in ("/c/c-abc-123", "/c/unknown-chat"):
            response = await client.get(path)
            assert response.status_code == 200
            assert "HyperAgent console" in response.text
            assert response.headers["content-type"].startswith("text/html")
        response = await client.head("/c/c-abc-123")
        assert response.status_code == 200
        assert response.content == b""


async def test_chat_fallback_does_not_swallow_other_routes(console_dir):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
        for path in ("/c/a/missing.js", "/api/missing", "/_next/missing.js"):
            response = await client.get(path)
            assert response.status_code == 404


async def test_chat_link_without_built_frontend_returns_404(console_dir):
    (console_dir / "index.html").unlink()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
        assert (await client.get("/c/c-abc-123")).status_code == 404
