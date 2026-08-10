"""Testes do scraper — rodam offline, com HTML embutido nos próprios casos."""

from decimal import Decimal

import pytest

from app.scraper import Dica, caminho_css, extrair_da_pagina, normalizar_preco


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("R$ 1.234,56", "1234.56"),
        ("R$ 199,90", "199.90"),
        ("R$\xa02.199,00", "2199.00"),  # espaço não-quebrável, comum em lojas
        ("1.234.567,89", "1234567.89"),
        ("5.499", "5499.00"),  # ponto de milhar sem centavos
        ("1,234.56", "1234.56"),  # padrão americano
        ("1234.56", "1234.56"),
        ("649.9", "649.90"),
        ("£51.77", "51.77"),
        (2999.9, "2999.90"),
    ],
)
def test_normalizar_preco_aceita_formatos_variados(entrada, esperado):
    assert normalizar_preco(entrada) == Decimal(esperado)


@pytest.mark.parametrize("entrada", ["", "  ", "abc", "R$", None, "0", "0,00", True])
def test_normalizar_preco_rejeita_lixo(entrada):
    assert normalizar_preco(entrada) is None


HTML_JSON_LD = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Teclado K70",
 "image":"/img/k70.jpg","brand":{"@type":"Brand","name":"Corsair"},
 "offers":{"@type":"Offer","price":"459.90","priceCurrency":"BRL",
           "seller":{"@type":"Organization","name":"TechPrecinho"},
           "availability":"https://schema.org/InStock"}}
</script></head><body><h1>Teclado K70</h1></body></html>
"""


def test_extrai_de_json_ld():
    r = extrair_da_pagina(HTML_JSON_LD, "https://loja.com.br/p/k70")
    assert r.preco == Decimal("459.90")
    assert r.nome == "Teclado K70"
    assert r.imagem_url == "https://loja.com.br/img/k70.jpg"  # relativo virou absoluto
    assert r.loja == "TechPrecinho"  # veio do vendedor, não do domínio
    assert r.fonte == "json-ld"
    assert r.disponivel is True


def test_marca_do_produto_nao_e_confundida_com_a_loja():
    """`brand` no schema.org é o fabricante. Sem `seller`, o domínio manda —
    senão um ventilador da Britânia vendido na KaBuM viraria "loja Britânia"."""
    html = HTML_JSON_LD.replace(
        '"seller":{"@type":"Organization","name":"TechPrecinho"},', ""
    )
    r = extrair_da_pagina(html, "https://www.kabum.com.br/produto/97900")
    assert r.loja == "Kabum"


HTML_OG = """
<html><head>
<meta property="og:title" content="Monitor Ultrawide 29" />
<meta property="og:image" content="https://cdn.loja.com/m.jpg" />
<meta property="og:site_name" content="Loja do Zé" />
<meta property="product:price:amount" content="1849.00" />
<meta property="product:price:currency" content="BRL" />
</head><body></body></html>
"""


def test_extrai_de_open_graph():
    r = extrair_da_pagina(HTML_OG, "https://loja.com.br/p/monitor")
    assert r.preco == Decimal("1849.00")
    assert r.nome == "Monitor Ultrawide 29"
    assert r.loja == "Loja do Zé"


HTML_VARREDURA = """
<html><body>
  <h1>Cadeira Gamer Throne X</h1>
  <div class="product-price"><span class="price-value">R$ 1.299,00</span></div>
  <p class="preco-parcelado">ou 10x de R$ 129,90</p>
  <span class="price-value">R$ 1.299,00</span>
</body></html>
"""


def test_varredura_escolhe_o_preco_repetido():
    """Sem JSON-LD nem meta tags, sobra varrer a página: o valor que mais
    aparece é o preço de venda — a parcela aparece só uma vez."""
    r = extrair_da_pagina(HTML_VARREDURA, "https://loja.com.br/p/cadeira")
    assert r.preco == Decimal("1299.00")
    assert r.nome == "Cadeira Gamer Throne X"


def test_nome_vindo_do_json_ld_perde_as_entidades_html():
    html = HTML_JSON_LD.replace("Teclado K70", 'Monitor 29&quot; &amp; suporte', 1)
    r = extrair_da_pagina(html, "https://loja.com.br/p/monitor")
    assert r.nome == 'Monitor 29" & suporte'


def test_pagina_sem_preco_nao_e_valida():
    r = extrair_da_pagina("<html><body><h1>Sobre nós</h1></body></html>", "https://loja.com.br/")
    assert r.valido is False
    assert r.preco is None


def test_loja_em_ip_nao_vira_numero():
    r = extrair_da_pagina(
        HTML_OG.replace('content="Loja do Zé"', 'content=""'), "http://127.0.0.1:8000/p/1"
    )
    assert r.loja == "Loja local"


# --------------------------------------------------------------------------- #
# JSON embutido (Next.js, Redux e afins)
# --------------------------------------------------------------------------- #
HTML_JSON_INLINE = """
<html><head></head><body>
<h1>Smartphone Galax S24</h1>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"product":{"name":"Smartphone Galax S24","price":3199.00,
 "shipping":{"amount":49.9}}}}}
</script>
</body></html>
"""


def test_extrai_preco_de_json_embutido():
    """O preço não está no HTML visível nem em meta tags — só no blob do Next.js."""
    r = extrair_da_pagina(HTML_JSON_INLINE, "https://loja.com.br/p/galax")
    assert r.preco == Decimal("3199.00")
    assert r.fonte == "json-inline"


def test_json_embutido_ignora_numero_sem_produto_por_perto():
    """`shipping.amount` tem chave de preço mas nenhum nome no mesmo objeto:
    é frete, não o produto."""
    html = HTML_JSON_INLINE.replace('"name":"Smartphone Galax S24","price":3199.00,', "")
    r = extrair_da_pagina(html, "https://loja.com.br/p/galax")
    assert r.preco is None


HTML_STATE = """
<html><body><h1>Notebook</h1>
<script>window.__PRELOADED_STATE__ = {"item":{"title":"Notebook Nitro","salePrice":"5499,00"}};</script>
</body></html>
"""


def test_extrai_de_atribuicao_javascript():
    r = extrair_da_pagina(HTML_STATE, "https://loja.com.br/p/nb")
    assert r.preco == Decimal("5499.00")


# --------------------------------------------------------------------------- #
# Consenso entre fontes
# --------------------------------------------------------------------------- #
def test_consenso_vence_json_ld_desatualizado():
    """Caso real e traiçoeiro: a loja baixou o preço mas esqueceu de atualizar o
    JSON-LD. Três fontes concordam com o preço novo e derrubam o dado velho."""
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Fone AirBeats",
     "offers":{"@type":"Offer","price":"649.90","priceCurrency":"BRL"}}
    </script>
    <meta property="product:price:amount" content="399.90" />
    </head><body>
      <h1>Fone AirBeats</h1>
      <span class="price">R$ 399,90</span>
      <span class="price-box">R$ 399,90</span>
      <script type="application/json">{"product":{"name":"Fone AirBeats","price":399.90}}</script>
    </body></html>
    """
    r = extrair_da_pagina(html, "https://loja.com.br/p/fone")
    assert r.preco == Decimal("399.90")
    assert r.fontes_concordantes >= 3
    assert r.confianca > 0.5


def test_fonte_unica_tem_confianca_menor_que_consenso():
    sozinho = extrair_da_pagina(HTML_OG, "https://loja.com.br/p/x")
    juntos = extrair_da_pagina(
        HTML_JSON_LD.replace(
            "</head>", '<meta property="product:price:amount" content="459.90" /></head>'
        ),
        "https://loja.com.br/p/k70",
    )
    assert juntos.confianca > sozinho.confianca
    assert juntos.fontes_concordantes == 2


# --------------------------------------------------------------------------- #
# Memória de seletor (o "auto-conserto")
# --------------------------------------------------------------------------- #
def test_aprende_o_caminho_css_do_preco():
    r = extrair_da_pagina(HTML_VARREDURA, "https://loja.com.br/p/cadeira")
    assert r.seletor  # aprendeu um caminho
    assert "price" in r.seletor


def test_seletor_aprendido_e_usado_na_coleta_seguinte():
    primeira = extrair_da_pagina(HTML_VARREDURA, "https://loja.com.br/p/cadeira")
    segunda = extrair_da_pagina(
        HTML_VARREDURA, "https://loja.com.br/p/cadeira", Dica(seletor=primeira.seletor)
    )
    assert segunda.fonte == "aprendido"
    assert segunda.preco == Decimal("1299.00")


def test_seletor_obsoleto_nao_quebra_a_coleta():
    """A loja mudou o layout: o caminho aprendido não existe mais. A cascata
    assume, o preço continua saindo e um novo caminho é aprendido."""
    r = extrair_da_pagina(
        HTML_VARREDURA, "https://loja.com.br/p/cadeira", Dica(seletor="div.layout-antigo span.velho")
    )
    assert r.preco == Decimal("1299.00")
    assert r.fonte != "aprendido"
    assert r.seletor and "velho" not in r.seletor


# --------------------------------------------------------------------------- #
# Fallback de navegador
# --------------------------------------------------------------------------- #
HTML_SEM_PRECO = "<html><body><h1>Notebook Nitro</h1><div id='preco'>carregando…</div></body></html>"
HTML_RENDERIZADO = (
    "<html><body><h1>Notebook Nitro</h1>"
    "<div class='preco-final'>R$ 5.499,00</div>"
    "<span class='preco-final'>R$ 5.499,00</span></body></html>"
)


def test_fallback_de_navegador_resolve_pagina_montada_por_js(monkeypatch):
    """Nenhum perfil HTTP acha preço; o navegador renderiza e o preço aparece."""
    from app import navegador, scraper

    monkeypatch.setattr(scraper, "coletar_html", lambda url, perfil=None, timeout=None: (HTML_SEM_PRECO, url))
    monkeypatch.setattr(navegador, "renderizar", lambda url: (HTML_RENDERIZADO, url))

    resultado = scraper.raspar_produto("https://loja.com.br/p/nb")
    assert resultado.preco == Decimal("5499.00")
    assert resultado.perfil == "navegador"


def test_sem_fallback_a_pagina_por_js_falha_com_mensagem_clara(monkeypatch):
    from app import navegador, scraper

    monkeypatch.setattr(scraper, "coletar_html", lambda url, perfil=None, timeout=None: (HTML_SEM_PRECO, url))
    monkeypatch.setattr(navegador, "renderizar", lambda url: None)

    with pytest.raises(scraper.ScraperError, match="não está no HTML"):
        scraper.raspar_produto("https://loja.com.br/p/nb")


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("auto", "auto"), ("", "auto"), ("true", "sempre"), ("1", "sempre"),
     ("false", "nunca"), ("nao", "nunca"), (False, "nunca"), (True, "sempre")],
)
def test_modo_do_fallback(monkeypatch, valor, esperado):
    from app import navegador

    monkeypatch.setattr(navegador.config, "NAVEGADOR_FALLBACK", valor)
    assert navegador._modo() == esperado


def test_navegador_desligado_nao_e_chamado(monkeypatch):
    from app import navegador

    monkeypatch.setattr(navegador.config, "NAVEGADOR_FALLBACK", "false")
    assert navegador.renderizar("https://loja.com.br/p/x") is None
    assert navegador.disponivel() is False


def test_dominio_marcado_nem_abre_o_navegador(monkeypatch):
    """Sem esta trava, uma loja com antibot custaria ~20 s por produto, toda
    rodada, para sempre. O retorno é None antes de qualquer launch."""
    from app import navegador

    monkeypatch.setattr(navegador, "_dominios_sem_sucesso", set())
    monkeypatch.setattr(navegador, "_falhas_ao_abrir", 0)
    monkeypatch.setattr(navegador.config, "NAVEGADOR_FALLBACK", "sempre")
    monkeypatch.setattr(navegador, "_playwright_instalado", lambda: True)

    navegador.registrar_sem_preco("https://bloqueada.com.br/p/1")
    assert "bloqueada.com.br" in navegador._dominios_sem_sucesso
    assert navegador.renderizar("https://bloqueada.com.br/p/2") is None


def test_scraper_marca_dominio_quando_nem_o_navegador_acha_preco(monkeypatch):
    from app import navegador, scraper

    marcados = []
    monkeypatch.setattr(scraper, "coletar_html", lambda url, perfil=None, timeout=None: (HTML_SEM_PRECO, url))
    monkeypatch.setattr(navegador, "renderizar", lambda url: (HTML_SEM_PRECO, url))
    monkeypatch.setattr(navegador, "registrar_sem_preco", marcados.append)

    with pytest.raises(scraper.ScraperError, match="antibot"):
        scraper.raspar_produto("https://bloqueada.com.br/p/1")
    assert marcados == ["https://bloqueada.com.br/p/1"]


def test_caminho_css_ignora_classes_geradas_por_build():
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(
        '<div id="app"><span class="css-1x2y3z preco-final">R$ 10,00</span></div>', "html.parser"
    )
    caminho = caminho_css(sopa.find("span"), sopa)
    assert "preco-final" in caminho
    assert "css-1x2y3z" not in caminho  # hash de CSS-in-JS muda a cada deploy
