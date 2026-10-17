import pytest


@pytest.fixture(autouse=True)
def no_model_credentials(monkeypatch):
    """Tests must never reach a paid provider."""
    for key in ("LLM_API_KEY", "OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
