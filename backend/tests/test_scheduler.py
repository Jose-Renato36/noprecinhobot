"""Testes da rodada que o agendador dispara."""

from app import scheduler


def test_rodada_chama_a_coleta(monkeypatch):
    chamou = []
    monkeypatch.setattr(scheduler, "coletar_todos", lambda db: chamou.append(True))

    scheduler.executar_rodada()
    assert chamou == [True]


def test_falha_na_coleta_nao_derruba_o_agendador(monkeypatch):
    """Uma exceção aqui mataria o job e o monitoramento pararia em silêncio."""

    def explodir(db):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(scheduler, "coletar_todos", explodir)

    scheduler.executar_rodada()  # não deve levantar
