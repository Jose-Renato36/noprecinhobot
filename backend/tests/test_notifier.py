"""Testes do desligamento do envio de e-mail.

O que importa aqui não é o e-mail — é a garantia de que desligá-lo não interfere
em nada mais: o alerta continua nascendo, sendo gravado e aparecendo no painel.
"""

from decimal import Decimal

import pytest

from app.notifier import enviar_alerta_email


@pytest.fixture
def sem_rede(monkeypatch):
    """Detona o teste se alguém tentar falar com a Resend de verdade."""
    chamadas = []

    def proibido(*args, **kwargs):
        chamadas.append(args)
        raise AssertionError("O código tentou enviar e-mail quando não devia.")

    monkeypatch.setattr("app.notifier.requests.post", proibido)
    return chamadas


def enviar():
    return enviar_alerta_email(
        destinatario="ana@teste.com",
        nome_produto="Fone AirBeats",
        url_produto="http://loja.test/p/fone",
        preco_atual=Decimal("400.00"),
        preco_alvo=Decimal("500.00"),
    )


def test_desligado_nao_envia_nem_com_chave(monkeypatch, sem_rede):
    """EMAIL_ENABLED=false vence a chave: é o desligamento explícito."""
    monkeypatch.setattr("app.notifier.config.EMAIL_ENABLED", False)
    monkeypatch.setattr("app.notifier.config.RESEND_API_KEY", "re_chave_de_teste")

    assert enviar() is False
    assert sem_rede == []


def test_ligado_sem_chave_tambem_nao_envia(monkeypatch, sem_rede):
    monkeypatch.setattr("app.notifier.config.EMAIL_ENABLED", True)
    monkeypatch.setattr("app.notifier.config.RESEND_API_KEY", None)

    assert enviar() is False
    assert sem_rede == []


def test_desligado_nao_impede_o_alerta_de_nascer(monkeypatch):
    """A garantia que interessa: sem e-mail, o monitoramento segue igual."""
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.models import Alerta, Produto, StatusProduto
    from app.monitor import coletar_produto
    from app.scraper import ResultadoScrape

    monkeypatch.setattr("app.notifier.config.EMAIL_ENABLED", False)

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    produto = Produto(
        nome="Fone AirBeats",
        url="http://loja.test/p/fone",
        preco_alvo=Decimal("500.00"),
        preco_atual=Decimal("650.00"),
        preco_inicial=Decimal("650.00"),
        status=StatusProduto.AGUARDANDO,
    )
    db.add(produto)
    db.commit()

    monkeypatch.setattr(
        "app.monitor.raspar_produto",
        lambda _url, _dica=None: ResultadoScrape(
            nome="Fone AirBeats", preco=Decimal("400.00"), imagem_url=None, loja="Loja"
        ),
    )

    resultado = coletar_produto(db, produto)

    assert resultado.alerta_gerado is True   # o alerta nasceu
    assert resultado.email_enviado is False  # só não saiu e-mail
    assert db.scalar(select(Alerta)) is not None  # e está gravado
    db.close()
