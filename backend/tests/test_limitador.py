"""Testes das proteções contra abuso.

Cobrem as duas defesas separadamente (janela por IP e trava por conta) e depois
o comportamento pelas rotas, que é onde elas precisam realmente valer.
"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import limitador
from app.database import Base, get_db
from app.limitador import JanelaDeslizante, TravaDeLogin, ip_do_cliente
from app.main import app


# --------------------------------------------------------------------------- #
# Janela deslizante
# --------------------------------------------------------------------------- #
def test_libera_ate_o_maximo_e_bloqueia_depois():
    janela = JanelaDeslizante(maximo=3, janela_segundos=60)
    assert [janela.registrar("ip") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert janela.registrar("ip") > 0


def test_chaves_diferentes_nao_se_afetam():
    janela = JanelaDeslizante(maximo=1, janela_segundos=60)
    assert janela.registrar("ip-a") == 0.0
    assert janela.registrar("ip-b") == 0.0  # o limite da A não vale para a B


def test_vaga_reabre_quando_a_janela_passa():
    janela = JanelaDeslizante(maximo=2, janela_segundos=0.3)
    janela.registrar("ip")
    janela.registrar("ip")
    assert janela.registrar("ip") > 0
    time.sleep(0.35)
    assert janela.registrar("ip") == 0.0


def test_espera_informada_e_util():
    """A espera devolvida precisa ser o tempo real até a vaga abrir."""
    janela = JanelaDeslizante(maximo=1, janela_segundos=10)
    janela.registrar("ip")
    espera = janela.registrar("ip")
    assert 1 <= espera <= 10


def test_esquecer_zera_a_contagem():
    janela = JanelaDeslizante(maximo=1, janela_segundos=60)
    janela.registrar("ip")
    janela.esquecer("ip")
    assert janela.registrar("ip") == 0.0


# --------------------------------------------------------------------------- #
# Trava de login por conta
# --------------------------------------------------------------------------- #
def test_trava_so_fecha_apos_o_limite():
    trava = TravaDeLogin(maximo_falhas=3, bloqueio_base=60, bloqueio_teto=900)
    assert trava.registrar_falha("ana@x.com") == 0
    assert trava.registrar_falha("ana@x.com") == 0
    assert trava.registrar_falha("ana@x.com") == 60  # a terceira fecha
    assert trava.espera("ana@x.com") > 0


def test_bloqueio_dobra_a_cada_rodada():
    trava = TravaDeLogin(maximo_falhas=2, bloqueio_base=10, bloqueio_teto=900)
    trava.registrar_falha("ana@x.com")
    assert trava.registrar_falha("ana@x.com") == 10
    trava.registrar_falha("ana@x.com")
    assert trava.registrar_falha("ana@x.com") == 20
    trava.registrar_falha("ana@x.com")
    assert trava.registrar_falha("ana@x.com") == 40


def test_bloqueio_respeita_o_teto():
    trava = TravaDeLogin(maximo_falhas=1, bloqueio_base=10, bloqueio_teto=25)
    duracoes = [trava.registrar_falha("ana@x.com") for _ in range(6)]
    assert max(duracoes) == 25


def test_sucesso_limpa_o_historico_de_falhas():
    trava = TravaDeLogin(maximo_falhas=3, bloqueio_base=60, bloqueio_teto=900)
    trava.registrar_falha("ana@x.com")
    trava.registrar_falha("ana@x.com")
    trava.registrar_sucesso("ana@x.com")
    # Se não tivesse limpado, a próxima falha já fecharia a conta.
    assert trava.registrar_falha("ana@x.com") == 0


def test_contas_diferentes_nao_se_afetam():
    trava = TravaDeLogin(maximo_falhas=1, bloqueio_base=60, bloqueio_teto=900)
    trava.registrar_falha("ana@x.com")
    assert trava.espera("bob@x.com") == 0


def test_trava_expira_sozinha():
    trava = TravaDeLogin(maximo_falhas=1, bloqueio_base=0.3, bloqueio_teto=1)
    trava.registrar_falha("ana@x.com")
    assert trava.espera("ana@x.com") > 0
    time.sleep(0.35)
    assert trava.espera("ana@x.com") == 0


# --------------------------------------------------------------------------- #
# Identificação do IP atrás de proxy
# --------------------------------------------------------------------------- #
class PedidoFalso:
    def __init__(self, cabecalhos=None, host="10.0.0.1"):
        self.headers = cabecalhos or {}
        self.client = type("C", (), {"host": host})()


def test_sem_proxy_usa_o_ip_da_conexao(monkeypatch):
    monkeypatch.setattr("app.limitador.config.CONFIAR_PROXIES", 0)
    pedido = PedidoFalso({"x-forwarded-for": "1.2.3.4"})
    # Com CONFIAR_PROXIES=0 o cabeçalho é ignorado — senão qualquer um forjaria
    # o próprio IP e escaparia do limite.
    assert ip_do_cliente(pedido) == "10.0.0.1"


def test_com_um_proxy_pega_o_ultimo_salto(monkeypatch):
    monkeypatch.setattr("app.limitador.config.CONFIAR_PROXIES", 1)
    # O atacante forjou "1.2.3.4"; o proxy anexou o IP real no fim.
    pedido = PedidoFalso({"x-forwarded-for": "1.2.3.4, 200.1.1.1"})
    assert ip_do_cliente(pedido) == "200.1.1.1"


def test_cabecalho_ausente_cai_no_ip_da_conexao(monkeypatch):
    monkeypatch.setattr("app.limitador.config.CONFIAR_PROXIES", 1)
    assert ip_do_cliente(PedidoFalso()) == "10.0.0.1"


# --------------------------------------------------------------------------- #
# Pelas rotas
# --------------------------------------------------------------------------- #
@pytest.fixture
def cliente(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    app.dependency_overrides[get_db] = lambda: sessao

    # O estado dos limitadores é zerado pelo autouse em conftest.py.
    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    sessao.close()


def test_login_repetido_leva_429_com_retry_after(cliente):
    respostas = [
        cliente.post("/api/auth/login", json={"email": "ana@x.com", "senha": "errada"})
        for _ in range(limitador.config.LIMITE_LOGIN + 2)
    ]
    codigos = [r.status_code for r in respostas]

    assert 429 in codigos, f"nenhuma requisição foi barrada: {codigos}"
    barrada = next(r for r in respostas if r.status_code == 429)
    assert int(barrada.headers["Retry-After"]) >= 1


def test_conta_e_bloqueada_apos_senhas_erradas(cliente):
    cliente.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@x.com", "senha": "senha-forte-123"},
    )

    for _ in range(limitador.config.LOGIN_MAX_FALHAS):
        cliente.post("/api/auth/login", json={"email": "ana@x.com", "senha": "errada"})

    # Agora nem a senha correta entra: a conta está de castigo.
    resposta = cliente.post(
        "/api/auth/login", json={"email": "ana@x.com", "senha": "senha-forte-123"}
    )
    assert resposta.status_code == 429
    assert "bloqueada" in resposta.json()["detail"].lower()


def test_login_correto_nao_e_afetado_pela_trava(cliente):
    cliente.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@x.com", "senha": "senha-forte-123"},
    )
    for _ in range(3):
        resposta = cliente.post(
            "/api/auth/login", json={"email": "ana@x.com", "senha": "senha-forte-123"}
        )
        assert resposta.status_code == 200


def test_acerto_no_meio_das_falhas_zera_a_contagem(cliente):
    cliente.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@x.com", "senha": "senha-forte-123"},
    )

    for _ in range(limitador.config.LOGIN_MAX_FALHAS - 1):
        cliente.post("/api/auth/login", json={"email": "ana@x.com", "senha": "errada"})

    cliente.post("/api/auth/login", json={"email": "ana@x.com", "senha": "senha-forte-123"})

    # Sem a limpeza no sucesso, a falha seguinte fecharia a conta.
    cliente.post("/api/auth/login", json={"email": "ana@x.com", "senha": "errada"})
    resposta = cliente.post(
        "/api/auth/login", json={"email": "ana@x.com", "senha": "senha-forte-123"}
    )
    assert resposta.status_code == 200


def test_registro_em_massa_e_barrado(cliente):
    codigos = [
        cliente.post(
            "/api/auth/registrar",
            json={"nome": f"U{i}", "email": f"u{i}@x.com", "senha": "senha-forte-123"},
        ).status_code
        for i in range(limitador.config.LIMITE_REGISTRO + 2)
    ]
    assert 429 in codigos, f"nenhum cadastro foi barrado: {codigos}"


def test_limite_desligado_nao_barra_nada(cliente, monkeypatch):
    monkeypatch.setattr(limitador.config, "RATE_LIMIT_ENABLED", False)
    codigos = [
        cliente.post(
            "/api/auth/login", json={"email": "ana@x.com", "senha": "errada"}
        ).status_code
        for _ in range(limitador.config.LIMITE_LOGIN + 3)
    ]
    # A trava por conta ainda age (429), mas o limite por IP não deve ter entrado.
    assert all(c in (401, 429) for c in codigos)
