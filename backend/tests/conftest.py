"""Configuração compartilhada dos testes."""

import pytest


@pytest.fixture(autouse=True)
def limitador_limpo():
    """Zera as proteções contra abuso antes de cada teste.

    Os limitadores são objetos de módulo — precisam ser, para o estado sobreviver
    entre requisições em produção. Em teste isso vaza de um caso para o outro: o
    sexto cadastro de uma suíte inteira levaria 429 e reprovaria um teste que não
    tem nada a ver com limite. Quem quer *testar* o limite (test_limitador.py)
    provoca as chamadas dentro do próprio teste.
    """
    from app import limitador

    for dependencia in (
        limitador.limite_login,
        limitador.limite_registro,
        limitador.limite_scraping,
    ):
        dependencia.janela._eventos.clear()

    limitador.trava_de_login._falhas.clear()
    limitador.trava_de_login._liberado_em.clear()

    yield
