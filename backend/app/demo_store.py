"""Loja fictícia "TechPrecinho", servida pela própria API.

Serve para demonstrar o sistema de ponta a ponta: são páginas HTML de verdade
(com JSON-LD, OpenGraph e marcação de preço), acessadas pelo scraper via HTTP
como qualquer outra loja. A diferença é que o preço oscila a cada minuto, então
dá para ver o histórico se formar e o alerta disparar durante a apresentação.

Motivo de existir: Amazon, Mercado Livre e afins respondem HTTP 403 para robôs,
o que inviabiliza uma demonstração ao vivo confiável.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from decimal import Decimal
from html import escape

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config
from .models import DemoProduto

PERIODO_SEGUNDOS = 600  # um ciclo completo de alta/baixa a cada 10 minutos
AMPLITUDE = 0.12  # variação de ±12% em torno do preço base

CATALOGO_INICIAL = [
    {
        "slug": "notebook-nitro-v15",
        "nome": "Notebook Gamer Nitro V15 - Ryzen 7, 16GB, RTX 4060",
        "descricao": "Notebook gamer com tela 165Hz, SSD 1TB e teclado retroiluminado.",
        "preco_base": Decimal("5499.00"),
        "emoji": "💻",
        "cor": "#6366f1",
    },
    {
        "slug": "fone-airbeats-pro",
        "nome": "Fone Bluetooth AirBeats Pro com Cancelamento de Ruído",
        "descricao": "Cancelamento ativo, 32h de bateria e estojo com carga sem fio.",
        "preco_base": Decimal("649.90"),
        "emoji": "🎧",
        "cor": "#0ea5e9",
    },
    {
        "slug": "cadeira-gamer-throne",
        "nome": "Cadeira Gamer Throne X - Encosto Reclinável 180°",
        "descricao": "Estrutura de aço, apoio lombar em memory foam e braços 4D.",
        "preco_base": Decimal("1299.00"),
        "emoji": "🪑",
        "cor": "#f43f5e",
    },
    {
        "slug": "monitor-ultrawide-29",
        "nome": 'Monitor Ultrawide 29" 144Hz IPS 1ms',
        "descricao": "Painel IPS 21:9, FreeSync Premium e suporte com ajuste de altura.",
        "preco_base": Decimal("1849.00"),
        "emoji": "🖥️",
        "cor": "#10b981",
    },
    {
        "slug": "teclado-mecanico-k70",
        "nome": "Teclado Mecânico K70 RGB Switch Brown ABNT2",
        "descricao": "Switches hot-swap, chassi de alumínio e apoio de pulso magnético.",
        "preco_base": Decimal("459.90"),
        "emoji": "⌨️",
        "cor": "#f59e0b",
    },
    {
        "slug": "smartphone-galax-s24",
        "nome": "Smartphone Galax S24 256GB 5G Câmera Tripla 108MP",
        "descricao": "Tela AMOLED 6.7\" 120Hz, bateria de 5000mAh e carregamento de 45W.",
        "preco_base": Decimal("3199.00"),
        "emoji": "📱",
        "cor": "#8b5cf6",
    },
]

_META = {item["slug"]: item for item in CATALOGO_INICIAL}


# --------------------------------------------------------------------------- #
# Preço dinâmico
# --------------------------------------------------------------------------- #
def _fase(slug: str) -> float:
    """Fase fixa por produto para que os preços não subam e desçam todos juntos."""
    digest = hashlib.md5(slug.encode()).hexdigest()
    return (int(digest[:8], 16) % 1000) / 1000 * 2 * math.pi


def preco_atual(produto: DemoProduto, instante: float | None = None) -> Decimal:
    agora = time.time() if instante is None else instante
    onda = math.sin(2 * math.pi * agora / PERIODO_SEGUNDOS + _fase(produto.slug))
    fator = float(produto.fator_promocao or 1.0) * (1 + AMPLITUDE * onda)
    valor = Decimal(str(produto.preco_base)) * Decimal(str(round(fator, 6)))
    return valor.quantize(Decimal("0.01"))


def semear_catalogo(db: Session) -> int:
    """Insere os produtos da loja-demo que ainda não existem. Idempotente."""
    existentes = set(db.scalars(select(DemoProduto.slug)))
    novos = 0
    for item in CATALOGO_INICIAL:
        if item["slug"] in existentes:
            continue
        db.add(
            DemoProduto(
                slug=item["slug"],
                nome=item["nome"],
                descricao=item["descricao"],
                preco_base=item["preco_base"],
                imagem_url=f"{config.BASE_URL}/loja-demo/img/{item['slug']}.svg",
                fator_promocao=1.0,
            )
        )
        novos += 1
    if novos:
        db.commit()
    return novos


# --------------------------------------------------------------------------- #
# Renderização
# --------------------------------------------------------------------------- #
def _brl(valor: Decimal) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _svg_produto(slug: str) -> str:
    meta = _META.get(slug, {})
    cor = meta.get("cor", "#64748b")
    emoji = meta.get("emoji", "📦")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{cor}" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="{cor}" stop-opacity="0.45"/>
    </linearGradient>
  </defs>
  <rect width="600" height="600" fill="url(#g)"/>
  <circle cx="300" cy="285" r="170" fill="#ffffff" fill-opacity="0.18"/>
  <text x="300" y="360" font-size="210" text-anchor="middle">{emoji}</text>
  <text x="300" y="545" font-size="30" font-family="Segoe UI, Arial, sans-serif"
        fill="#ffffff" fill-opacity="0.9" text-anchor="middle">TechPrecinho</text>
</svg>"""


def _pagina_produto(produto: DemoProduto, preco: Decimal) -> str:
    meta = _META.get(produto.slug, {})
    nome = escape(produto.nome)
    descricao = escape(produto.descricao or "")
    imagem = f"{config.BASE_URL}/loja-demo/img/{produto.slug}.svg"
    url = f"{config.BASE_URL}/loja-demo/produto/{produto.slug}"
    parcela = (preco / 10).quantize(Decimal("0.01"))
    preco_de = (Decimal(str(produto.preco_base)) * Decimal("1.25")).quantize(Decimal("0.01"))

    # O bloco JSON-LD é JSON, não HTML: precisa de escape de JSON (aspas dentro do
    # nome viravam &quot; e chegavam sujas no scraper). O `</` escapado evita que
    # um texto do produto feche a tag <script> antes da hora.
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": produto.nome,
            "image": imagem,
            "description": produto.descricao or "",
            "sku": produto.slug,
            "brand": {"@type": "Brand", "name": "TechPrecinho"},
            "offers": {
                "@type": "Offer",
                "url": url,
                "priceCurrency": "BRL",
                "price": str(preco),
                "availability": "https://schema.org/InStock",
            },
        },
        ensure_ascii=False,
        indent=2,
    ).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{nome} | TechPrecinho</title>
<meta property="og:type" content="product" />
<meta property="og:title" content="{nome}" />
<meta property="og:image" content="{imagem}" />
<meta property="og:url" content="{url}" />
<meta property="product:price:amount" content="{preco}" />
<meta property="product:price:currency" content="BRL" />
<meta property="og:site_name" content="TechPrecinho" />
<script type="application/ld+json">
{json_ld}
</script>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: "Segoe UI", system-ui, sans-serif; background:#f1f5f9; color:#0f172a; }}
  header {{ background:#0f172a; color:#fff; padding:14px 24px; font-weight:700; letter-spacing:.02em; }}
  header span {{ color:#38bdf8; }}
  main {{ max-width: 940px; margin: 28px auto; padding: 0 20px; display:grid;
          grid-template-columns: minmax(0,340px) minmax(0,1fr); gap:32px; align-items:start; }}
  .foto {{ background:#fff; border-radius:16px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,.1); }}
  .foto img {{ width:100%; border-radius:10px; display:block; }}
  h1 {{ font-size:24px; line-height:1.3; margin:0 0 8px; }}
  .desc {{ color:#475569; font-size:15px; margin:0 0 24px; }}
  .caixa {{ background:#fff; border-radius:16px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,.1); }}
  .de {{ color:#94a3b8; text-decoration:line-through; font-size:15px; }}
  .preco {{ font-size:38px; font-weight:800; color:#059669; margin:4px 0; }}
  .parcela {{ color:#475569; font-size:14px; }}
  .comprar {{ display:block; width:100%; margin-top:20px; background:#059669; color:#fff; border:0;
              padding:14px; border-radius:10px; font-size:16px; font-weight:700; cursor:pointer; }}
  .aviso {{ max-width:940px; margin:0 auto 28px; padding:14px 20px; font-size:13px; color:#78350f;
            background:#fef3c7; border:1px solid #fde68a; border-radius:12px; }}
  @media (max-width: 720px) {{ main {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>Tech<span>Precinho</span> — a loja de mentirinha do NoPrecinhoBot</header>
<main>
  <div class="foto"><img src="{imagem}" alt="{nome}" /></div>
  <div>
    <h1 itemprop="name">{nome}</h1>
    <p class="desc">{descricao}</p>
    <div class="caixa" itemscope itemtype="https://schema.org/Offer">
      <div class="de">De R$ {_brl(preco_de)}</div>
      <div class="preco" data-testid="price-value">R$ {_brl(preco)}</div>
      <meta itemprop="price" content="{preco}" />
      <meta itemprop="priceCurrency" content="BRL" />
      <div class="parcela">ou 10x de R$ {_brl(parcela)} sem juros</div>
      <button class="comprar">Comprar agora</button>
    </div>
  </div>
</main>
<p class="aviso">
  Página gerada pelo próprio backend do NoPrecinhoBot para testes. O preço oscila
  ±{int(AMPLITUDE * 100)}% num ciclo de {PERIODO_SEGUNDOS // 60} minutos, então o scraper
  vê valores diferentes a cada coleta. Emoji do item: {meta.get("emoji", "📦")}
</p>
</body>
</html>"""


def _pagina_js(produto: DemoProduto) -> str:
    """HTML sem preço algum: quem preenche é o JavaScript, depois do carregamento."""
    nome = escape(produto.nome)
    imagem = f"{config.BASE_URL}/loja-demo/img/{produto.slug}.svg"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{nome} | TechPrecinho JS</title>
<meta property="og:site_name" content="TechPrecinho" />
<meta property="og:title" content="{nome}" />
<meta property="og:image" content="{imagem}" />
<style>
  body {{ margin:0; font-family:"Segoe UI",system-ui,sans-serif; background:#f1f5f9; color:#0f172a; }}
  header {{ background:#0f172a; color:#fff; padding:14px 24px; font-weight:700; }}
  header span {{ color:#38bdf8; }}
  main {{ max-width:840px; margin:28px auto; padding:0 20px; display:grid;
          grid-template-columns:minmax(0,300px) minmax(0,1fr); gap:28px; }}
  .foto {{ background:#fff; border-radius:16px; padding:16px; }}
  .foto img {{ width:100%; border-radius:10px; display:block; }}
  .caixa {{ background:#fff; border-radius:16px; padding:24px; }}
  .preco-final {{ font-size:38px; font-weight:800; color:#059669; }}
  .aviso {{ max-width:840px; margin:0 auto 28px; padding:14px 20px; font-size:13px;
            color:#78350f; background:#fef3c7; border:1px solid #fde68a; border-radius:12px; }}
</style>
</head>
<body>
<header>Tech<span>Precinho</span> — versão que monta o preço por JavaScript</header>
<main>
  <div class="foto"><img src="{imagem}" alt="{nome}" /></div>
  <div>
    <h1>{nome}</h1>
    <div class="caixa">
      <div class="preco-final" id="preco">carregando…</div>
      <div id="parcela"></div>
    </div>
  </div>
</main>
<p class="aviso">
  Nesta página o preço <strong>não existe no HTML</strong>: ele é buscado em
  <code>/api/demo/preco/{produto.slug}</code> e escrito na tela pelo JavaScript, como
  fazem Mercado Livre e Magazine Luiza. O scraper HTTP falha aqui de propósito; quem
  resolve é o fallback de navegador (<code>NAVEGADOR_FALLBACK=true</code>).
</p>
<script>
  // O atraso imita a latência de uma API real e garante que o preço não esteja
  // presente no DOMContentLoaded.
  setTimeout(async () => {{
    const r = await fetch('/api/demo/preco/{produto.slug}');
    const dados = await r.json();
    const formatado = Number(dados.preco).toLocaleString('pt-BR',
      {{ style: 'currency', currency: 'BRL' }});
    document.getElementById('preco').textContent = formatado;
    document.getElementById('parcela').textContent =
      'ou 10x de ' + (Number(dados.preco) / 10).toLocaleString('pt-BR',
        {{ style: 'currency', currency: 'BRL' }}) + ' sem juros';
  }}, 600);
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #
def _buscar(db: Session, slug: str) -> DemoProduto:
    produto = db.scalar(select(DemoProduto).where(DemoProduto.slug == slug))
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado na loja-demo.")
    return produto


def registrar_rotas(app, get_db) -> None:
    """Registra as rotas da loja-demo (chamado em main.py para evitar import circular)."""
    from fastapi import Depends

    @app.get("/loja-demo", response_class=HTMLResponse, tags=["loja-demo"])
    def vitrine(db: Session = Depends(get_db)) -> HTMLResponse:
        produtos = list(db.scalars(select(DemoProduto).order_by(DemoProduto.id)))
        cartoes = "".join(
            f"""
            <a class="card" href="/loja-demo/produto/{p.slug}">
              <img src="/loja-demo/img/{p.slug}.svg" alt="" />
              <strong>{escape(p.nome)}</strong>
              <span>R$ {_brl(preco_atual(p))}</span>
            </a>"""
            for p in produtos
        )
        return HTMLResponse(f"""<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TechPrecinho — loja de demonstração</title>
<style>
 body {{ margin:0; font-family:"Segoe UI",system-ui,sans-serif; background:#f1f5f9; color:#0f172a; }}
 header {{ background:#0f172a; color:#fff; padding:14px 24px; font-weight:700; }}
 header span {{ color:#38bdf8; }}
 p.intro {{ max-width:1000px; margin:24px auto 8px; padding:0 20px; color:#475569; }}
 .grade {{ max-width:1000px; margin:16px auto 48px; padding:0 20px; display:grid;
           grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:18px; }}
 .card {{ background:#fff; border-radius:14px; padding:14px; text-decoration:none; color:inherit;
          box-shadow:0 1px 3px rgba(0,0,0,.1); display:flex; flex-direction:column; gap:8px; }}
 .card:hover {{ transform:translateY(-2px); box-shadow:0 6px 18px rgba(0,0,0,.12); }}
 .card img {{ width:100%; border-radius:10px; }}
 .card strong {{ font-size:14px; line-height:1.35; font-weight:600; }}
 .card span {{ color:#059669; font-weight:800; font-size:19px; }}
</style></head><body>
<header>Tech<span>Precinho</span> — a loja de mentirinha do NoPrecinhoBot</header>
<p class="intro">Copie a URL de qualquer produto abaixo e cadastre no painel do NoPrecinhoBot.
Os preços oscilam sozinhos, então o histórico e os alertas funcionam ao vivo.</p>
<div class="grade">{cartoes}</div>
</body></html>""")

    @app.get("/loja-demo/produto/{slug}", response_class=HTMLResponse, tags=["loja-demo"])
    def pagina_produto(slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
        produto = _buscar(db, slug)
        return HTMLResponse(_pagina_produto(produto, preco_atual(produto)))

    @app.get("/loja-demo/js/{slug}", response_class=HTMLResponse, tags=["loja-demo"])
    def pagina_renderizada_por_js(slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
        """Mesma loja, mas o preço só aparece depois que o JavaScript roda.

        O HTML que sai daqui não contém preço nenhum — nem em JSON-LD, nem em meta
        tag, nem no corpo. Serve para demonstrar a diferença entre o scraper HTTP
        (que falha aqui, corretamente) e o fallback de navegador (que resolve).
        """
        produto = _buscar(db, slug)
        return HTMLResponse(_pagina_js(produto))

    @app.get("/api/demo/preco/{slug}", tags=["loja-demo"])
    def preco_via_api(slug: str, db: Session = Depends(get_db)) -> dict:
        """Endpoint que a página JS consulta — como fazem as lojas de verdade."""
        produto = _buscar(db, slug)
        return {"slug": slug, "preco": str(preco_atual(produto)), "moeda": "BRL"}

    @app.get("/loja-demo/img/{slug}.svg", tags=["loja-demo"])
    def imagem_produto(slug: str) -> Response:
        return Response(
            content=_svg_produto(slug),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )
