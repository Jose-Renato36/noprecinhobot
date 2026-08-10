"""Testes das regras de alerta, com banco em memória e scraper simulado."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Alerta, HistoricoPreco, Produto, StatusProduto
from app.scraper import ResultadoScrape, ScraperError


@pytest.fixture
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


@pytest.fixture
def produto(db):
    p = Produto(
        nome="Fone AirBeats",
        url="http://loja.test/p/fone",
        preco_alvo=Decimal("500.00"),
        preco_atual=Decimal("650.00"),
        preco_inicial=Decimal("650.00"),
        status=StatusProduto.AGUARDANDO,
    )
    db.add(p)
    db.commit()
    return p


def simular(monkeypatch, preco, **extras):
    """Troca o scraper de verdade por um que devolve o preço pedido."""
    def falso(_url, _dica=None):
        if preco is None:
            raise ScraperError("Loja fora do ar")
        return ResultadoScrape(
            nome="Fone AirBeats",
            preco=Decimal(str(preco)),
            imagem_url=None,
            loja="Loja",
            **extras,
        )

    monkeypatch.setattr("app.monitor.raspar_produto", falso)


def test_coleta_grava_historico_sem_alerta_acima_do_alvo(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(monkeypatch, 620)
    resultado = coletar_produto(db, produto)

    assert resultado.sucesso
    assert resultado.alerta_gerado is False
    assert produto.status == StatusProduto.AGUARDANDO
    assert produto.preco_atual == Decimal("620.00")
    assert db.scalar(select(HistoricoPreco).where(HistoricoPreco.produto_id == produto.id))


def test_alerta_dispara_ao_atingir_o_alvo(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(monkeypatch, 480)
    resultado = coletar_produto(db, produto)

    assert resultado.alerta_gerado is True
    assert produto.status == StatusProduto.ALVO_ATINGIDO
    alerta = db.scalar(select(Alerta))
    assert alerta.preco_disparo == Decimal("480.00")
    assert alerta.preco_alvo == Decimal("500.00")


def test_alerta_nao_repete_enquanto_continuar_abaixo(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(monkeypatch, 480)
    coletar_produto(db, produto)
    simular(monkeypatch, 470)
    segunda = coletar_produto(db, produto)

    assert segunda.alerta_gerado is False
    assert len(db.scalars(select(Alerta)).all()) == 1


def test_alerta_volta_a_disparar_depois_de_subir(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(monkeypatch, 480)
    coletar_produto(db, produto)
    simular(monkeypatch, 700)  # preço subiu: volta para aguardando
    coletar_produto(db, produto)
    assert produto.status == StatusProduto.AGUARDANDO

    simular(monkeypatch, 450)  # caiu de novo: novo alerta
    assert coletar_produto(db, produto).alerta_gerado is True
    assert len(db.scalars(select(Alerta)).all()) == 2


def test_produto_pausado_nao_e_coletado(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    produto.status = StatusProduto.PAUSADO
    db.commit()
    simular(monkeypatch, 100)

    resultado = coletar_produto(db, produto)
    assert resultado.sucesso is False
    assert produto.status == StatusProduto.PAUSADO
    assert db.scalar(select(HistoricoPreco)) is None


def test_pausado_e_coletado_quando_forcado(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    produto.status = StatusProduto.PAUSADO
    db.commit()
    simular(monkeypatch, 450)

    resultado = coletar_produto(db, produto, forcar=True)
    assert resultado.sucesso is True
    # Coleta forçada registra o preço, mas não tira o produto da pausa.
    assert produto.status == StatusProduto.PAUSADO


def test_falha_do_scraper_marca_erro_sem_derrubar_a_rodada(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(monkeypatch, None)
    resultado = coletar_produto(db, produto)

    assert resultado.sucesso is False
    assert produto.status == StatusProduto.ERRO
    assert produto.ultimo_erro == "Loja fora do ar"
    assert db.scalar(select(HistoricoPreco)) is None


# --------------------------------------------------------------------------- #
# Barreira contra extração errada
# --------------------------------------------------------------------------- #
def test_preco_de_parcela_e_recusado(db, produto, monkeypatch):
    """O erro clássico: o scraper leu "10x de R$ 65,00" e achou que era o preço.
    Sem esta barreira, o histórico seria corrompido e um alerta falso dispararia."""
    from app.monitor import coletar_produto

    simular(monkeypatch, 65)  # 1/10 do preço real de 650
    resultado = coletar_produto(db, produto)

    assert resultado.sucesso is False
    assert "destoa" in (resultado.erro or "")
    assert db.scalar(select(HistoricoPreco)) is None
    assert db.scalar(select(Alerta)) is None
    assert produto.preco_atual == Decimal("650.00")  # o preço bom foi preservado


def test_preco_absurdamente_alto_e_recusado(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(monkeypatch, 9999)  # pegou o preço de outro produto na página
    assert coletar_produto(db, produto).sucesso is False
    assert db.scalar(select(HistoricoPreco)) is None


def test_recusa_esquece_o_seletor_aprendido(db, produto, monkeypatch):
    """Se o caminho CSS aprendido passou a apontar para o lugar errado, ele precisa
    ser descartado — senão o scraper repetiria o mesmo erro para sempre."""
    from app.monitor import coletar_produto

    produto.seletor_preco = "div.antigo span.preco"
    db.commit()

    simular(monkeypatch, 65)
    coletar_produto(db, produto)
    assert produto.seletor_preco is None


def test_promocao_agressiva_dentro_do_limite_passa(db, produto, monkeypatch):
    """-50% é promoção de verdade e precisa passar. O corte é em 4x."""
    from app.monitor import coletar_produto

    simular(monkeypatch, 325)
    resultado = coletar_produto(db, produto)

    assert resultado.sucesso is True
    assert resultado.alerta_gerado is True
    assert produto.preco_atual == Decimal("325.00")


def test_primeira_coleta_nao_tem_com_o_que_comparar(db, monkeypatch):
    from app.monitor import coletar_produto

    novo = Produto(
        nome="Sem histórico",
        url="http://loja.test/p/novo",
        preco_alvo=Decimal("100.00"),
        status=StatusProduto.AGUARDANDO,
    )
    db.add(novo)
    db.commit()

    simular(monkeypatch, 5)
    assert coletar_produto(db, novo).sucesso is True


def test_memoria_do_scraper_e_gravada(db, produto, monkeypatch):
    from app.monitor import coletar_produto

    simular(
        monkeypatch, 620, fonte="json-ld", confianca=0.85, seletor="div.p > span.v", perfil="edge"
    )
    coletar_produto(db, produto)

    assert produto.fonte_preco == "json-ld"
    assert produto.seletor_preco == "div.p > span.v"
    assert produto.perfil_http == "edge"
    assert float(produto.confianca) == 0.85
