"""Agendador: dispara a coleta periodicamente, sem intervenção humana.

Em produção na Railway há duas formas de rodar (escolha uma):

1. **Worker interno** (padrão): o APScheduler sobe junto com a API e dispara a
   coleta a cada `SCRAPE_INTERVAL_MINUTES`.
2. **Cron job da Railway**: defina `SCHEDULER_ENABLED=false` na API e crie um
   cron service executando `python -m app.run_coleta`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from .config import config
from .database import SessionLocal, engine
from .monitor import coletar_todos

logger = logging.getLogger(__name__)

ID_JOB = "coleta_periodica"
_scheduler: BackgroundScheduler | None = None


# Identificador arbitrário da trava; só precisa ser estável e não colidir com
# outro uso de advisory lock no mesmo banco.
CHAVE_TRAVA = 8274613


@contextmanager
def _trava_de_rodada() -> Iterator[bool]:
    """Garante uma rodada por vez, mesmo com vários processos da API no ar.

    O agendador vive dentro do processo web. Subindo para 2 workers, cada um
    sobe o seu — e a coleta acontece em duplicata: o dobro de requisições para as
    lojas e pontos repetidos no histórico. Nada disso levanta erro, então
    passaria despercebido.

    A trava consultiva do PostgreSQL resolve sem infraestrutura nova: quem pega,
    coleta; quem não pega, pula a rodada. No SQLite não há concorrência entre
    processos, então segue direto.
    """
    if not config.DATABASE_URL.startswith("postgresql"):
        yield True
        return

    conexao = engine.connect()
    try:
        obtida = bool(
            conexao.execute(
                text("SELECT pg_try_advisory_lock(:chave)"), {"chave": CHAVE_TRAVA}
            ).scalar()
        )
        try:
            yield obtida
        finally:
            if obtida:
                conexao.execute(
                    text("SELECT pg_advisory_unlock(:chave)"), {"chave": CHAVE_TRAVA}
                )
    finally:
        conexao.close()


def executar_rodada() -> None:
    """Alvo do job: abre a própria sessão, coleta tudo e fecha."""
    try:
        with _trava_de_rodada() as minha_vez:
            if not minha_vez:
                logger.info("Outra instância já está coletando; esta rodada foi pulada.")
                return

            db = SessionLocal()
            try:
                coletar_todos(db)
            finally:
                db.close()
    except Exception:  # um erro aqui não pode matar o agendador
        logger.exception("Erro inesperado durante a rodada agendada.")


def iniciar_agendador() -> BackgroundScheduler | None:
    global _scheduler

    if not config.SCHEDULER_ENABLED:
        logger.info("Agendador desativado (SCHEDULER_ENABLED=false).")
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
    _scheduler.add_job(
        executar_rodada,
        trigger=IntervalTrigger(minutes=config.SCRAPE_INTERVAL_MINUTES),
        id=ID_JOB,
        name="Coleta periódica de preços",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info(
        "Agendador ativo — coleta a cada %d minuto(s).", config.SCRAPE_INTERVAL_MINUTES
    )

    if config.COLETA_AO_INICIAR:
        logger.info("COLETA_AO_INICIAR=true — disparando uma rodada agora.")
        _scheduler.add_job(executar_rodada, id="coleta_inicial", name="Coleta inicial")

    return _scheduler


def parar_agendador() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Agendador finalizado.")
    _scheduler = None


def proxima_execucao() -> datetime | None:
    if _scheduler is None or not _scheduler.running:
        return None
    job = _scheduler.get_job(ID_JOB)
    return job.next_run_time if job else None


def esta_ativo() -> bool:
    return _scheduler is not None and _scheduler.running
