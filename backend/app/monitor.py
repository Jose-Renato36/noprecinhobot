"""Coração do sistema: coleta o preço, grava no histórico e decide o alerta."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config
from .models import Alerta, HistoricoPreco, Produto, StatusProduto
from .notifier import formatar_brl, enviar_alerta_email
from .scraper import Dica, ScraperError, raspar_produto

logger = logging.getLogger(__name__)


def _preco_e_confiavel(produto: Produto, novo: Decimal) -> str | None:
    """Barreira contra extração errada. Devolve o motivo da recusa, ou None.

    O erro clássico do scraper não é falhar — é acertar o número errado: pegar o
    valor da parcela ("10x de R$ 129,90"), o frete ou um produto relacionado. Sem
    esta checagem, o histórico é corrompido e um alerta falso é disparado.
    """
    anterior = produto.preco_atual
    if anterior is None:
        return None  # primeira coleta: não há com o que comparar

    anterior = Decimal(str(anterior))
    if anterior <= 0:
        return None

    fator = Decimal(str(config.VARIACAO_MAXIMA_FATOR))
    if novo > anterior * fator or novo * fator < anterior:
        return (
            f"Preço coletado ({formatar_brl(novo)}) destoa demais do anterior "
            f"({formatar_brl(anterior)}). A coleta foi descartada por segurança — "
            "provavelmente o scraper leu o valor errado na página."
        )
    return None


@dataclass
class ResultadoColeta:
    produto_id: int
    nome: str
    sucesso: bool
    preco: Decimal | None = None
    alerta_gerado: bool = False
    email_enviado: bool = False
    erro: str | None = None


@dataclass
class ResumoRodada:
    iniciada_em: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resultados: list[ResultadoColeta] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.resultados)

    @property
    def sucessos(self) -> int:
        return sum(1 for r in self.resultados if r.sucesso)

    @property
    def falhas(self) -> int:
        return self.total - self.sucessos

    @property
    def alertas(self) -> int:
        return sum(1 for r in self.resultados if r.alerta_gerado)

    def to_dict(self) -> dict:
        return {
            "iniciada_em": self.iniciada_em.isoformat(),
            "total": self.total,
            "sucessos": self.sucessos,
            "falhas": self.falhas,
            "alertas_gerados": self.alertas,
            "resultados": [
                {
                    "produto_id": r.produto_id,
                    "nome": r.nome,
                    "sucesso": r.sucesso,
                    "preco": float(r.preco) if r.preco is not None else None,
                    "alerta_gerado": r.alerta_gerado,
                    "email_enviado": r.email_enviado,
                    "erro": r.erro,
                }
                for r in self.resultados
            ],
        }


def coletar_produto(db: Session, produto: Produto, forcar: bool = False) -> ResultadoColeta:
    """Executa uma coleta para um produto e aplica as regras de alerta.

    `forcar=True` coleta mesmo com o monitoramento pausado (usado no botão
    "coletar agora" do painel).
    """
    if produto.status == StatusProduto.PAUSADO and not forcar:
        return ResultadoColeta(
            produto_id=produto.id, nome=produto.nome, sucesso=False, erro="Monitoramento pausado"
        )

    try:
        # Entrega ao scraper o que ele aprendeu na última coleta bem-sucedida.
        dados = raspar_produto(
            produto.url, Dica(seletor=produto.seletor_preco, perfil=produto.perfil_http)
        )
    except ScraperError as exc:
        produto.ultimo_erro = str(exc)
        if produto.status != StatusProduto.PAUSADO:
            produto.status = StatusProduto.ERRO
        produto.ultima_coleta_em = datetime.now(timezone.utc)
        db.commit()
        logger.warning("Falha ao coletar %s (%s): %s", produto.nome, produto.url, exc)
        return ResultadoColeta(
            produto_id=produto.id, nome=produto.nome, sucesso=False, erro=str(exc)
        )

    preco = dados.preco
    assert preco is not None  # raspar_produto garante o preço ou levanta ScraperError

    recusa = _preco_e_confiavel(produto, preco)
    if recusa is not None:
        produto.ultimo_erro = recusa
        produto.ultima_coleta_em = datetime.now(timezone.utc)
        if produto.status != StatusProduto.PAUSADO:
            produto.status = StatusProduto.ERRO
        # O seletor aprendido virou suspeito: esquece para forçar a cascata inteira
        # na próxima tentativa, em vez de repetir o mesmo erro para sempre.
        produto.seletor_preco = None
        db.commit()
        logger.warning("Coleta descartada em %s: %s", produto.nome, recusa)
        return ResultadoColeta(
            produto_id=produto.id, nome=produto.nome, sucesso=False, erro=recusa
        )

    # Cada coleta gera um registro no histórico.
    db.add(
        HistoricoPreco(
            produto_id=produto.id, preco=preco, disponivel=dados.disponivel
        )
    )

    # Memória do scraper para a próxima rodada.
    produto.seletor_preco = dados.seletor or produto.seletor_preco
    produto.fonte_preco = dados.fonte
    produto.perfil_http = dados.perfil or produto.perfil_http
    produto.confianca = round(dados.confianca, 3)

    estava_acima_do_alvo = produto.status != StatusProduto.ALVO_ATINGIDO

    produto.preco_atual = preco
    if produto.preco_inicial is None:
        produto.preco_inicial = preco
    if dados.imagem_url and not produto.imagem_url:
        produto.imagem_url = dados.imagem_url
    if dados.moeda:
        produto.moeda = dados.moeda
    produto.ultima_coleta_em = datetime.now(timezone.utc)
    produto.ultimo_erro = None

    alvo_atingido = preco <= Decimal(str(produto.preco_alvo))
    gerou_alerta = False
    email_enviado = False

    if produto.status != StatusProduto.PAUSADO:
        produto.status = (
            StatusProduto.ALVO_ATINGIDO if alvo_atingido else StatusProduto.AGUARDANDO
        )

    # O alerta só nasce na *transição* para "alvo atingido" — assim uma promoção
    # que dura vários dias não gera um e-mail a cada coleta.
    if alvo_atingido and estava_acima_do_alvo:
        mensagem = (
            f"{produto.nome} está por {formatar_brl(preco)} — seu preço-alvo era "
            f"{formatar_brl(produto.preco_alvo)}."
        )
        destinatario = produto.usuario.email if produto.usuario else None
        email_enviado = enviar_alerta_email(
            destinatario=destinatario,
            nome_produto=produto.nome,
            url_produto=produto.url,
            preco_atual=preco,
            preco_alvo=Decimal(str(produto.preco_alvo)),
            imagem_url=produto.imagem_url,
        )
        db.add(
            Alerta(
                produto_id=produto.id,
                preco_disparo=preco,
                preco_alvo=produto.preco_alvo,
                mensagem=mensagem,
                email_enviado=email_enviado,
            )
        )
        gerou_alerta = True
        logger.info("ALERTA: %s", mensagem)

    db.commit()

    return ResultadoColeta(
        produto_id=produto.id,
        nome=produto.nome,
        sucesso=True,
        preco=preco,
        alerta_gerado=gerou_alerta,
        email_enviado=email_enviado,
    )


def coletar_todos(db: Session, incluir_pausados: bool = False) -> ResumoRodada:
    """Rodada completa do scraper — é isto que o agendador/cron dispara."""
    consulta = select(Produto)
    if not incluir_pausados:
        consulta = consulta.where(Produto.status != StatusProduto.PAUSADO)

    produtos = list(db.scalars(consulta.order_by(Produto.id)))
    resumo = ResumoRodada()

    logger.info("Iniciando rodada de coleta em %d produto(s).", len(produtos))
    for indice, produto in enumerate(produtos):
        resumo.resultados.append(coletar_produto(db, produto))
        # Educação com as lojas: um respiro entre requisições.
        if config.SCRAPER_DELAY_SEGUNDOS > 0 and indice < len(produtos) - 1:
            time.sleep(config.SCRAPER_DELAY_SEGUNDOS)

    logger.info(
        "Rodada concluída: %d ok, %d falha(s), %d alerta(s).",
        resumo.sucessos,
        resumo.falhas,
        resumo.alertas,
    )
    return resumo
