"""Testes de autenticação e, principalmente, de **autorização**.

O login em si é a parte fácil. O que estes testes protegem é o escopo por dono:
antes dele, qualquer visitante lia e apagava o produto de qualquer pessoa só
trocando o id na URL. É o tipo de falha que nenhum teste de "funciona o login"
pegaria, então cada rota que recebe um id tem aqui um caso de acesso cruzado.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Produto, StatusProduto
from app.scraper import ResultadoScrape


@pytest.fixture
def cliente(monkeypatch):
    # O TestClient atende as requisições em outra thread; sem StaticPool e sem
    # check_same_thread=False, o SQLite em memória recusa o acesso cruzado.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)

    # Uma sessão só para o teste inteiro: com SQLite em memória, cada conexão
    # nova enxergaria um banco vazio.
    sessao = Sessao()
    app.dependency_overrides[get_db] = lambda: sessao

    # O cadastro de produto faz uma coleta de verdade; aqui ela é simulada.
    def falso(_url, _dica=None):
        return ResultadoScrape(
            nome="Fone AirBeats", preco=Decimal("650.00"), imagem_url=None, loja="Loja"
        )

    monkeypatch.setattr("app.main.raspar_produto", falso)

    with TestClient(app) as c:
        yield c, sessao

    app.dependency_overrides.clear()
    sessao.close()


def registrar(c, email, senha="senha-forte-123"):
    resposta = c.post(
        "/api/auth/registrar",
        json={"nome": email.split("@")[0], "email": email, "senha": senha},
    )
    assert resposta.status_code == 201, resposta.text

    # O TestClient guarda cookies como um navegador. Nos testes que simulam dois
    # usuários ao mesmo tempo, o cookie do último cadastro venceria o Bearer de
    # todos — o cookie tem precedência de propósito. Limpar aqui deixa o token
    # ser a única credencial, que é o que estes testes querem exercitar.
    c.cookies.clear()
    return resposta.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def criar_produto(c, token, url="http://loja.test/p/fone"):
    resposta = c.post(
        "/api/produtos", json={"url": url, "preco_alvo": "500.00"}, headers=auth(token)
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


# --------------------------------------------------------------------------- #
# Autenticação
# --------------------------------------------------------------------------- #
def test_registro_devolve_token_utilizavel(cliente):
    c, _ = cliente
    token = registrar(c, "ana@teste.com")
    resposta = c.get("/api/auth/eu", headers=auth(token))
    assert resposta.status_code == 200
    assert resposta.json()["email"] == "ana@teste.com"


def test_email_duplicado_e_recusado(cliente):
    c, _ = cliente
    registrar(c, "ana@teste.com")
    resposta = c.post(
        "/api/auth/registrar",
        json={"nome": "Outra", "email": "ana@teste.com", "senha": "outra-senha-123"},
    )
    assert resposta.status_code == 409


def test_email_e_case_insensitive(cliente):
    c, _ = cliente
    registrar(c, "ana@teste.com", senha="senha-forte-123")
    resposta = c.post(
        "/api/auth/login", json={"email": "ANA@TESTE.COM", "senha": "senha-forte-123"}
    )
    assert resposta.status_code == 200


def test_senha_errada_nao_entra(cliente):
    c, _ = cliente
    registrar(c, "ana@teste.com", senha="senha-forte-123")
    resposta = c.post("/api/auth/login", json={"email": "ana@teste.com", "senha": "errada-123"})
    assert resposta.status_code == 401


def test_login_nao_revela_se_o_email_existe(cliente):
    """Mensagens diferentes permitiriam descobrir quem tem conta no sistema."""
    c, _ = cliente
    registrar(c, "ana@teste.com", senha="senha-forte-123")

    inexistente = c.post("/api/auth/login", json={"email": "zzz@teste.com", "senha": "x"})
    senha_errada = c.post("/api/auth/login", json={"email": "ana@teste.com", "senha": "x"})

    assert inexistente.status_code == senha_errada.status_code == 401
    assert inexistente.json()["detail"] == senha_errada.json()["detail"]


def test_token_invalido_e_recusado(cliente):
    c, _ = cliente
    assert c.get("/api/auth/eu", headers=auth("nao-e-um-jwt")).status_code == 401


def test_senha_nao_aparece_em_nenhuma_resposta(cliente):
    c, _ = cliente
    token = registrar(c, "ana@teste.com")
    corpo = c.get("/api/auth/eu", headers=auth(token)).text
    assert "senha" not in corpo.lower()


# --------------------------------------------------------------------------- #
# Cookie de sessão
# --------------------------------------------------------------------------- #
def test_login_grava_cookie_httponly(cliente):
    """httpOnly é o motivo de existir do cookie: sem ele, um XSS lê o token."""
    from app.config import config

    c, _ = cliente
    c.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@teste.com", "senha": "senha-forte-123"},
    )
    resposta = c.post(
        "/api/auth/login", json={"email": "ana@teste.com", "senha": "senha-forte-123"}
    )

    bruto = resposta.headers["set-cookie"]
    assert config.COOKIE_NOME in bruto
    assert "httponly" in bruto.lower()
    assert "samesite=strict" in bruto.lower()


def test_cookie_e_de_sessao_por_padrao(cliente):
    """Sem Max-Age/Expires o navegador descarta o cookie ao fechar."""
    c, _ = cliente
    c.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@teste.com", "senha": "senha-forte-123"},
    )
    bruto = c.post(
        "/api/auth/login", json={"email": "ana@teste.com", "senha": "senha-forte-123"}
    ).headers["set-cookie"]

    assert "max-age" not in bruto.lower()
    assert "expires" not in bruto.lower()


def test_cookie_autentica_sem_cabecalho(cliente):
    """O painel não manda Authorization: quem sustenta a sessão é o cookie."""
    c, _ = cliente
    c.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@teste.com", "senha": "senha-forte-123"},
    )
    # O TestClient guarda os cookies entre chamadas, como um navegador.
    assert c.get("/api/auth/eu").status_code == 200
    assert c.get("/api/produtos").status_code == 200


def test_sair_derruba_a_sessao(cliente):
    c, _ = cliente
    c.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@teste.com", "senha": "senha-forte-123"},
    )
    assert c.get("/api/auth/eu").status_code == 200

    assert c.post("/api/auth/sair").status_code == 204
    assert c.get("/api/auth/eu").status_code == 401


def test_bearer_continua_valendo_para_clientes_sem_navegador(cliente):
    """O /docs e o curl não têm como usar cookie httpOnly."""
    c, _ = cliente
    token = registrar(c, "ana@teste.com")
    c.cookies.clear()  # simula um cliente que não guarda cookie

    assert c.get("/api/auth/eu", headers=auth(token)).status_code == 200


def test_cookie_tem_precedencia_sobre_bearer_invalido(cliente):
    """Cookie válido + cabeçalho lixo não pode derrubar a sessão do painel."""
    c, _ = cliente
    c.post(
        "/api/auth/registrar",
        json={"nome": "Ana", "email": "ana@teste.com", "senha": "senha-forte-123"},
    )
    assert c.get("/api/auth/eu", headers=auth("lixo")).status_code == 200


# --------------------------------------------------------------------------- #
# Rotas exigem autenticação
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "metodo,rota",
    [
        ("get", "/api/produtos"),
        ("get", "/api/resumo"),
        ("get", "/api/alertas"),
        ("get", "/api/lojas"),
        ("post", "/api/coletas/executar"),
        ("post", "/api/produtos"),
        ("post", "/api/previa"),
    ],
)
def test_rota_sem_token_responde_401(cliente, metodo, rota):
    c, _ = cliente
    extras = {"json": {}} if metodo == "post" else {}
    resposta = getattr(c, metodo)(rota, **extras)
    assert resposta.status_code == 401, f"{rota} respondeu {resposta.status_code}"


# --------------------------------------------------------------------------- #
# Escopo por dono — o coração da mudança
# --------------------------------------------------------------------------- #
def test_cada_um_ve_so_os_proprios_produtos(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    criar_produto(c, ana)

    assert len(c.get("/api/produtos", headers=auth(ana)).json()) == 1
    assert c.get("/api/produtos", headers=auth(bob)).json() == []


def test_nao_da_para_ler_produto_alheio(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    produto_id = criar_produto(c, ana)

    assert c.get(f"/api/produtos/{produto_id}", headers=auth(bob)).status_code == 404


def test_nao_da_para_apagar_produto_alheio(cliente):
    """O caso mais grave: antes do escopo, isto apagava de verdade."""
    c, sessao = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    produto_id = criar_produto(c, ana)

    assert c.delete(f"/api/produtos/{produto_id}", headers=auth(bob)).status_code == 404
    assert sessao.get(Produto, produto_id) is not None  # continua lá


def test_nao_da_para_editar_produto_alheio(cliente):
    c, sessao = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    produto_id = criar_produto(c, ana)

    resposta = c.patch(
        f"/api/produtos/{produto_id}", json={"preco_alvo": "1.00"}, headers=auth(bob)
    )
    assert resposta.status_code == 404
    sessao.expire_all()
    assert sessao.get(Produto, produto_id).preco_alvo == Decimal("500.00")


def test_nao_da_para_pausar_produto_alheio(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    produto_id = criar_produto(c, ana)

    assert c.post(f"/api/produtos/{produto_id}/pausar", headers=auth(bob)).status_code == 404


def test_nao_da_para_ver_historico_alheio(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    produto_id = criar_produto(c, ana)

    assert c.get(f"/api/produtos/{produto_id}/historico", headers=auth(bob)).status_code == 404


def test_nao_da_para_forcar_coleta_em_produto_alheio(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    produto_id = criar_produto(c, ana)

    assert c.post(f"/api/produtos/{produto_id}/coletar", headers=auth(bob)).status_code == 404


def test_resumo_conta_so_os_proprios_produtos(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    criar_produto(c, ana)

    assert c.get("/api/resumo", headers=auth(ana)).json()["total_produtos"] == 1
    resumo_bob = c.get("/api/resumo", headers=auth(bob)).json()
    assert resumo_bob["total_produtos"] == 0
    assert resumo_bob["total_coletas"] == 0


def test_alertas_sao_isolados_por_dono(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    # preco_alvo acima do atual dispara o alerta já no cadastro
    c.post(
        "/api/produtos",
        json={"url": "http://loja.test/p/fone", "preco_alvo": "900.00"},
        headers=auth(ana),
    )

    assert len(c.get("/api/alertas", headers=auth(ana)).json()) == 1
    assert c.get("/api/alertas", headers=auth(bob)).json() == []


def test_rodada_manual_nao_alcanca_produto_alheio(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    criar_produto(c, ana)

    rodada = c.post("/api/coletas/executar", headers=auth(bob)).json()
    assert rodada["total"] == 0


def test_saude_das_lojas_nao_vaza_lojas_alheias(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")
    criar_produto(c, ana)

    assert c.get("/api/lojas", headers=auth(bob)).json() == []


# --------------------------------------------------------------------------- #
# A URL passou a ser única por usuário, não globalmente
# --------------------------------------------------------------------------- #
def test_dois_usuarios_podem_monitorar_a_mesma_url(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")

    criar_produto(c, ana)
    criar_produto(c, bob)  # antes disto respondia 409


def test_o_mesmo_usuario_nao_duplica_a_mesma_url(cliente):
    c, _ = cliente
    ana = registrar(c, "ana@teste.com")
    criar_produto(c, ana)

    repetido = c.post(
        "/api/produtos",
        json={"url": "http://loja.test/p/fone", "preco_alvo": "400.00"},
        headers=auth(ana),
    )
    assert repetido.status_code == 409


def test_dono_vem_do_token_e_nao_do_corpo(cliente):
    """Mandar usuario_id no corpo não pode cadastrar produto na conta alheia."""
    c, sessao = cliente
    ana = registrar(c, "ana@teste.com")
    bob = registrar(c, "bob@teste.com")

    id_da_ana = c.get("/api/auth/eu", headers=auth(ana)).json()["id"]
    resposta = c.post(
        "/api/produtos",
        json={"url": "http://loja.test/p/outro", "preco_alvo": "500.00", "usuario_id": id_da_ana},
        headers=auth(bob),
    )
    assert resposta.status_code == 201
    produto = sessao.get(Produto, resposta.json()["id"])
    assert produto.usuario.email == "bob@teste.com"  # ignorou o usuario_id do corpo
