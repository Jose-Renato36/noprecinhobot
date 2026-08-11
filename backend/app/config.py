"""Configuração central do NoPrecinhoBot, lida de variáveis de ambiente."""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RAIZ_PROJETO = BASE_DIR.parent

load_dotenv(BASE_DIR / ".env")


def _bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "yes", "y", "sim", "on"}


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, "").strip())
    except ValueError:
        return padrao


def _segredo() -> str:
    """Chave de assinatura dos tokens.

    Sem SECRET_KEY definida, geramos uma aleatória: é seguro por padrão, mas
    reinicia todas as sessões a cada boot (e, com mais de uma instância, os
    tokens de uma não valem na outra). Em produção, defina a variável.
    """
    valor = os.getenv("SECRET_KEY")
    if valor and valor.strip():
        return valor.strip()
    logger.warning(
        "SECRET_KEY não definida — usando uma chave aleatória. Os logins serão "
        "perdidos a cada reinício. Defina SECRET_KEY em produção."
    )
    return secrets.token_urlsafe(48)


def _normalizar_database_url(url: str) -> str:
    """A Railway entrega `postgres://...`; o SQLAlchemy 2 espera um driver explícito."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    # Banco: PostgreSQL em produção (Railway), SQLite no desenvolvimento local.
    DATABASE_URL: str = _normalizar_database_url(
        os.getenv("DATABASE_URL") or f"sqlite:///{(BASE_DIR / 'noprecinho.db').as_posix()}"
    )

    # Agendador
    SCHEDULER_ENABLED: bool = _bool("SCHEDULER_ENABLED", True)
    SCRAPE_INTERVAL_MINUTES: int = _int("SCRAPE_INTERVAL_MINUTES", 360)  # 6 horas (spec)
    COLETA_AO_INICIAR: bool = _bool("COLETA_AO_INICIAR", False)

    # Scraper
    SCRAPER_TIMEOUT: int = _int("SCRAPER_TIMEOUT", 20)
    SCRAPER_DELAY_SEGUNDOS: float = float(os.getenv("SCRAPER_DELAY_SEGUNDOS", "1.0"))
    SCRAPER_TENTATIVAS: int = _int("SCRAPER_TENTATIVAS", 3)
    # Um preço que pula mais que este fator entre coletas quase sempre é erro de
    # extração (pegou a parcela, o frete ou um produto relacionado), não promoção.
    VARIACAO_MAXIMA_FATOR: float = float(os.getenv("VARIACAO_MAXIMA_FATOR", "4.0"))

    # Fallback de navegador headless (Playwright), para lojas que só preenchem o
    # preço depois de rodar JavaScript. `auto` = usa se estiver instalado, e
    # ignora em silêncio se não estiver. Aceita também `true` / `false`.
    NAVEGADOR_FALLBACK: str = (os.getenv("NAVEGADOR_FALLBACK") or "auto").strip().lower()
    NAVEGADOR_TIMEOUT_MS: int = _int("NAVEGADOR_TIMEOUT_MS", 45000)
    NAVEGADOR_ESPERA_PRECO_MS: int = _int("NAVEGADOR_ESPERA_PRECO_MS", 8000)

    # Notificação (Resend)
    RESEND_API_KEY: str | None = os.getenv("RESEND_API_KEY") or None
    RESEND_FROM: str = os.getenv("RESEND_FROM", "NoPrecinhoBot <onboarding@resend.dev>")
    EMAIL_DESTINO: str | None = os.getenv("EMAIL_DESTINO") or None

    # Autenticação
    SECRET_KEY: str = _segredo()
    JWT_EXPIRA_MINUTOS: int = _int("JWT_EXPIRA_MINUTOS", 60 * 24 * 7)  # 7 dias
    # Com registro fechado, ninguém cria conta pela API: as contas existentes
    # continuam entrando normalmente, mas /api/auth/registrar passa a recusar.
    REGISTRO_ABERTO: bool = _bool("REGISTRO_ABERTO", True)

    # API
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
        ).split(",")
        if o.strip()
    ]
    BASE_URL: str = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    # Loja de demonstração (páginas HTML reais servidas pela própria API)
    DEMO_STORE_ENABLED: bool = _bool("DEMO_STORE_ENABLED", True)

    # Frontend compilado (usado quando se faz deploy de tudo num serviço só)
    FRONTEND_DIST: Path = Path(
        os.getenv("FRONTEND_DIST", str(RAIZ_PROJETO / "frontend" / "dist"))
    )


@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
