"""Entrypoint para o cron job da Railway: `python -m app.run_coleta`.

Executa uma única rodada de coleta em todos os produtos monitorados e sai.
Use quando preferir o cron gerenciado da plataforma em vez do worker interno
(nesse caso, defina `SCHEDULER_ENABLED=false` no serviço da API).
"""

from __future__ import annotations

import json
import logging
import sys

from .database import SessionLocal, criar_tabelas
from .monitor import coletar_todos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> int:
    criar_tabelas()
    db = SessionLocal()
    try:
        resumo = coletar_todos(db)
    finally:
        db.close()

    print(json.dumps(resumo.to_dict(), ensure_ascii=False, indent=2))
    # Sai com erro se *todas* as coletas falharam (havendo produtos), para o
    # cron da Railway marcar a execução como problemática.
    return 1 if resumo.total > 0 and resumo.sucessos == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
