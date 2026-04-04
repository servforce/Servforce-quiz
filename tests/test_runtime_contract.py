from __future__ import annotations

from pathlib import Path

import pytest

import backend.md_quiz.config as settings_module
import backend.md_quiz.services.runtime_bootstrap as runtime_bootstrap


def test_local_database_contract_is_consistent_across_docs_and_compose():
    readme = Path("README.md").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    expected = "postgresql+psycopg2://admin:pasword@127.0.0.1:5433/markdown_quiz"

    assert expected in readme
    assert expected in env_example
    assert "cp .env.example .env" in readme
    assert "POSTGRES_USER: admin" in compose
    assert "POSTGRES_PASSWORD: pasword" in compose
    assert "POSTGRES_DB: markdown_quiz" in compose


def test_load_settings_default_database_matches_documented_local_contract(monkeypatch):
    monkeypatch.setattr(settings_module, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = settings_module.load_environment_settings()

    assert settings.database_url == "postgresql://admin:pasword@127.0.0.1:5433/markdown_quiz"


def test_bootstrap_runtime_wraps_database_errors(monkeypatch):
    def _boom():
        raise RuntimeError("cannot connect to postgres")

    monkeypatch.setattr(runtime_bootstrap, "init_db", _boom)

    with pytest.raises(runtime_bootstrap.RuntimeBootstrapError, match="cannot connect to postgres"):
        runtime_bootstrap.bootstrap_runtime()
