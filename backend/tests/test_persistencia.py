"""Testes do alerta de dados não-persistentes.

Sem DATABASE_URL o sistema cai em SQLite dentro do container e funciona
perfeitamente — até o container ser recriado, quando some tudo. O problema desse
caminho é o silêncio: a falha não aparece quando é causada, e sim dias depois,
disfarçada de outra coisa ("os produtos sumiram", "a coleta quebrou").
"""

import pytest

from app import main


@pytest.fixture
def ambiente_limpo(monkeypatch):
    """Sem variáveis de plataforma, para cada teste controlar o próprio cenário."""
    for v in ("RAILWAY_ENVIRONMENT", "RENDER", "FLY_APP_NAME", "DYNO"):
        monkeypatch.delenv(v, raising=False)


def test_sqlite_publicado_e_denunciado(monkeypatch, ambiente_limpo, caplog):
    monkeypatch.setattr(main.config, "DATABASE_URL", "sqlite:///noprecinho.db")
    monkeypatch.setattr(main.config, "BASE_URL", "https://noprecinho.up.railway.app")

    with caplog.at_level("ERROR"):
        main._conferir_persistencia()

    assert "NÃO estão sendo salvos" in caplog.text
    assert "PostgreSQL" in caplog.text


def test_sqlite_local_nao_reclama(monkeypatch, ambiente_limpo, caplog):
    """Em desenvolvimento o SQLite é o padrão desejado — avisar seria ruído."""
    monkeypatch.setattr(main.config, "DATABASE_URL", "sqlite:///noprecinho.db")
    monkeypatch.setattr(main.config, "BASE_URL", "http://127.0.0.1:8000")

    with caplog.at_level("ERROR"):
        main._conferir_persistencia()

    assert caplog.text == ""


def test_postgres_publicado_nao_reclama(monkeypatch, ambiente_limpo, caplog):
    monkeypatch.setattr(main.config, "DATABASE_URL", "postgresql+psycopg://u:s@host/db")
    monkeypatch.setattr(main.config, "BASE_URL", "https://noprecinho.up.railway.app")

    with caplog.at_level("ERROR"):
        main._conferir_persistencia()

    assert caplog.text == ""


def test_variavel_da_plataforma_tambem_indica_producao(monkeypatch, ambiente_limpo, caplog):
    """Domínio ainda em http, mas rodando na Railway: continua sendo produção."""
    monkeypatch.setattr(main.config, "DATABASE_URL", "sqlite:///noprecinho.db")
    monkeypatch.setattr(main.config, "BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    with caplog.at_level("ERROR"):
        main._conferir_persistencia()

    assert "NÃO estão sendo salvos" in caplog.text


def test_health_expoe_o_diagnostico(monkeypatch, ambiente_limpo):
    monkeypatch.setattr(main.config, "DATABASE_URL", "sqlite:///noprecinho.db")
    monkeypatch.setattr(main.config, "BASE_URL", "https://noprecinho.up.railway.app")

    saude = main.health()
    assert saude["banco"] == "sqlite"
    assert saude["dados_persistentes"] is False


def test_health_ok_com_postgres(monkeypatch, ambiente_limpo):
    monkeypatch.setattr(main.config, "DATABASE_URL", "postgresql+psycopg://u:s@host/db")
    monkeypatch.setattr(main.config, "BASE_URL", "https://noprecinho.up.railway.app")

    saude = main.health()
    assert saude["banco"] == "postgresql"
    assert saude["dados_persistentes"] is True
