"""Testes da trava que impede rodadas em duplicata.

O agendador vive dentro do processo web. Com mais de um worker, cada um sobe o
seu e a coleta acontece duas vezes: o dobro de requisições às lojas e pontos
repetidos no histórico. Nada disso levanta erro, então passaria despercebido.
"""

from contextlib import contextmanager

from app import scheduler


def test_sqlite_nao_usa_trava(monkeypatch):
    """Sem concorrência entre processos, a trava só atrapalharia."""
    monkeypatch.setattr(scheduler.config, "DATABASE_URL", "sqlite:///teste.db")
    with scheduler._trava_de_rodada() as minha_vez:
        assert minha_vez is True


def test_rodada_acontece_quando_a_trava_e_obtida(monkeypatch):
    chamou = []

    @contextmanager
    def trava_livre():
        yield True

    monkeypatch.setattr(scheduler, "_trava_de_rodada", trava_livre)
    monkeypatch.setattr(scheduler, "coletar_todos", lambda db: chamou.append(True))

    scheduler.executar_rodada()
    assert chamou == [True]


def test_rodada_e_pulada_quando_outra_instancia_esta_coletando(monkeypatch):
    chamou = []

    @contextmanager
    def trava_ocupada():
        yield False

    monkeypatch.setattr(scheduler, "_trava_de_rodada", trava_ocupada)
    monkeypatch.setattr(scheduler, "coletar_todos", lambda db: chamou.append(True))

    scheduler.executar_rodada()
    assert chamou == [], "coletou mesmo com outra instância segurando a trava"


def test_falha_na_coleta_nao_derruba_o_agendador(monkeypatch):
    """Uma exceção aqui mataria o job e o monitoramento pararia em silêncio."""

    @contextmanager
    def trava_livre():
        yield True

    def explodir(db):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(scheduler, "_trava_de_rodada", trava_livre)
    monkeypatch.setattr(scheduler, "coletar_todos", explodir)

    scheduler.executar_rodada()  # não deve levantar
