"""All tests are offline, regardless of the developer's shell credentials."""

import pytest


@pytest.fixture(autouse=True)
def offline_credentials(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "TEXT_MODEL_API_KEY", "TYPESAFE_API_KEY",
                 "OPENROUTER_API_KEY", "SYS2_API_KEY", "SYS2_PROVIDER", "SYS2_MODEL", "SYS2_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def anyio_backend():
    return "asyncio"
