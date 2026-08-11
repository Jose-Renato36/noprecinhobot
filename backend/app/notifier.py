"""Envio de e-mail de alerta via Resend.

O envio é opcional em dois níveis: `EMAIL_ENABLED=false` desliga tudo, e mesmo
ligado, sem `RESEND_API_KEY` nada é enviado. Nos dois casos o alerta é gravado no
banco e aparece no painel — a falha de e-mail nunca derruba a coleta.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import requests

from .config import config

logger = logging.getLogger(__name__)

ENDPOINT_RESEND = "https://api.resend.com/emails"


def formatar_brl(valor: Decimal | float | None) -> str:
    if valor is None:
        return "—"
    return f"R$ {Decimal(str(valor)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_html(
    nome_produto: str,
    url_produto: str,
    preco_atual: Decimal,
    preco_alvo: Decimal,
    imagem_url: str | None = None,
) -> str:
    economia = Decimal(str(preco_alvo)) - Decimal(str(preco_atual))
    bloco_imagem = (
        f'<img src="{imagem_url}" alt="" width="180" '
        'style="border-radius:12px;display:block;margin:0 0 16px" />'
        if imagem_url
        else ""
    )
    return f"""\
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:auto;
            padding:24px;border:1px solid #e5e7eb;border-radius:16px;color:#111827">
  <p style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;
            color:#059669;margin:0 0 8px;font-weight:700">NoPrecinhoBot</p>
  <h1 style="font-size:22px;margin:0 0 16px">Baixou! O preço atingiu seu alvo 🎯</h1>
  {bloco_imagem}
  <p style="margin:0 0 4px;font-size:16px;font-weight:600">{nome_produto}</p>
  <p style="margin:0 0 20px;color:#6b7280;font-size:14px">
    Preço atual: <strong style="color:#059669;font-size:20px">{formatar_brl(preco_atual)}</strong><br />
    Seu preço-alvo era {formatar_brl(preco_alvo)}
    {f'(ficou {formatar_brl(economia)} abaixo)' if economia > 0 else ''}
  </p>
  <a href="{url_produto}"
     style="display:inline-block;background:#059669;color:#fff;text-decoration:none;
            padding:12px 20px;border-radius:10px;font-weight:600">Ver produto na loja</a>
  <p style="margin:24px 0 0;font-size:12px;color:#9ca3af">
    Você recebeu este e-mail porque cadastrou este produto no NoPrecinhoBot.
  </p>
</div>"""


def enviar_alerta_email(
    destinatario: str | None,
    nome_produto: str,
    url_produto: str,
    preco_atual: Decimal,
    preco_alvo: Decimal,
    imagem_url: str | None = None,
) -> bool:
    """Retorna True se o e-mail foi aceito pela Resend. Nunca levanta exceção."""
    if not config.EMAIL_ENABLED:
        # Desligado de propósito: nem loga como pendência, para não encher o log
        # de aviso a cada alerta de uma funcionalidade que ninguém pediu.
        return False

    destino = destinatario or config.EMAIL_DESTINO
    if not config.RESEND_API_KEY:
        logger.info("RESEND_API_KEY ausente — alerta registrado sem envio de e-mail.")
        return False
    if not destino:
        logger.info("Nenhum destinatário configurado (EMAIL_DESTINO) — e-mail não enviado.")
        return False

    payload = {
        "from": config.RESEND_FROM,
        "to": [destino],
        "subject": f"🔔 {nome_produto} está por {formatar_brl(preco_atual)}",
        "html": montar_html(nome_produto, url_produto, preco_atual, preco_alvo, imagem_url),
    }

    try:
        resposta = requests.post(
            ENDPOINT_RESEND,
            json=payload,
            headers={
                "Authorization": f"Bearer {config.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("Falha de rede ao enviar e-mail pela Resend: %s", exc)
        return False

    if resposta.status_code >= 300:
        logger.warning("Resend recusou o envio (HTTP %s): %s", resposta.status_code, resposta.text)
        return False

    logger.info("E-mail de alerta enviado para %s", destino)
    return True
