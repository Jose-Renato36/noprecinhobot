"""Proteção contra abuso: limite de requisições e trava de força bruta no login.

Duas defesas diferentes, porque os ataques são diferentes:

1. **Limite por IP** segura quem martela a API — muitas tentativas de senha,
   cadastro em massa de contas, uso do scraper como serviço de download alheio.
2. **Trava por e-mail** segura o ataque distribuído contra *uma* conta, em que
   cada tentativa vem de um IP diferente e nenhum limite por IP dispara.

O estado vive em memória, de propósito: com uma instância só na Railway isso
basta, e evita arrastar Redis para dentro do projeto. O preço é que, escalando
para várias instâncias, cada uma passa a contar em separado — o limite efetivo
vira N vezes o configurado. Está documentado no README; o dia em que houver mais
de uma instância, o caminho é trocar o miolo destas classes por um armazenamento
compartilhado, sem mexer nas rotas.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from .config import config

logger = logging.getLogger(__name__)

# Acima disto, faz-se uma varredura para descartar chaves que já expiraram. Sem
# isso, um atacante variando o IP faria os dicionários crescerem sem fim — o
# limitador viraria o próprio vetor de ataque.
LIMITE_PARA_LIMPEZA = 2048


def ip_do_cliente(request: Request) -> str:
    """Descobre o IP real de quem chamou.

    Atrás de um proxy, `request.client.host` é o IP do proxy: limitar por ele
    colocaria todos os usuários no mesmo balde. O proxy anexa quem se conectou a
    ele no fim do `X-Forwarded-For`, então com N proxies confiáveis o cliente é o
    N-ésimo da direita para a esquerda.

    Confiar no cabeçalho sem proxy na frente é pior que não limitar: qualquer um
    forja o valor e escapa do limite trocando de "IP" a cada requisição. Por isso
    `CONFIAR_PROXIES` é explícito, e vale 0 quando a API está exposta direto.
    """
    confiaveis = config.CONFIAR_PROXIES
    if confiaveis > 0:
        encaminhado = request.headers.get("x-forwarded-for", "")
        saltos = [parte.strip() for parte in encaminhado.split(",") if parte.strip()]
        if saltos:
            # Se vieram menos saltos que o esperado, o mais à esquerda é o mais
            # próximo do cliente que dá para confiar.
            indice = max(0, len(saltos) - confiaveis)
            return saltos[indice]

    return request.client.host if request.client else "desconhecido"


class JanelaDeslizante:
    """Conta eventos por chave dentro de uma janela de tempo móvel.

    Janela deslizante e não contador por bloco fixo: no bloco fixo, quem dispara
    tudo no fim de um bloco e tudo no início do seguinte passa o dobro do limite
    em poucos segundos.
    """

    def __init__(self, maximo: int, janela_segundos: float) -> None:
        self.maximo = maximo
        self.janela = janela_segundos
        self._eventos: dict[str, deque[float]] = defaultdict(deque)
        self._trava = threading.Lock()

    def _expirar(self, marcas: deque[float], agora: float) -> None:
        while marcas and marcas[0] <= agora - self.janela:
            marcas.popleft()

    def _limpar(self, agora: float) -> None:
        vazias = [chave for chave, marcas in self._eventos.items() if not marcas]
        for chave in vazias:
            del self._eventos[chave]

    def registrar(self, chave: str) -> float:
        """Contabiliza uma tentativa. Devolve 0 se liberado, ou os segundos de espera."""
        agora = time.monotonic()
        with self._trava:
            if len(self._eventos) > LIMITE_PARA_LIMPEZA:
                self._limpar(agora)

            marcas = self._eventos[chave]
            self._expirar(marcas, agora)

            if len(marcas) >= self.maximo:
                # A vaga só abre quando a tentativa mais antiga sair da janela.
                return max(1.0, round(marcas[0] + self.janela - agora, 1))

            marcas.append(agora)
            return 0.0

    def esquecer(self, chave: str) -> None:
        """Zera a contagem — usado quando o login dá certo."""
        with self._trava:
            self._eventos.pop(chave, None)


class TravaDeLogin:
    """Tranca uma conta por um tempo depois de seguidas senhas erradas.

    O bloqueio dobra a cada nova rodada de falhas (1x, 2x, 4x…), até um teto.
    Assim uma pessoa que errou a senha duas vezes mal percebe, enquanto quem está
    varrendo senhas é empurrado para uma espera que inviabiliza o ataque.

    Efeito colateral conhecido: dá para trancar de propósito a conta de outra
    pessoa errando a senha dela. É o motivo de o bloqueio ser em minutos e não em
    horas — o incômodo passa, e sem ele a conta ficaria exposta a força bruta.
    """

    def __init__(self, maximo_falhas: int, bloqueio_base: float, bloqueio_teto: float) -> None:
        self.maximo_falhas = maximo_falhas
        self.bloqueio_base = bloqueio_base
        self.bloqueio_teto = bloqueio_teto
        self._falhas: dict[str, int] = defaultdict(int)
        self._liberado_em: dict[str, float] = {}
        self._trava = threading.Lock()

    def espera(self, chave: str) -> float:
        """Segundos que ainda faltam para a conta destravar (0 se liberada)."""
        with self._trava:
            liberado = self._liberado_em.get(chave)
            if liberado is None:
                return 0.0
            restante = liberado - time.monotonic()
            if restante <= 0:
                # Cumpriu a pena: a contagem recomeça, mas guardamos o nível de
                # bloqueio para que reincidência já pegue uma espera maior.
                del self._liberado_em[chave]
                return 0.0
            return round(restante, 1)

    def registrar_falha(self, chave: str) -> float:
        """Anota uma senha errada. Devolve o bloqueio aplicado, ou 0."""
        with self._trava:
            if len(self._falhas) > LIMITE_PARA_LIMPEZA:
                agora = time.monotonic()
                antigas = [
                    c for c, quando in self._liberado_em.items() if quando + 3600 < agora
                ]
                for c in antigas:
                    self._liberado_em.pop(c, None)
                    self._falhas.pop(c, None)

            self._falhas[chave] += 1
            if self._falhas[chave] < self.maximo_falhas:
                return 0.0

            rodadas = self._falhas[chave] // self.maximo_falhas
            duracao = min(self.bloqueio_base * (2 ** (rodadas - 1)), self.bloqueio_teto)
            self._liberado_em[chave] = time.monotonic() + duracao
            logger.warning(
                "Conta %s bloqueada por %.0fs após %d senha(s) incorreta(s).",
                chave,
                duracao,
                self._falhas[chave],
            )
            return duracao

    def registrar_sucesso(self, chave: str) -> None:
        with self._trava:
            self._falhas.pop(chave, None)
            self._liberado_em.pop(chave, None)


def _recusar(espera: float, detalhe: str) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detalhe,
        # Retry-After é o que permite a um cliente bem-comportado esperar o
        # tempo certo em vez de continuar tentando e afundar o próprio limite.
        headers={"Retry-After": str(int(espera) + 1)},
    )


def limite_por_ip(maximo: int, janela_segundos: float, mensagem: str):
    """Cria uma dependência do FastAPI que limita a rota por IP de origem."""
    janela = JanelaDeslizante(maximo, janela_segundos)

    def dependencia(request: Request) -> None:
        if not config.RATE_LIMIT_ENABLED:
            return
        espera = janela.registrar(ip_do_cliente(request))
        if espera:
            raise _recusar(espera, mensagem)

    dependencia.janela = janela  # exposto para os testes zerarem o estado
    return dependencia


# Instâncias usadas pelas rotas. Ficam no módulo (e não dentro das funções) para
# que o estado sobreviva entre requisições.
trava_de_login = TravaDeLogin(
    maximo_falhas=config.LOGIN_MAX_FALHAS,
    bloqueio_base=config.LOGIN_BLOQUEIO_SEGUNDOS,
    bloqueio_teto=config.LOGIN_BLOQUEIO_TETO_SEGUNDOS,
)

limite_login = limite_por_ip(
    config.LIMITE_LOGIN,
    config.LIMITE_LOGIN_JANELA,
    "Muitas tentativas de login. Aguarde um pouco e tente de novo.",
)

limite_registro = limite_por_ip(
    config.LIMITE_REGISTRO,
    config.LIMITE_REGISTRO_JANELA,
    "Muitas contas criadas a partir deste endereço. Tente mais tarde.",
)

# O scraper faz requisição de saída a cada chamada: sem limite, a API vira um
# serviço de download por conta alheia, e a conta da Railway paga por isso.
limite_scraping = limite_por_ip(
    config.LIMITE_SCRAPING,
    config.LIMITE_SCRAPING_JANELA,
    "Muitas coletas seguidas. Aguarde alguns instantes.",
)


def conferir_trava_de_login(email: str) -> None:
    espera = trava_de_login.espera(email)
    if espera:
        raise _recusar(
            espera,
            f"Conta temporariamente bloqueada por tentativas incorretas. "
            f"Tente novamente em {int(espera) + 1}s.",
        )
