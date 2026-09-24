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
    reinicia todas as sessões a cada boot. Defina a variável no .env para o
    login sobreviver a reinícios.
    """
    valor = os.getenv("SECRET_KEY")
    if valor and valor.strip():
        return valor.strip()
    logger.warning(
        "SECRET_KEY não definida — usando uma chave aleatória. Os logins serão "
        "perdidos a cada reinício. Defina SECRET_KEY no .env."
    )
    return secrets.token_urlsafe(48)


class Config:
    # Banco: um arquivo SQLite em backend/noprecinho.db.
    DATABASE_URL: str = f"sqlite:///{(BASE_DIR / 'noprecinho.db').as_posix()}"

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

    # Autenticação
    SECRET_KEY: str = _segredo()
    JWT_EXPIRA_MINUTOS: int = _int("JWT_EXPIRA_MINUTOS", 60 * 12)  # 12 horas

    # O token viaja num cookie httpOnly — invisível ao JavaScript, ao contrário
    # de localStorage/sessionStorage, que um XSS lê à vontade.
    COOKIE_NOME: str = os.getenv("COOKIE_NOME", "noprecinho_sessao")
    # Cookie de sessão: sem data de expiração, o navegador o descarta ao fechar.
    # Com true, ele persiste por JWT_EXPIRA_MINUTOS.
    COOKIE_PERSISTENTE: bool = _bool("COOKIE_PERSISTENTE", False)
    # Secure exige HTTPS; em desenvolvimento (http://127.0.0.1) o navegador
    # descartaria o cookie. Por isso segue o esquema da BASE_URL.
    COOKIE_SEGURO: bool = _bool(
        "COOKIE_SEGURO", (os.getenv("BASE_URL", "")).lower().startswith("https")
    )
    # Strict é o mais restritivo e cabe aqui: nenhum e-mail nosso aponta de volta
    # para o painel, então não há navegação externa legítima para quebrar.
    COOKIE_SAMESITE: str = os.getenv("COOKIE_SAMESITE", "strict").strip().lower()
    # Com registro fechado, ninguém cria conta pela API: as contas existentes
    # continuam entrando normalmente, mas /api/auth/registrar passa a recusar.
    REGISTRO_ABERTO: bool = _bool("REGISTRO_ABERTO", True)

    # Proteção contra abuso
    RATE_LIMIT_ENABLED: bool = _bool("RATE_LIMIT_ENABLED", True)
    # Quantos proxies confiáveis existem à frente da API. Rodando localmente não
    # há nenhum, então fica 0: confiar no X-Forwarded-For sem proxy permitiria
    # forjar o IP e furar o limite.
    CONFIAR_PROXIES: int = _int("CONFIAR_PROXIES", 0)

    LIMITE_LOGIN: int = _int("LIMITE_LOGIN", 10)
    LIMITE_LOGIN_JANELA: int = _int("LIMITE_LOGIN_JANELA", 300)  # 5 min
    LIMITE_REGISTRO: int = _int("LIMITE_REGISTRO", 5)
    LIMITE_REGISTRO_JANELA: int = _int("LIMITE_REGISTRO_JANELA", 3600)  # 1 h
    LIMITE_SCRAPING: int = _int("LIMITE_SCRAPING", 20)
    LIMITE_SCRAPING_JANELA: int = _int("LIMITE_SCRAPING_JANELA", 60)

    # Trava por conta, contra ataque distribuído em que o limite por IP não pega.
    LOGIN_MAX_FALHAS: int = _int("LOGIN_MAX_FALHAS", 5)
    LOGIN_BLOQUEIO_SEGUNDOS: int = _int("LOGIN_BLOQUEIO_SEGUNDOS", 60)
    LOGIN_BLOQUEIO_TETO_SEGUNDOS: int = _int("LOGIN_BLOQUEIO_TETO_SEGUNDOS", 900)  # 15 min

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

    # Libera o scraper a alcançar endereços de rede interna. Fica desligado: o
    # usuário informa a URL e quem faz a requisição é o servidor, então sem essa
    # trava o sistema serve de ponte para a rede privada da hospedagem (SSRF).
    # Ligue apenas para desenvolver contra uma loja local que não seja a BASE_URL.
    PERMITIR_REDE_INTERNA: bool = _bool("PERMITIR_REDE_INTERNA", False)

    # Só libera a origem localhost no CORS quando a API não está em HTTPS.
    CORS_PERMITIR_LOCALHOST: bool = _bool(
        "CORS_PERMITIR_LOCALHOST",
        not (os.getenv("BASE_URL", "")).lower().startswith("https"),
    )

@lru_cache
def get_config() -> Config:
    return Config()


config = get_config()
