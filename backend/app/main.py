"""API do NoPrecinhoBot (FastAPI)."""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from . import demo_store, scheduler, schemas
from .auth import (
    apagar_cookie,
    conferir_senha,
    criar_token,
    gravar_cookie,
    hash_senha,
    usuario_atual,
)
from .config import config
from .limitador import (
    conferir_trava_de_login,
    limite_login,
    limite_registro,
    limite_scraping,
    trava_de_login,
)
from .database import SessionLocal, criar_tabelas, get_db
from .models import Alerta, DemoProduto, HistoricoPreco, Produto, StatusProduto, Usuario
from .monitor import coletar_produto, coletar_todos
from .scraper import ScraperError, raspar_produto

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("noprecinhobot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_tabelas()
    if config.DEMO_STORE_ENABLED:
        db = SessionLocal()
        try:
            novos = demo_store.semear_catalogo(db)
            if novos:
                logger.info("Loja-demo populada com %d produto(s).", novos)
        finally:
            db.close()

    scheduler.iniciar_agendador()
    yield
    scheduler.parar_agendador()


app = FastAPI(
    title="NoPrecinhoBot API",
    description=(
        "Monitoramento automático de preços: cadastro de produtos por URL, coleta "
        "periódica via scraper, histórico e alertas de queda de preço."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Montagem das respostas
# --------------------------------------------------------------------------- #
def _estatisticas_historico(db: Session, produto_ids: list[int]) -> dict[int, dict]:
    if not produto_ids:
        return {}
    linhas = db.execute(
        select(
            HistoricoPreco.produto_id,
            func.count(HistoricoPreco.id),
            func.min(HistoricoPreco.preco),
            func.max(HistoricoPreco.preco),
        )
        .where(HistoricoPreco.produto_id.in_(produto_ids))
        .group_by(HistoricoPreco.produto_id)
    ).all()
    return {
        pid: {
            "total": total,
            "menor": Decimal(str(menor)) if menor is not None else None,
            "maior": Decimal(str(maior)) if maior is not None else None,
        }
        for pid, total, menor, maior in linhas
    }


def _montar_produto(produto: Produto, stats: dict | None) -> schemas.ProdutoResposta:
    resposta = schemas.ProdutoResposta.model_validate(produto)
    stats = stats or {}
    resposta.total_coletas = stats.get("total", 0)
    resposta.menor_preco = stats.get("menor")
    resposta.maior_preco = stats.get("maior")

    if produto.preco_atual is not None:
        atual = Decimal(str(produto.preco_atual))
        resposta.distancia_do_alvo = (atual - Decimal(str(produto.preco_alvo))).quantize(
            Decimal("0.01")
        )
        if produto.preco_inicial:
            inicial = Decimal(str(produto.preco_inicial))
            if inicial > 0:
                resposta.variacao_percentual = float(
                    ((atual - inicial) / inicial * 100).quantize(Decimal("0.01"))
                )
    return resposta


def _buscar_produto(db: Session, produto_id: int, usuario: Usuario) -> Produto:
    """Busca o produto **e** confirma que ele pertence a quem pediu.

    Devolve 404 (não 403) quando o produto é de outra pessoa: responder "existe,
    mas não é seu" já entregaria que aquele id existe, permitindo mapear a base
    alheia por tentativa. Para quem não é dono, o produto simplesmente não existe.
    """
    produto = db.get(Produto, produto_id, options=[selectinload(Produto.usuario)])
    if produto is None or produto.usuario_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto não encontrado.")
    return produto


def _email_ativo() -> bool:
    """Só é 'ativo' quando ligado **e** com chave: as duas coisas precisam valer
    para um e-mail realmente sair."""
    return config.EMAIL_ENABLED and bool(config.RESEND_API_KEY)


# --------------------------------------------------------------------------- #
# Saúde e raiz
# --------------------------------------------------------------------------- #
@app.get("/api/health", tags=["sistema"])
def health() -> dict:
    return {
        "status": "ok",
        "agendador_ativo": scheduler.esta_ativo(),
        "intervalo_minutos": config.SCRAPE_INTERVAL_MINUTES,
        "email_ativo": _email_ativo(),
        "banco": "postgresql" if "postgresql" in config.DATABASE_URL else "sqlite",
    }


# --------------------------------------------------------------------------- #
# Autenticação
# --------------------------------------------------------------------------- #
def _resposta_token(usuario: Usuario, resposta: Response) -> schemas.TokenResposta:
    """Grava o cookie de sessão e devolve o token também no corpo.

    O painel usa só o cookie e ignora o `token` do corpo — ele existe para
    clientes que não são navegador (o `/docs`, curl, scripts), que não têm como
    aproveitar cookie httpOnly.
    """
    token = criar_token(usuario)
    gravar_cookie(resposta, token)
    return schemas.TokenResposta(
        token=token,
        expira_em_minutos=config.JWT_EXPIRA_MINUTOS,
        usuario=schemas.UsuarioResumo.model_validate(usuario),
    )


@app.post(
    "/api/auth/registrar",
    response_model=schemas.TokenResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
    dependencies=[Depends(limite_registro)],
)
def registrar(
    dados: schemas.UsuarioCriar, resposta: Response, db: Session = Depends(get_db)
):
    """Cria a conta e já devolve o token, para o painel não pedir login em seguida."""
    if not config.REGISTRO_ABERTO:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "O cadastro de novas contas está fechado."
        )

    email = str(dados.email).strip().lower()
    if db.scalar(select(Usuario).where(func.lower(Usuario.email) == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma conta com esse e-mail.")

    usuario = Usuario(nome=dados.nome.strip(), email=email, senha_hash=hash_senha(dados.senha))
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    logger.info("Conta criada: %s", email)
    return _resposta_token(usuario, resposta)


@app.post(
    "/api/auth/login",
    response_model=schemas.TokenResposta,
    tags=["auth"],
    dependencies=[Depends(limite_login)],
)
def login(dados: schemas.LoginPedido, resposta: Response, db: Session = Depends(get_db)):
    email = str(dados.email).strip().lower()

    # A trava por conta é conferida antes de tocar no banco: sob ataque, nem faz
    # sentido gastar consulta e verificação de hash (que é cara de propósito).
    conferir_trava_de_login(email)

    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))

    # Mesma mensagem para e-mail inexistente e senha errada: distinguir os dois
    # casos revelaria quais e-mails têm conta aqui.
    if usuario is None or not conferir_senha(dados.senha, usuario.senha_hash):
        # A falha é contada mesmo para e-mail inexistente. Contar só os que
        # existem faria o tempo de resposta denunciar quais contas são reais.
        trava_de_login.registrar_falha(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha incorretos.")

    trava_de_login.registrar_sucesso(email)
    return _resposta_token(usuario, resposta)


@app.post("/api/auth/sair", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
def sair(resposta: Response):
    """Apaga o cookie de sessão.

    Precisa existir no servidor justamente porque o cookie é httpOnly: o painel
    não consegue removê-lo por conta própria. Não exige autenticação — sair de
    uma sessão que já morreu não é erro, e pedir token aqui só produziria um 401
    inútil no caminho mais comum (token expirado).
    """
    apagar_cookie(resposta)


@app.get("/api/auth/eu", response_model=schemas.UsuarioResumo, tags=["auth"])
def quem_sou_eu(usuario: Usuario = Depends(usuario_atual)):
    """O painel chama isto no boot para saber se a sessão do cookie ainda vale."""
    return usuario


# --------------------------------------------------------------------------- #
# Produtos
# --------------------------------------------------------------------------- #
@app.post(
    "/api/produtos",
    response_model=schemas.ProdutoResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["produtos"],
    dependencies=[Depends(limite_scraping)],
)
def cadastrar_produto(
    dados: schemas.ProdutoCriar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    """Cadastra um produto a partir da URL.

    A primeira coleta acontece aqui: é ela que confirma que o link é válido e
    preenche nome, preço atual e imagem.
    """
    url = str(dados.url)
    # A duplicidade é checada dentro da conta: o mesmo link pode ser monitorado
    # por vários usuários, cada um com o seu preço-alvo.
    ja_existe = db.scalar(
        select(Produto).where(Produto.url == url, Produto.usuario_id == usuario.id)
    )
    if ja_existe is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Você já está monitorando esse produto."
        )

    try:
        raspado = raspar_produto(url)
    except ScraperError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    preco = raspado.preco
    assert preco is not None

    produto = Produto(
        nome=raspado.nome or "Produto sem nome",
        url=raspado.url_final or url,
        imagem_url=raspado.imagem_url,
        loja=raspado.loja,
        preco_alvo=dados.preco_alvo,
        preco_atual=preco,
        preco_inicial=preco,
        moeda=raspado.moeda,
        status=(
            StatusProduto.ALVO_ATINGIDO
            if preco <= dados.preco_alvo
            else StatusProduto.AGUARDANDO
        ),
        ultima_coleta_em=datetime.now(timezone.utc),
        usuario_id=usuario.id,
        seletor_preco=raspado.seletor,
        fonte_preco=raspado.fonte,
        perfil_http=raspado.perfil,
        confianca=round(raspado.confianca, 3),
    )
    db.add(produto)
    db.flush()
    db.add(HistoricoPreco(produto_id=produto.id, preco=preco, disponivel=raspado.disponivel))

    # Já nasce abaixo do alvo? Registra o alerta na hora.
    if preco <= dados.preco_alvo:
        from .notifier import enviar_alerta_email, formatar_brl

        email_enviado = enviar_alerta_email(
            destinatario=usuario.email,
            nome_produto=produto.nome,
            url_produto=produto.url,
            preco_atual=preco,
            preco_alvo=dados.preco_alvo,
            imagem_url=produto.imagem_url,
        )
        db.add(
            Alerta(
                produto_id=produto.id,
                preco_disparo=preco,
                preco_alvo=dados.preco_alvo,
                mensagem=(
                    f"{produto.nome} já está por {formatar_brl(preco)} — abaixo do seu "
                    f"alvo de {formatar_brl(dados.preco_alvo)}."
                ),
                email_enviado=email_enviado,
            )
        )

    db.commit()
    db.refresh(produto)
    return _montar_produto(produto, _estatisticas_historico(db, [produto.id]).get(produto.id))


@app.get("/api/produtos", response_model=list[schemas.ProdutoResposta], tags=["produtos"])
def listar_produtos(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
    status_filtro: StatusProduto | None = Query(default=None, alias="status"),
    busca: str | None = Query(default=None, max_length=120),
):
    consulta = (
        select(Produto)
        .options(selectinload(Produto.usuario))
        .where(Produto.usuario_id == usuario.id)
    )
    if status_filtro is not None:
        consulta = consulta.where(Produto.status == status_filtro)
    if busca:
        padrao = f"%{busca.strip()}%"
        consulta = consulta.where(Produto.nome.ilike(padrao))

    produtos = list(db.scalars(consulta.order_by(Produto.criado_em.desc())))
    stats = _estatisticas_historico(db, [p.id for p in produtos])
    return [_montar_produto(p, stats.get(p.id)) for p in produtos]


@app.get("/api/produtos/{produto_id}", response_model=schemas.ProdutoResposta, tags=["produtos"])
def obter_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    produto = _buscar_produto(db, produto_id, usuario)
    return _montar_produto(produto, _estatisticas_historico(db, [produto_id]).get(produto_id))


@app.patch("/api/produtos/{produto_id}", response_model=schemas.ProdutoResposta, tags=["produtos"])
def atualizar_produto(
    produto_id: int,
    dados: schemas.ProdutoAtualizar,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    produto = _buscar_produto(db, produto_id, usuario)

    if dados.nome is not None:
        produto.nome = dados.nome
    if dados.preco_alvo is not None:
        produto.preco_alvo = dados.preco_alvo
        # Mudar o alvo recalcula o status na hora, sem esperar a próxima coleta.
        if produto.status != StatusProduto.PAUSADO and produto.preco_atual is not None:
            produto.status = (
                StatusProduto.ALVO_ATINGIDO
                if Decimal(str(produto.preco_atual)) <= dados.preco_alvo
                else StatusProduto.AGUARDANDO
            )

    db.commit()
    db.refresh(produto)
    return _montar_produto(produto, _estatisticas_historico(db, [produto_id]).get(produto_id))


@app.post("/api/produtos/{produto_id}/pausar", response_model=schemas.ProdutoResposta, tags=["produtos"])
def pausar_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    produto = _buscar_produto(db, produto_id, usuario)
    produto.status = StatusProduto.PAUSADO
    db.commit()
    db.refresh(produto)
    return _montar_produto(produto, _estatisticas_historico(db, [produto_id]).get(produto_id))


@app.post("/api/produtos/{produto_id}/retomar", response_model=schemas.ProdutoResposta, tags=["produtos"])
def retomar_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    produto = _buscar_produto(db, produto_id, usuario)
    if produto.preco_atual is not None and Decimal(str(produto.preco_atual)) <= Decimal(
        str(produto.preco_alvo)
    ):
        produto.status = StatusProduto.ALVO_ATINGIDO
    else:
        produto.status = StatusProduto.AGUARDANDO
    db.commit()
    db.refresh(produto)
    return _montar_produto(produto, _estatisticas_historico(db, [produto_id]).get(produto_id))


@app.delete("/api/produtos/{produto_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["produtos"])
def remover_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    produto = _buscar_produto(db, produto_id, usuario)
    db.delete(produto)  # histórico e alertas caem junto (cascade)
    db.commit()


@app.post(
    "/api/produtos/{produto_id}/coletar",
    response_model=schemas.ResultadoColetaResposta,
    tags=["coleta"],
    dependencies=[Depends(limite_scraping)],
)
def coletar_agora(
    produto_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    """Coleta manual — o mesmo caminho que o agendador percorre, só que sob demanda."""
    produto = _buscar_produto(db, produto_id, usuario)
    resultado = coletar_produto(db, produto, forcar=True)
    return schemas.ResultadoColetaResposta(
        produto_id=resultado.produto_id,
        nome=resultado.nome,
        sucesso=resultado.sucesso,
        preco=float(resultado.preco) if resultado.preco is not None else None,
        alerta_gerado=resultado.alerta_gerado,
        email_enviado=resultado.email_enviado,
        erro=resultado.erro,
    )


@app.get("/api/produtos/{produto_id}/historico", response_model=schemas.HistoricoResposta, tags=["historico"])
def historico_do_produto(
    produto_id: int,
    limite: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    produto = _buscar_produto(db, produto_id, usuario)
    pontos = list(
        db.scalars(
            select(HistoricoPreco)
            .where(HistoricoPreco.produto_id == produto_id)
            .order_by(HistoricoPreco.coletado_em.desc())
            .limit(limite)
        )
    )
    pontos.reverse()  # do mais antigo para o mais recente, pronto para o gráfico

    precos = [Decimal(str(p.preco)) for p in pontos]
    media = (sum(precos) / len(precos)).quantize(Decimal("0.01")) if precos else None

    return schemas.HistoricoResposta(
        produto_id=produto_id,
        preco_alvo=Decimal(str(produto.preco_alvo)),
        pontos=[schemas.PontoHistorico.model_validate(p) for p in pontos],
        menor_preco=min(precos) if precos else None,
        maior_preco=max(precos) if precos else None,
        preco_medio=media,
    )


# --------------------------------------------------------------------------- #
# Coleta em lote
# --------------------------------------------------------------------------- #
@app.post(
    "/api/coletas/executar",
    response_model=schemas.RodadaResposta,
    tags=["coleta"],
    dependencies=[Depends(limite_scraping)],
)
def executar_rodada(
    incluir_pausados: bool = Query(default=False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    """Dispara manualmente a rodada que o agendador executaria.

    Limitada aos produtos de quem chamou — o botão do painel não pode virar um
    gatilho para raspar a lista inteira de todo mundo.
    """
    resumo_rodada = coletar_todos(
        db, incluir_pausados=incluir_pausados, usuario_id=usuario.id
    )
    return schemas.RodadaResposta(**resumo_rodada.to_dict())


@app.post(
    "/api/previa",
    response_model=schemas.PreviaProduto,
    tags=["produtos"],
    dependencies=[Depends(limite_scraping)],
)
def prever_produto(
    url: str = Body(..., embed=True), usuario: Usuario = Depends(usuario_atual)
):
    """Testa uma URL e devolve o que o scraper conseguiu extrair, sem cadastrar nada."""
    try:
        resultado = raspar_produto(url)
    except ScraperError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return schemas.PreviaProduto(
        nome=resultado.nome,
        preco=resultado.preco,
        imagem_url=resultado.imagem_url,
        loja=resultado.loja,
        moeda=resultado.moeda,
        disponivel=resultado.disponivel,
        fonte=resultado.fonte,
        confianca=resultado.confianca,
        fontes_concordantes=resultado.fontes_concordantes,
        perfil=resultado.perfil,
    )


@app.get("/api/lojas", response_model=list[schemas.SaudeLoja], tags=["painel"])
def saude_das_lojas(
    db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
):
    """Taxa de sucesso por loja.

    É o alarme de incêndio do scraper: quando uma loja muda o HTML, a taxa dela
    despenca e isso fica visível no painel em vez de passar semanas despercebido.
    """
    produtos = list(db.scalars(select(Produto).where(Produto.usuario_id == usuario.id)))
    por_loja: dict[str, list[Produto]] = {}
    for produto in produtos:
        por_loja.setdefault(produto.loja or "Desconhecida", []).append(produto)

    resposta: list[schemas.SaudeLoja] = []
    for loja, itens in por_loja.items():
        com_erro = sum(1 for p in itens if p.status == StatusProduto.ERRO)
        fontes = [p.fonte_preco for p in itens if p.fonte_preco]
        confiancas = [float(p.confianca) for p in itens if p.confianca is not None]
        coletas = [p.ultima_coleta_em for p in itens if p.ultima_coleta_em]
        resposta.append(
            schemas.SaudeLoja(
                loja=loja,
                total_produtos=len(itens),
                com_erro=com_erro,
                taxa_sucesso=round((len(itens) - com_erro) / len(itens), 3),
                fonte_predominante=Counter(fontes).most_common(1)[0][0] if fontes else None,
                confianca_media=round(sum(confiancas) / len(confiancas), 3) if confiancas else None,
                ultima_coleta_em=max(coletas) if coletas else None,
            )
        )
    return sorted(resposta, key=lambda s: (s.taxa_sucesso, -s.total_produtos))


# --------------------------------------------------------------------------- #
# Alertas
# --------------------------------------------------------------------------- #
@app.get("/api/alertas", response_model=list[schemas.AlertaResposta], tags=["alertas"])
def listar_alertas(
    apenas_nao_lidos: bool = Query(default=False),
    limite: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    # O alerta não guarda dono: ele o herda do produto, daí o join.
    consulta = (
        select(Alerta)
        .join(Alerta.produto)
        .options(selectinload(Alerta.produto))
        .where(Produto.usuario_id == usuario.id)
    )
    if apenas_nao_lidos:
        consulta = consulta.where(Alerta.lido.is_(False))
    alertas = list(db.scalars(consulta.order_by(Alerta.criado_em.desc()).limit(limite)))
    return [schemas.AlertaResposta.model_validate(a) for a in alertas]


def _buscar_alerta(db: Session, alerta_id: int, usuario: Usuario) -> Alerta:
    """Mesma regra do produto: alerta de outra pessoa responde 404, não 403."""
    alerta = db.get(Alerta, alerta_id, options=[selectinload(Alerta.produto)])
    if alerta is None or alerta.produto is None or alerta.produto.usuario_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta não encontrado.")
    return alerta


@app.post("/api/alertas/{alerta_id}/lido", response_model=schemas.AlertaResposta, tags=["alertas"])
def marcar_alerta_lido(
    alerta_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    alerta = _buscar_alerta(db, alerta_id, usuario)
    alerta.lido = True
    db.commit()
    db.refresh(alerta)
    return schemas.AlertaResposta.model_validate(alerta)


@app.post("/api/alertas/marcar-todos-lidos", tags=["alertas"])
def marcar_todos_lidos(
    db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
):
    # UPDATE ... WHERE id IN (subconsulta) porque nem todo banco aceita JOIN
    # direto num UPDATE; a subconsulta é o que garante o escopo por dono.
    meus_alertas = (
        select(Alerta.id)
        .join(Alerta.produto)
        .where(Produto.usuario_id == usuario.id, Alerta.lido.is_(False))
    )
    total = db.execute(
        update(Alerta)
        .where(Alerta.id.in_(meus_alertas.scalar_subquery()))
        .values(lido=True)
    ).rowcount
    db.commit()
    return {"marcados": total or 0}


@app.delete("/api/alertas/{alerta_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["alertas"])
def remover_alerta(
    alerta_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    db.delete(_buscar_alerta(db, alerta_id, usuario))
    db.commit()


# --------------------------------------------------------------------------- #
# Painel
# --------------------------------------------------------------------------- #
@app.get("/api/resumo", response_model=schemas.Resumo, tags=["painel"])
def resumo(db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    por_status = dict(
        db.execute(
            select(Produto.status, func.count(Produto.id))
            .where(Produto.usuario_id == usuario.id)
            .group_by(Produto.status)
        ).all()
    )
    produtos = list(db.scalars(select(Produto).where(Produto.usuario_id == usuario.id)))

    economia = Decimal("0.00")
    for p in produtos:
        if p.preco_atual is not None and p.preco_inicial is not None:
            diferenca = Decimal(str(p.preco_inicial)) - Decimal(str(p.preco_atual))
            if diferenca > 0:
                economia += diferenca

    return schemas.Resumo(
        total_produtos=len(produtos),
        aguardando=por_status.get(StatusProduto.AGUARDANDO, 0),
        alvo_atingido=por_status.get(StatusProduto.ALVO_ATINGIDO, 0),
        pausados=por_status.get(StatusProduto.PAUSADO, 0),
        com_erro=por_status.get(StatusProduto.ERRO, 0),
        alertas_nao_lidos=db.scalar(
            select(func.count(Alerta.id))
            .join(Alerta.produto)
            .where(Produto.usuario_id == usuario.id, Alerta.lido.is_(False))
        )
        or 0,
        total_coletas=db.scalar(
            select(func.count(HistoricoPreco.id))
            .join(HistoricoPreco.produto)
            .where(Produto.usuario_id == usuario.id)
        )
        or 0,
        economia_potencial=economia.quantize(Decimal("0.01")),
        ultima_coleta_em=db.scalar(select(func.max(Produto.ultima_coleta_em))),
        proxima_coleta_em=scheduler.proxima_execucao(),
        intervalo_minutos=config.SCRAPE_INTERVAL_MINUTES,
        agendador_ativo=scheduler.esta_ativo(),
        email_ativo=_email_ativo(),
    )


# As rotas /api/usuarios foram removidas: a listagem devolvia o nome e o e-mail
# de todo mundo para qualquer visitante, e a criação virou /api/auth/registrar,
# que é a única forma de nascer uma conta (lá a senha é obrigatória).


# --------------------------------------------------------------------------- #
# Loja de demonstração
# --------------------------------------------------------------------------- #
if config.DEMO_STORE_ENABLED:
    demo_store.registrar_rotas(app, get_db)

    @app.get("/api/demo/produtos", tags=["loja-demo"])
    def listar_demo(db: Session = Depends(get_db)):
        produtos = list(db.scalars(select(DemoProduto).order_by(DemoProduto.id)))
        return [
            {
                "slug": p.slug,
                "nome": p.nome,
                "url": f"{config.BASE_URL}/loja-demo/produto/{p.slug}",
                "imagem_url": f"{config.BASE_URL}/loja-demo/img/{p.slug}.svg",
                "preco_atual": float(demo_store.preco_atual(p)),
                "preco_base": float(p.preco_base),
                "em_promocao": float(p.fator_promocao or 1) < 1,
            }
            for p in produtos
        ]

    @app.post("/api/demo/promocao", tags=["loja-demo"])
    def aplicar_promocao(
        desconto: float = Query(default=0.35, ge=0.05, le=0.9),
        db: Session = Depends(get_db),
        usuario: Usuario = Depends(usuario_atual),
    ):
        """Derruba os preços da loja-demo para provocar alertas na apresentação."""
        db.execute(update(DemoProduto).values(fator_promocao=round(1 - desconto, 3)))
        db.commit()
        return {"mensagem": f"Promoção de {int(desconto * 100)}% aplicada na loja-demo."}

    @app.post("/api/demo/normalizar", tags=["loja-demo"])
    def normalizar_precos(
        db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
    ):
        db.execute(update(DemoProduto).values(fator_promocao=1.0))
        db.commit()
        return {"mensagem": "Preços da loja-demo voltaram ao normal."}

    @app.post("/api/demo/reiniciar", tags=["loja-demo"])
    def reiniciar_dados(
        db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
    ):
        """Zera o monitoramento **da própria conta**.

        Antes isto era um `DELETE` sem cláusula: um POST sem autenticação apagava
        os produtos, o histórico e os alertas de todos os usuários. Agora o
        estrago que alguém consegue fazer se limita à própria conta.
        """
        meus = select(Produto.id).where(Produto.usuario_id == usuario.id).scalar_subquery()
        db.execute(delete(Alerta).where(Alerta.produto_id.in_(meus)))
        db.execute(delete(HistoricoPreco).where(HistoricoPreco.produto_id.in_(meus)))
        db.execute(delete(Produto).where(Produto.usuario_id == usuario.id))
        db.execute(update(DemoProduto).values(fator_promocao=1.0))
        db.commit()
        return {"mensagem": "Seu monitoramento foi zerado."}


# --------------------------------------------------------------------------- #
# Frontend compilado (deploy tudo-em-um na Railway)
# --------------------------------------------------------------------------- #
if config.FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="frontend")
    logger.info("Servindo frontend compilado de %s", config.FRONTEND_DIST)
else:

    @app.get("/", include_in_schema=False)
    def raiz():
        return RedirectResponse("/docs")
