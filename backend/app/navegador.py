"""Fallback de navegador headless para lojas que montam o preço por JavaScript.

Entra em ação sozinho: se o Playwright estiver instalado, é usado como último
recurso quando todas as tentativas por HTTP falham. Não é preciso ligar nada
(`NAVEGADOR_FALLBACK=auto`, o padrão). Sem o Playwright, o scraper segue só com
HTTP, sem erro.

Limite conhecido e medido: isto **não** vence antibot. Magazine Luiza, Mercado
Livre e Shopee detectam o Chromium automatizado e seguem bloqueando. O que este
módulo resolve é o outro problema — a loja que responde normalmente mas só
preenche o preço depois que o JavaScript roda.

Para não desperdiçar ~20 s por produto em loja que nunca vai funcionar, há duas
travas: domínios onde o navegador já tentou e não achou preço são pulados, e
falhas seguidas ao abrir o navegador desligam o fallback no processo inteiro.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from urllib.parse import urlparse

from .config import config

logger = logging.getLogger(__name__)

# Uma coleta por vez: cada navegador consome bastante memória, e a rodada é
# sequencial mesmo.
_trava = threading.Lock()

# Domínios em que o navegador já rodou e mesmo assim não trouxe preço.
_dominios_sem_sucesso: set[str] = set()

_falhas_ao_abrir = 0
_MAX_FALHAS = 2

# Remove os sinais mais óbvios de automação. Ajuda com verificações simples;
# não engana Cloudflare, Akamai e afins.
ANTI_DETECCAO = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = { runtime: {} };
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _modo() -> str:
    """`auto` (padrão), `sempre` ou `nunca`, a partir de NAVEGADOR_FALLBACK."""
    valor = config.NAVEGADOR_FALLBACK
    if isinstance(valor, bool):
        return "sempre" if valor else "nunca"
    texto = str(valor).strip().lower()
    if texto in {"0", "false", "no", "nao", "não", "off"}:
        return "nunca"
    if texto in {"1", "true", "yes", "sim", "on"}:
        return "sempre"
    return "auto"


@lru_cache(maxsize=1)
def _playwright_instalado() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def disponivel() -> bool:
    modo = _modo()
    if modo == "nunca" or _falhas_ao_abrir >= _MAX_FALHAS:
        return False
    return _playwright_instalado()


def _dominio(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def registrar_sem_preco(url: str) -> None:
    """O navegador abriu a página e mesmo assim não havia preço.

    Quase sempre significa antibot ou URL que não é de produto. Marcar o domínio
    evita gastar mais 20 s por produto na próxima rodada.
    """
    dominio = _dominio(url)
    if dominio and dominio not in _dominios_sem_sucesso:
        _dominios_sem_sucesso.add(dominio)
        logger.info(
            "Navegador não achou preço em %s — o domínio será pulado no fallback "
            "até a API reiniciar.",
            dominio,
        )


def renderizar(url: str) -> tuple[str, str] | None:
    """Abre a página num navegador real e devolve (html_renderizado, url_final).

    Retorna None quando o fallback está indisponível, o domínio já se mostrou
    inútil ou o navegador não conseguiu abrir a página — nunca levanta exceção,
    para não derrubar a rodada de coleta.
    """
    global _falhas_ao_abrir

    if not disponivel():
        return None
    if _dominio(url) in _dominios_sem_sucesso:
        logger.debug("Fallback pulado em %s (domínio já falhou antes).", url)
        return None

    from playwright.sync_api import sync_playwright

    with _trava:
        try:
            with sync_playwright() as p:
                navegador = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                try:
                    contexto = navegador.new_context(
                        locale="pt-BR",
                        timezone_id="America/Sao_Paulo",
                        viewport={"width": 1366, "height": 768},
                        user_agent=USER_AGENT,
                    )
                    contexto.add_init_script(ANTI_DETECCAO)
                    pagina = contexto.new_page()
                    pagina.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=config.NAVEGADOR_TIMEOUT_MS,
                    )
                    try:
                        pagina.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

                    # `networkidle` não basta: uma página sem requisições pendentes
                    # ainda pode preencher o preço num setTimeout. O sinal certo é
                    # o preço aparecer no texto visível — esperamos por ele.
                    try:
                        pagina.wait_for_function(
                            r"() => /R\$\s*\d|\d+[.,]\d{2}/.test(document.body.innerText)",
                            timeout=config.NAVEGADOR_ESPERA_PRECO_MS,
                        )
                    except Exception:
                        # Sem sinal de preço: devolve o que houver e deixa o
                        # extrator tentar (pode estar em JSON embutido, não na tela).
                        logger.debug("Nenhum preço visível apareceu em %s", url)

                    _falhas_ao_abrir = 0
                    return pagina.content(), pagina.url
                finally:
                    navegador.close()
        except Exception as exc:
            _falhas_ao_abrir += 1
            if _falhas_ao_abrir >= _MAX_FALHAS:
                logger.warning(
                    "Navegador falhou %d vezes seguidas (%s). Fallback desligado neste "
                    "processo — falta rodar `playwright install chromium`?",
                    _falhas_ao_abrir,
                    exc,
                )
            else:
                logger.warning("Fallback de navegador falhou em %s: %s", url, exc)
            return None
