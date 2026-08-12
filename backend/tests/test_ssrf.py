"""Testes da recusa de destinos internos (SSRF).

O sistema recebe uma URL do usuário e faz a requisição **do servidor**. Sem
trava, isso alcança a rede privada da hospedagem — endereços que o navegador de
quem pediu jamais atingiria — e devolve o conteúdo na resposta da prévia.
"""

import pytest

from app.scraper import ScraperError, conferir_destino


@pytest.fixture(autouse=True)
def rede_interna_bloqueada(monkeypatch):
    monkeypatch.setattr("app.scraper.config.PERMITIR_REDE_INTERNA", False)
    # BASE_URL aponta para outro host, para a exceção da loja-demo não interferir.
    monkeypatch.setattr("app.scraper.config.BASE_URL", "https://noprecinho.example")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/admin",
        "http://localhost:5432/",
        "http://10.0.0.5/",
        "http://192.168.0.1/",
        "http://172.16.0.9/",
        "http://169.254.169.254/latest/meta-data/",  # metadados da nuvem
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_endereco_interno_e_recusado(url):
    with pytest.raises(ScraperError):
        conferir_destino(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://loja.com/x", "gopher://x/"])
def test_esquema_nao_http_e_recusado(url):
    with pytest.raises(ScraperError, match="http"):
        conferir_destino(url)


def test_dominio_publico_passa():
    conferir_destino("https://www.kabum.com.br/produto/331159")


def test_dominio_que_resolve_para_loopback_e_recusado(monkeypatch):
    """A checagem é sobre o IP resolvido, não sobre o texto do domínio.

    Qualquer pessoa pode apontar um domínio público para 127.0.0.1; validar só a
    aparência do endereço não protegeria nada.
    """
    import socket

    def resolver_para_loopback(host, porta, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", porta))]

    monkeypatch.setattr("socket.getaddrinfo", resolver_para_loopback)
    with pytest.raises(ScraperError, match="loja pública"):
        conferir_destino("https://loja-parece-legitima.com/produto")


def test_loja_demo_da_propria_api_e_liberada(monkeypatch):
    """A loja-demo roda em 127.0.0.1 e é a exceção legítima."""
    monkeypatch.setattr("app.scraper.config.BASE_URL", "http://127.0.0.1:8000")
    conferir_destino("http://127.0.0.1:8000/loja-demo/produto/fone-airbeats-pro")


def test_liberacao_explicita_permite_rede_interna(monkeypatch):
    monkeypatch.setattr("app.scraper.config.PERMITIR_REDE_INTERNA", True)
    conferir_destino("http://192.168.0.10:3000/produto")


def test_raspar_produto_recusa_antes_de_qualquer_requisicao(monkeypatch):
    """A trava tem que agir antes da rede, não depois."""
    from app import scraper

    def proibido(*a, **k):
        raise AssertionError("O scraper tentou acessar a rede num destino interno.")

    monkeypatch.setattr(scraper, "coletar_html", proibido)
    with pytest.raises(ScraperError):
        scraper.raspar_produto("http://169.254.169.254/latest/meta-data/")
