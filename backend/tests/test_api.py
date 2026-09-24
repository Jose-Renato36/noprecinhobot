"""Testes das rotas da API, com banco em memória e scraper simulado."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Alerta, HistoricoPreco, Produto
from app.scraper import ResultadoScrape, ScraperError


@pytest.fixture
def cliente(monkeypatch):
    # O TestClient atende as requisições em outra thread; sem StaticPool e sem
    # check_same_thread=False, o SQLite em memória recusa o acesso cruzado.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    app.dependency_overrides[get_db] = lambda: sessao

    def falso(url, _dica=None):
        if "quebrada" in url:
            raise ScraperError("A loja bloqueou o acesso do robô (HTTP 403).")
        return ResultadoScrape(
            nome="Fone AirBeats", preco=Decimal("650.00"), imagem_url=None, loja="Loja"
        )

    monkeypatch.setattr("app.main.raspar_produto", falso)

    # Sem `with`: o lifespan não roda, então o teste não cria o banco de verdade
    # nem liga o agendador.
    yield TestClient(app), sessao

    app.dependency_overrides.clear()
    sessao.close()


def cadastrar(c, url="http://loja.test/p/fone", alvo="500.00"):
    return c.post("/api/produtos", json={"url": url, "preco_alvo": alvo})


def test_cadastro_faz_a_primeira_coleta(cliente):
    c, sessao = cliente
    resposta = cadastrar(c)

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["nome"] == "Fone AirBeats"
    assert Decimal(corpo["preco_atual"]) == Decimal("650.00")
    assert corpo["status"] == "aguardando"
    assert sessao.query(HistoricoPreco).count() == 1


def test_mesma_url_nao_e_cadastrada_duas_vezes(cliente):
    c, _ = cliente
    cadastrar(c)
    assert cadastrar(c, alvo="400.00").status_code == 409


def test_link_que_a_loja_bloqueia_devolve_o_motivo(cliente):
    c, _ = cliente
    resposta = cadastrar(c, url="http://loja.test/quebrada")
    assert resposta.status_code == 422
    assert "403" in resposta.json()["detail"]


def test_url_invalida_e_recusada(cliente):
    c, _ = cliente
    assert cadastrar(c, url="nao-e-url").status_code == 422


def test_ja_abaixo_do_alvo_gera_alerta_no_cadastro(cliente):
    c, _ = cliente
    resposta = cadastrar(c, alvo="900.00")

    assert resposta.json()["status"] == "alvo_atingido"
    alertas = c.get("/api/alertas").json()
    assert len(alertas) == 1
    assert alertas[0]["lido"] is False


def test_mudar_o_alvo_recalcula_o_status(cliente):
    c, _ = cliente
    produto_id = cadastrar(c).json()["id"]

    resposta = c.patch(f"/api/produtos/{produto_id}", json={"preco_alvo": "700.00"})
    assert resposta.json()["status"] == "alvo_atingido"


def test_pausar_e_retomar(cliente):
    c, _ = cliente
    produto_id = cadastrar(c).json()["id"]

    assert c.post(f"/api/produtos/{produto_id}/pausar").json()["status"] == "pausado"
    assert c.post(f"/api/produtos/{produto_id}/retomar").json()["status"] == "aguardando"


def test_remover_leva_historico_e_alertas_junto(cliente):
    c, sessao = cliente
    produto_id = cadastrar(c, alvo="900.00").json()["id"]

    assert c.delete(f"/api/produtos/{produto_id}").status_code == 204
    assert sessao.get(Produto, produto_id) is None
    assert sessao.query(HistoricoPreco).count() == 0
    assert sessao.query(Alerta).count() == 0


def test_produto_inexistente_responde_404(cliente):
    c, _ = cliente
    assert c.get("/api/produtos/999").status_code == 404
    assert c.get("/api/produtos/999/historico").status_code == 404


def test_historico_traz_os_numeros_do_grafico(cliente):
    c, _ = cliente
    produto_id = cadastrar(c).json()["id"]

    historico = c.get(f"/api/produtos/{produto_id}/historico").json()
    assert len(historico["pontos"]) == 1
    assert Decimal(historico["menor_preco"]) == Decimal("650.00")
    assert Decimal(historico["preco_alvo"]) == Decimal("500.00")


def test_marcar_todos_os_alertas_como_lidos(cliente):
    c, _ = cliente
    cadastrar(c, alvo="900.00")

    assert c.post("/api/alertas/marcar-todos-lidos").json() == {"marcados": 1}
    assert c.get("/api/resumo").json()["alertas_nao_lidos"] == 0


def test_resumo_conta_os_produtos(cliente):
    c, _ = cliente
    cadastrar(c)
    cadastrar(c, url="http://loja.test/p/outro", alvo="900.00")

    resumo = c.get("/api/resumo").json()
    assert resumo["total_produtos"] == 2
    assert resumo["aguardando"] == 1
    assert resumo["alvo_atingido"] == 1
