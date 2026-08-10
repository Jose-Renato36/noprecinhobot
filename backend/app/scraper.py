"""Scraper adaptativo de produtos: acessa a página e extrai nome, preço e imagem.

Três ideias sustentam este módulo:

1. **Impersonação de navegador.** Lojas grandes não olham o User-Agent, olham a
   impressão digital do handshake TLS/HTTP2 (JA3). A `curl_cffi` reproduz a de um
   navegador real. O perfil que funciona varia por loja — a Amazon só abre com
   `safari`/`edge`, a Magalu com `chrome`/`firefox` — então o scraper testa vários
   e **lembra qual funcionou** para aquele domínio.

2. **Consenso entre estratégias.** Em vez de parar na primeira fonte que devolve um
   número, ele coleta candidatos de *todas* as fontes (JSON-LD, microdata, meta
   tags, JSON embutido, seletores da loja, varredura) e escolhe o valor com maior
   peso somado. Isso resolve um caso comum e traiçoeiro: a loja põe o produto em
   promoção mas esquece de atualizar o JSON-LD — o preço certo aparece em três
   fontes e vence o JSON-LD sozinho.

3. **Memória de seletor.** Quando um preço é confirmado, o scraper localiza aquele
   valor no DOM e guarda o caminho CSS. Na coleta seguinte, tenta esse caminho
   primeiro. Se a loja trocar o layout, o caminho falha, a cascata assume e um
   novo caminho é aprendido — o scraper se conserta sozinho.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import navegador
from .config import config

logger = logging.getLogger(__name__)

# A curl_cffi é opcional: sem ela o scraper cai no `requests` e perde só a
# capacidade de furar antibot — todo o resto continua funcionando.
try:
    from curl_cffi import requests as cliente_http

    IMPERSONACAO_DISPONIVEL = True
except ImportError:  # pragma: no cover - caminho de degradação
    import requests as cliente_http

    IMPERSONACAO_DISPONIVEL = False

_excecoes = getattr(cliente_http, "exceptions", None)
ERROS_DE_REDE = tuple(
    filtro
    for filtro in (
        getattr(_excecoes, "RequestException", None),
        getattr(_excecoes, "RequestsError", None),
    )
    if filtro is not None
) or (Exception,)

# Ordem de tentativa. Cobre as quatro impressões digitais que as lojas brasileiras
# aceitam; a primeira que devolver um preço válido vira a preferida do domínio.
PERFIS_NAVEGADOR = ("chrome", "edge", "safari", "firefox")

CABECALHOS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}
# Só é preciso forjar o User-Agent quando não há impersonação de verdade.
USER_AGENT_MANUAL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

STATUS_TEMPORARIOS = {429, 500, 502, 503, 504}

# Pesos de confiança por fonte. Somados por valor, decidem o vencedor.
PESO = {
    "aprendido": 1.10,  # caminho CSS que já funcionou neste produto
    "json-ld": 0.95,
    "microdata": 0.85,
    "seletor-loja": 0.80,
    "meta": 0.75,
    "json-inline": 0.70,
    "varredura": 0.45,
}

SELETORES_POR_LOJA: dict[str, dict[str, list[str]]] = {
    "mercadolivre.com.br": {
        "preco": ["meta[itemprop='price']", ".andes-money-amount__fraction"],
        "centavos": [".andes-money-amount__cents"],
        "nome": ["h1.ui-pdp-title"],
        "imagem": ["figure.ui-pdp-gallery__figure img", "img.ui-pdp-image"],
    },
    "amazon.com.br": {
        "preco": [
            "#corePrice_feature_div .a-offscreen",
            ".a-price .a-offscreen",
            "#priceblock_ourprice",
        ],
        "nome": ["#productTitle"],
        "imagem": ["#landingImage", "#imgBlkFront"],
    },
    "magazineluiza.com.br": {
        "preco": ["[data-testid='price-value']", "[data-testid='price-original']"],
        "nome": ["[data-testid='heading-product-title']", "h1"],
        "imagem": ["[data-testid='image-selected-thumb']", "img[alt]"],
    },
    "kabum.com.br": {
        "preco": ["h4.finalPrice", ".finalPrice"],
        "nome": ["h1"],
        "imagem": ["#carouselDetails img", "img"],
    },
    "americanas.com.br": {
        "preco": ["[class*='PriceUI'] span", ".price__SalesPrice-sc-uoay31-3"],
        "nome": ["h1"],
        "imagem": ["img[class*='image']"],
    },
}

# A ordem das alternativas importa: os formatos com separador de milhar vêm
# primeiro, senão "51.77" casaria só o "51" e o resto viraria outro candidato.
RE_PRECO = re.compile(
    r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"  # 1.234,56 / 5.499  (padrão BR)
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"  # 1,234.56          (padrão US)
    r"|\d+(?:[.,]\d{1,2})?"  # 1234,56 / 51.77 / 12
)
CLASSES_COM_CARA_DE_PRECO = re.compile(r"(pre[cç]o|price|valor|amount|sale)", re.I)
CHAVES_DE_PRECO = re.compile(
    r"^(price|saleprice|sale_price|currentprice|current_price|finalprice|final_price"
    r"|bestprice|best_price|pricevalue|price_value|preco|precoatual|preco_atual"
    r"|valor|amount|unitprice|unit_price)$",
    re.I,
)
CHAVES_DE_NOME = re.compile(r"^(name|title|productname|product_name|nome|titulo)$", re.I)
# Classes geradas por CSS-in-JS mudam a cada build: não servem como âncora.
RE_CLASSE_INSTAVEL = re.compile(r"^(css|sc|jsx|styles?)[-_][a-z0-9]{4,}$", re.I)
RE_CLASSE_VALIDA = re.compile(r"^[A-Za-z_][\w-]*$")

# Qual perfil de navegador funcionou por domínio, dentro deste processo.
_PERFIL_POR_DOMINIO: dict[str, str] = {}


class ScraperError(Exception):
    """Falha ao acessar ou interpretar a página do produto."""


@dataclass
class Dica:
    """O que o sistema já aprendeu sobre este produto em coletas anteriores."""

    seletor: str | None = None
    perfil: str | None = None


@dataclass
class Candidato:
    preco: Decimal
    fonte: str
    seletor: str | None = None

    @property
    def peso(self) -> float:
        return PESO.get(self.fonte, 0.3)


@dataclass
class ResultadoScrape:
    nome: str | None
    preco: Decimal | None
    imagem_url: str | None
    moeda: str = "BRL"
    loja: str | None = None
    disponivel: bool = True
    url_final: str | None = None
    # Rastro do que funcionou — alimenta a memória do scraper e o painel.
    fonte: str | None = None
    confianca: float = 0.0
    seletor: str | None = None
    perfil: str | None = None
    fontes_concordantes: int = 0

    @property
    def valido(self) -> bool:
        return self.preco is not None


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def normalizar_preco(bruto: object) -> Decimal | None:
    """Converte "R$ 1.234,56", "1,234.56", "1234.5" ou 1234.5 em Decimal."""
    if bruto is None or isinstance(bruto, bool):
        return None
    if isinstance(bruto, (int, float, Decimal)):
        try:
            valor = Decimal(str(bruto)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None
        return valor if valor > 0 else None

    texto = str(bruto).strip()
    if not texto:
        return None

    texto = re.sub(r"[^\d,.\-]", "", texto)
    if not re.search(r"\d", texto):
        return None

    tem_ponto, tem_virgula = "." in texto, "," in texto
    if tem_ponto and tem_virgula:
        # O separador decimal é o que aparece por último ("1.234,56" ou "1,234.56").
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif tem_virgula:
        # Vírgula com 1-2 dígitos no fim é decimal; senão é separador de milhar.
        texto = texto.replace(",", "." if re.search(r",\d{1,2}$", texto) else "")
    elif tem_ponto:
        # Vários pontos ("1.234.567") são sempre milhar. Com um único ponto,
        # 3 dígitos depois dele indicam milhar no padrão brasileiro ("1.234");
        # 1 ou 2 dígitos indicam decimal ("1234.5" / "1234.56").
        if texto.count(".") > 1 or re.search(r"\.\d{3}$", texto):
            texto = texto.replace(".", "")

    try:
        valor = Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return valor if valor > 0 else None


def _dominio(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _nome_da_loja(url: str) -> str:
    dominio = _dominio(url)
    if not dominio:
        return "Desconhecida"
    # Endereços de IP e localhost não têm nome útil para exibir.
    if dominio == "localhost" or re.fullmatch(r"[\d.:]+", dominio):
        return "Loja local"
    partes = dominio.split(".")
    return partes[0].capitalize() if partes else dominio


def _texto(elemento) -> str | None:
    if elemento is None:
        return None
    if elemento.has_attr("content"):
        return elemento["content"]
    texto = elemento.get_text(" ", strip=True)
    return texto or None


def _absolutizar(url_base: str, caminho: str | None) -> str | None:
    if not caminho:
        return None
    caminho = caminho.strip()
    if caminho.startswith("data:"):
        return None
    return urljoin(url_base, caminho)


def _preco_plausivel(valor: Decimal | None) -> bool:
    return valor is not None and Decimal("0.5") < valor < Decimal("10000000")


# --------------------------------------------------------------------------- #
# Caminho CSS: aprender e reusar
# --------------------------------------------------------------------------- #
def _classes_estaveis(elemento) -> list[str]:
    return [
        c
        for c in (elemento.get("class") or [])
        if RE_CLASSE_VALIDA.match(c) and not RE_CLASSE_INSTAVEL.match(c)
    ][:3]


def caminho_css(elemento, sopa, profundidade: int = 4) -> str | None:
    """Monta o seletor mais curto que identifica este elemento sem ambiguidade."""
    partes: list[str] = []
    atual = elemento
    for _ in range(profundidade):
        if atual is None or atual.name in (None, "[document]", "html"):
            break

        identificador = atual.get("id")
        if identificador and RE_CLASSE_VALIDA.match(identificador):
            partes.insert(0, f"#{identificador}")
            return " ".join(partes)

        partes.insert(0, atual.name + "".join(f".{c}" for c in _classes_estaveis(atual)))
        candidato = " ".join(partes)
        try:
            if len(sopa.select(candidato)) == 1:
                return candidato
        except Exception:  # seletor inválido: desiste de aprender
            return None
        atual = atual.parent

    candidato = " ".join(partes)
    return candidato or None


def _localizar_preco_no_dom(sopa, preco: Decimal):
    """Acha o menor elemento cujo texto é exatamente este preço."""
    for elemento in sopa.find_all(
        ["span", "div", "p", "strong", "b", "td", "h1", "h2", "h3", "h4", "ins", "bdi"]
    ):
        texto = elemento.get_text(" ", strip=True)
        if not texto or len(texto) > 40:
            continue
        if normalizar_preco(texto) == preco:
            return elemento
    return None


# --------------------------------------------------------------------------- #
# Estratégias de extração
# --------------------------------------------------------------------------- #
def _achatar_json_ld(no: object) -> list[dict]:
    """JSON-LD vem em formatos variados (@graph, listas, aninhado). Achata tudo."""
    encontrados: list[dict] = []
    if isinstance(no, list):
        for item in no:
            encontrados.extend(_achatar_json_ld(item))
    elif isinstance(no, dict):
        encontrados.append(no)
        for chave in ("@graph", "mainEntity", "itemListElement", "hasVariant"):
            if chave in no:
                encontrados.extend(_achatar_json_ld(no[chave]))
    return encontrados


def _de_json_ld(sopa) -> tuple[list[Candidato], dict]:
    candidatos: list[Candidato] = []
    extras: dict = {}

    for tag in sopa.find_all("script", type=lambda v: v and "ld+json" in v):
        conteudo = tag.string or tag.get_text()
        if not conteudo:
            continue
        try:
            dados = json.loads(conteudo.strip())
        except json.JSONDecodeError:
            continue

        for no in _achatar_json_ld(dados):
            tipo = no.get("@type", "")
            tipos = tipo if isinstance(tipo, list) else [tipo]
            if not any("product" in str(t).lower() for t in tipos):
                continue

            ofertas = no.get("offers") or {}
            if isinstance(ofertas, list):
                ofertas = ofertas[0] if ofertas else {}
            if not isinstance(ofertas, dict):
                ofertas = {}

            bruto = ofertas.get("price") or ofertas.get("lowPrice") or no.get("price")
            if bruto is None and isinstance(ofertas.get("priceSpecification"), dict):
                bruto = ofertas["priceSpecification"].get("price")

            preco = normalizar_preco(bruto)
            if _preco_plausivel(preco):
                candidatos.append(Candidato(preco=preco, fonte="json-ld"))

            imagem = no.get("image")
            if isinstance(imagem, list):
                imagem = imagem[0] if imagem else None
            if isinstance(imagem, dict):
                imagem = imagem.get("url")

            # `brand` no schema.org é o fabricante do produto ("Britânia"), não a
            # loja. Quem identifica o vendedor é `offers.seller`.
            vendedor = ofertas.get("seller")
            if isinstance(vendedor, dict):
                vendedor = vendedor.get("name")

            disponibilidade = str(ofertas.get("availability", "")).lower()
            extras.setdefault("nome", no.get("name"))
            extras.setdefault("imagem_url", imagem)
            extras.setdefault("moeda", ofertas.get("priceCurrency"))
            extras.setdefault("loja", vendedor if isinstance(vendedor, str) else None)
            extras.setdefault(
                "disponivel", "outofstock" not in disponibilidade.replace("_", "")
            )
    return candidatos, extras


def _de_microdata(sopa) -> tuple[list[Candidato], dict]:
    candidatos: list[Candidato] = []
    extras: dict = {}

    tag = sopa.select_one("[itemprop='price']")
    if tag is not None:
        preco = normalizar_preco(tag.get("content") or _texto(tag))
        if _preco_plausivel(preco):
            candidatos.append(Candidato(preco=preco, fonte="microdata"))

    for chave, seletor in (("nome", "[itemprop='name']"), ("moeda", "[itemprop='priceCurrency']")):
        alvo = sopa.select_one(seletor)
        if alvo is not None:
            extras[chave] = alvo.get("content") or _texto(alvo)
    imagem = sopa.select_one("[itemprop='image']")
    if imagem is not None:
        extras["imagem_url"] = imagem.get("content") or imagem.get("src")
    return candidatos, extras


def _de_meta(sopa) -> tuple[list[Candidato], dict]:
    def meta(*nomes: str) -> str | None:
        for nome in nomes:
            tag = sopa.find("meta", attrs={"property": nome}) or sopa.find(
                "meta", attrs={"name": nome}
            )
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    candidatos: list[Candidato] = []
    preco = normalizar_preco(meta("product:price:amount", "og:price:amount", "twitter:data1"))
    if _preco_plausivel(preco):
        candidatos.append(Candidato(preco=preco, fonte="meta"))

    extras = {
        "nome": meta("og:title", "twitter:title"),
        "imagem_url": meta("og:image", "og:image:secure_url", "twitter:image"),
        "moeda": meta("product:price:currency", "og:price:currency"),
        "loja": meta("og:site_name"),
    }
    return candidatos, {k: v for k, v in extras.items() if v}


def _blocos_json(texto: str, maximo: int = 4) -> list[object]:
    """Extrai objetos JSON de dentro de um <script>.

    Cobre tanto `<script type="application/json">{...}</script>` (Next.js) quanto
    `window.__PRELOADED_STATE__ = {...};` (Vue/Redux e afins).
    """
    blocos: list[object] = []
    texto = texto.strip()
    if not texto:
        return blocos

    if texto[0] in "{[":
        try:
            return [json.loads(texto)]
        except json.JSONDecodeError:
            pass

    for achado in re.finditer(r"=\s*(\{)", texto):
        if len(blocos) >= maximo:
            break
        recorte = _recortar_objeto(texto, achado.start(1))
        if not recorte:
            continue
        try:
            blocos.append(json.loads(recorte))
        except json.JSONDecodeError:
            continue
    return blocos


def _recortar_objeto(texto: str, inicio: int, limite: int = 3_000_000) -> str | None:
    """Varre chaves balanceadas a partir de `inicio`, ignorando o que está em string."""
    profundidade = 0
    dentro_de_string = False
    escapado = False
    for posicao in range(inicio, min(len(texto), inicio + limite)):
        caractere = texto[posicao]
        if dentro_de_string:
            if escapado:
                escapado = False
            elif caractere == "\\":
                escapado = True
            elif caractere == '"':
                dentro_de_string = False
            continue
        if caractere == '"':
            dentro_de_string = True
        elif caractere == "{":
            profundidade += 1
        elif caractere == "}":
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio : posicao + 1]
    return None


def _cacar_precos(no: object, achados: list[Candidato], profundidade: int = 0) -> None:
    """Percorre o JSON procurando dicionários que descrevam um produto."""
    if profundidade > 10 or len(achados) >= 12:
        return

    if isinstance(no, list):
        for item in no[:60]:
            _cacar_precos(item, achados, profundidade + 1)
        return

    if not isinstance(no, dict):
        return

    tem_nome = any(CHAVES_DE_NOME.match(str(k)) for k in no)
    for chave, valor in no.items():
        if isinstance(valor, (dict, list)):
            continue
        if not CHAVES_DE_PRECO.match(str(chave)):
            continue
        preco = normalizar_preco(valor)
        # Sem um nome por perto, o número tem grande chance de ser frete,
        # desconto ou id — só aceitamos quando o objeto parece um produto.
        if _preco_plausivel(preco) and tem_nome:
            achados.append(Candidato(preco=preco, fonte="json-inline"))

    for valor in no.values():
        if isinstance(valor, (dict, list)):
            _cacar_precos(valor, achados, profundidade + 1)


def _de_json_inline(sopa) -> tuple[list[Candidato], dict]:
    achados: list[Candidato] = []
    for tag in sopa.find_all("script"):
        if len(achados) >= 12:
            break
        tipo = (tag.get("type") or "").lower()
        if "ld+json" in tipo:
            continue  # já tratado com regras próprias
        bruto = tag.string or tag.get_text()
        if not bruto or len(bruto) > 4_000_000:
            continue
        for dados in _blocos_json(bruto):
            _cacar_precos(dados, achados)
    return achados, {}


def _de_seletores_da_loja(sopa, url: str) -> tuple[list[Candidato], dict]:
    dominio = _dominio(url)
    regras = next((r for d, r in SELETORES_POR_LOJA.items() if dominio.endswith(d)), None)
    if not regras:
        return [], {}

    candidatos: list[Candidato] = []
    for seletor in regras.get("preco", []):
        bruto = _texto(sopa.select_one(seletor))
        if not bruto:
            continue
        # Lojas que separam reais e centavos em tags diferentes.
        if "," not in bruto and "." not in bruto:
            for seletor_centavos in regras.get("centavos", []):
                centavos = _texto(sopa.select_one(seletor_centavos))
                if centavos and centavos.strip().isdigit():
                    bruto = f"{bruto},{centavos.strip()[:2]}"
                    break
        preco = normalizar_preco(bruto)
        if _preco_plausivel(preco):
            candidatos.append(Candidato(preco=preco, fonte="seletor-loja", seletor=seletor))
            break

    extras: dict = {}
    for seletor in regras.get("nome", []):
        nome = _texto(sopa.select_one(seletor))
        if nome:
            extras["nome"] = nome
            break
    for seletor in regras.get("imagem", []):
        tag = sopa.select_one(seletor)
        if tag is not None:
            src = tag.get("src") or tag.get("data-src") or tag.get("data-old-hires")
            if src:
                extras["imagem_url"] = src
                break
    return candidatos, extras


def _de_varredura(sopa) -> tuple[list[Candidato], dict]:
    """Último recurso: procura "R$ x" em elementos cuja classe/id parece de preço."""
    vistos: list[Decimal] = []
    for elemento in sopa.find_all(["span", "div", "p", "strong", "b", "h1", "h2", "h3", "h4"]):
        atributos = " ".join(
            filter(None, [" ".join(elemento.get("class", [])), elemento.get("id", "")])
        )
        if not CLASSES_COM_CARA_DE_PRECO.search(atributos):
            continue
        texto = elemento.get_text(" ", strip=True)
        if not texto or len(texto) > 60:
            continue
        for achado in RE_PRECO.findall(texto):
            preco = normalizar_preco(achado)
            if _preco_plausivel(preco):
                vistos.append(preco)

    candidatos: list[Candidato] = []
    if vistos:
        # O preço de venda costuma aparecer repetido na página (destaque, resumo,
        # carrinho...); o valor mais frequente é o palpite mais seguro. Empate
        # resolve pelo menor, que normalmente é o preço à vista.
        frequencia = defaultdict(int)
        for preco in vistos:
            frequencia[preco] += 1
        maior = max(frequencia.values())
        candidatos.append(
            Candidato(preco=min(p for p, c in frequencia.items() if c == maior), fonte="varredura")
        )

    extras = {}
    h1 = sopa.find("h1")
    if h1 is not None:
        extras["nome"] = _texto(h1)
    return candidatos, extras


def _do_seletor_aprendido(sopa, seletor: str | None) -> list[Candidato]:
    if not seletor:
        return []
    try:
        elementos = sopa.select(seletor)
    except Exception:
        return []
    for elemento in elementos[:3]:
        preco = normalizar_preco(_texto(elemento))
        if _preco_plausivel(preco):
            return [Candidato(preco=preco, fonte="aprendido", seletor=seletor)]
    return []


# --------------------------------------------------------------------------- #
# Decisão por consenso
# --------------------------------------------------------------------------- #
def escolher_por_consenso(candidatos: list[Candidato]) -> tuple[Candidato, float, int] | None:
    """Soma os pesos por valor e devolve (melhor candidato, confiança, nº de fontes)."""
    if not candidatos:
        return None

    por_valor: dict[Decimal, list[Candidato]] = defaultdict(list)
    for candidato in candidatos:
        por_valor[candidato.preco].append(candidato)

    def pontuacao(valor: Decimal) -> tuple[float, float]:
        grupo = por_valor[valor]
        fontes_distintas = {c.fonte: c.peso for c in grupo}
        # Somar por fonte distinta: dez candidatos vindos do mesmo JSON gigante
        # não podem valer mais que o acordo entre JSON-LD e meta tags.
        return sum(fontes_distintas.values()), max(fontes_distintas.values())

    vencedor = max(por_valor, key=pontuacao)
    grupo = por_valor[vencedor]
    melhor = max(grupo, key=lambda c: c.peso)
    total, _ = pontuacao(vencedor)
    # Calibragem da escala: uma fonte estruturada sozinha fica em ~0,8; duas
    # fontes concordando saturam em 1,0; a varredura sozinha cai para ~0,4,
    # que é honesto — ela adivinha.
    return melhor, round(min(1.0, total / 1.2), 3), len({c.fonte for c in grupo})


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def extrair_da_pagina(html: str, url: str, dica: Dica | None = None) -> ResultadoScrape:
    """Aplica todas as estratégias sobre o HTML e decide o preço por consenso."""
    try:
        sopa = BeautifulSoup(html, "lxml")
    except Exception:  # lxml ausente: o parser padrão resolve
        sopa = BeautifulSoup(html, "html.parser")

    candidatos: list[Candidato] = list(_do_seletor_aprendido(sopa, dica.seletor if dica else None))
    extras: dict = {}

    for estrategia in (
        _de_json_ld,
        _de_microdata,
        _de_meta,
        _de_json_inline,
        lambda s: _de_seletores_da_loja(s, url),
        _de_varredura,
    ):
        try:
            novos, parciais = estrategia(sopa)
        except Exception as exc:  # uma estratégia quebrada não derruba as outras
            logger.debug("Estratégia falhou em %s: %s", url, exc)
            continue
        candidatos.extend(novos)
        for chave, valor in parciais.items():
            if valor not in (None, "") and extras.get(chave) in (None, ""):
                extras[chave] = valor

    escolha = escolher_por_consenso(candidatos)

    nome = (extras.get("nome") or "").strip() or None
    if nome:
        # Conteúdo de <script> não passa pelo decode de entidades do parser, então
        # nomes vindos de JSON-LD podem chegar com &quot; / &amp; literais.
        nome = re.sub(r"\s+", " ", unescape(nome))[:290]

    resultado = ResultadoScrape(
        nome=nome,
        preco=None,
        imagem_url=_absolutizar(url, extras.get("imagem_url")),
        moeda=(extras.get("moeda") or "BRL").strip().upper()[:8] or "BRL",
        # A loja se identifica melhor do que o domínio: og:site_name ou a marca do
        # JSON-LD vêm primeiro; o domínio é só o plano B.
        loja=(extras.get("loja") or "").strip()[:110] or _nome_da_loja(url),
        disponivel=bool(extras.get("disponivel", True)),
        url_final=url,
    )

    if escolha is not None:
        melhor, confianca, concordantes = escolha
        resultado.preco = melhor.preco
        resultado.fonte = melhor.fonte
        resultado.confianca = confianca
        resultado.fontes_concordantes = concordantes
        # Aprende (ou reaprende) o caminho CSS que aponta para este preço.
        resultado.seletor = melhor.seletor
        if melhor.fonte != "aprendido":
            elemento = _localizar_preco_no_dom(sopa, melhor.preco)
            if elemento is not None:
                resultado.seletor = caminho_css(elemento, sopa) or melhor.seletor

    return resultado


def coletar_html(url: str, perfil: str | None = None, timeout: int | None = None) -> tuple[str, str]:
    """Baixa o HTML da página. Retorna (html, url_final após redirecionamentos)."""
    if not re.match(r"^https?://", url, re.I):
        raise ScraperError("A URL precisa começar com http:// ou https://")

    cabecalhos = dict(CABECALHOS)
    opcoes: dict = {}
    if IMPERSONACAO_DISPONIVEL:
        opcoes["impersonate"] = perfil or PERFIS_NAVEGADOR[0]
    else:
        cabecalhos["User-Agent"] = USER_AGENT_MANUAL

    ultimo_status = None
    for tentativa in range(config.SCRAPER_TENTATIVAS):
        try:
            resposta = cliente_http.get(
                url,
                headers=cabecalhos,
                timeout=timeout or config.SCRAPER_TIMEOUT,
                allow_redirects=True,
                **opcoes,
            )
        except ERROS_DE_REDE as exc:
            if "timed out" in str(exc).lower() or "timeout" in type(exc).__name__.lower():
                raise ScraperError("A loja demorou demais para responder (timeout).") from exc
            raise ScraperError(f"Não foi possível acessar a página: {exc}") from exc

        ultimo_status = resposta.status_code
        if resposta.status_code in STATUS_TEMPORARIOS and tentativa < config.SCRAPER_TENTATIVAS - 1:
            # 429/5xx são temporários: espera o que a loja pedir (ou dobra a espera).
            espera = min(float(resposta.headers.get("Retry-After") or 2**tentativa), 30.0)
            logger.info("HTTP %s em %s — nova tentativa em %.0fs", resposta.status_code, url, espera)
            time.sleep(espera)
            continue
        break

    if ultimo_status == 403:
        raise ScraperError("A loja bloqueou o acesso do robô (HTTP 403).")
    if ultimo_status and ultimo_status >= 400:
        raise ScraperError(f"A loja respondeu com HTTP {ultimo_status}.")

    resposta.encoding = resposta.encoding or getattr(resposta, "apparent_encoding", None) or "utf-8"
    return resposta.text, str(resposta.url)


def raspar_produto(url: str, dica: Dica | None = None) -> ResultadoScrape:
    """Coleta e interpreta a página de um produto.

    Testa perfis de navegador até um deles render um preço válido — o critério de
    sucesso é ter extraído o preço, não ter recebido HTTP 200: lojas com antibot
    devolvem 200 com uma página de desafio vazia.
    """
    dica = dica or Dica()
    dominio = _dominio(url)
    preferido = dica.perfil or _PERFIL_POR_DOMINIO.get(dominio)

    perfis = [preferido] if preferido else []
    perfis += [p for p in PERFIS_NAVEGADOR if p != preferido]
    if not IMPERSONACAO_DISPONIVEL:
        perfis = [None]

    ultimo_erro: ScraperError | None = None
    melhor_parcial: ResultadoScrape | None = None

    for perfil in perfis:
        try:
            html, url_final = coletar_html(url, perfil)
        except ScraperError as exc:
            ultimo_erro = exc
            continue

        resultado = extrair_da_pagina(html, url_final, dica)
        resultado.perfil = perfil
        if resultado.valido:
            if perfil:
                _PERFIL_POR_DOMINIO[dominio] = perfil
            if not resultado.nome:
                resultado.nome = f"Produto em {resultado.loja}"
            return resultado
        melhor_parcial = melhor_parcial or resultado

    # Nenhum perfil HTTP trouxe preço. Se o fallback de navegador estiver ligado,
    # a última chance é deixar o JavaScript da página rodar.
    renderizado = navegador.renderizar(url)
    if renderizado is not None:
        html, url_final = renderizado
        resultado = extrair_da_pagina(html, url_final, dica)
        resultado.perfil = "navegador"
        if resultado.valido:
            if not resultado.nome:
                resultado.nome = f"Produto em {resultado.loja}"
            logger.info("Preço de %s obtido pelo fallback de navegador.", url)
            return resultado
        # Nem o navegador achou preço: marca o domínio para não gastar mais
        # 20 segundos por produto nas próximas rodadas.
        navegador.registrar_sem_preco(url)
        melhor_parcial = resultado

    if melhor_parcial is not None:
        raise ScraperError(
            "A página abriu, mas o preço não está no HTML — nem depois de renderizar o "
            "JavaScript. Isso costuma ser bloqueio antibot da loja (Shopee, Mercado Livre "
            "e Magazine Luiza fazem isso). Confira se a URL aponta direto para a página do "
            "produto; se apontar, essa loja não é acessível por scraping."
        )
    raise ultimo_erro or ScraperError("Não foi possível acessar a página.")
