# 🏷️ NoPrecinhoBot

**Sistema de Monitoramento Automático de Preços** — atividade acadêmica.

O usuário cadastra um produto a partir de uma URL e define um preço-alvo. Um processo
automático (scraper) revisita cada produto periodicamente, registra o preço no histórico e,
quando o valor atinge o alvo, dispara um alerta.

**Integrantes:** José Renato · João Pedro · Tiago Ferrari · Jean Lucas · Pedro Henrique

---

## Como rodar

Tudo roda na sua máquina: API em Python, painel em React e um arquivo SQLite como
banco. Não há serviço externo para configurar.

Precisa de **Python 3.11+** e **Node.js 18+**.

### 1. Backend (API + scraper + agendador)

Windows:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Linux / macOS: igual, trocando a ativação por `source .venv/bin/activate`.

Sobe em <http://127.0.0.1:8000> — documentação interativa em <http://127.0.0.1:8000/docs>.
Os dados ficam em `backend/noprecinho.db`, criado sozinho no primeiro início.

Opcional: `playwright install chromium` baixa o navegador (~150 MB) usado como último recurso
em lojas que montam o preço por JavaScript. Sem ele o scraper funciona igual, só sem essa
camada — ela se desliga sozinha.

Opcional: `copy .env.example .env` (ou `cp`) para ajustar o intervalo de coleta e o
comportamento do scraper. Veja [Configuração](#configuração).

### 2. Frontend (painel React)

Em outro terminal:

```bash
cd frontend
npm install
npm run dev
```

Abra <http://localhost:5173> e pronto — o painel abre direto, sem login. O Vite repassa `/api` para o backend,
então não há URL de API para configurar.

### 3. Rodar os testes

```bash
cd backend
python -m pytest
```

---

## Como demonstrar em 1 minuto

As lojas reais (Amazon, Mercado Livre, Magalu) respondem **HTTP 403** para robôs, o que
inviabiliza uma apresentação ao vivo confiável. Por isso o backend serve a **TechPrecinho**,
uma loja fictícia em <http://127.0.0.1:8000/loja-demo>: são páginas HTML de verdade, com
JSON-LD e OpenGraph, cujo preço oscila ±12% num ciclo de 10 minutos. O scraper acessa por
HTTP igual a qualquer outra loja — nada é simulado do lado dele.

1. No painel, abra a aba **Loja de teste** e copie o link de um produto.
2. Cole na aba **Minha lista**: o scraper busca o produto na hora e sugere um preço-alvo 10%
   abaixo do atual. Clique em **Adicionar à minha lista**.
3. Clique em **Verificar agora** algumas vezes: o histórico cresce e o gráfico se forma.
4. Clique em **Derrubar preços 40%** na aba Loja de teste e verifique de novo — o alerta
   dispara, o card muda de cor e o aviso aparece na aba **Avisos**.

O produto também é monitorado sozinho: o agendador roda no intervalo definido em
`SCRAPE_INTERVAL_MINUTES` (o padrão é 360 = 6 horas, como pede a especificação; o
`.env.example` vem com 3 minutos para dar para ver acontecendo).

---

## Arquitetura

| Camada | Tecnologia | Papel |
| --- | --- | --- |
| Frontend | React 18 + Vite + CSS | Cadastro, painel, histórico e alertas |
| Backend / API | Python + FastAPI | CRUD de produto, coleta, histórico, alertas |
| Scraper | BeautifulSoup + curl_cffi | Extrai nome, preço e imagem; se adapta ao HTML da loja |
| Agendador | APScheduler | Dispara a coleta periodicamente, dentro do processo da API |
| Banco | SQLite | Produtos, histórico e alertas |

```
React (Vite) ──/api──▶  FastAPI  ──▶  scraper (BeautifulSoup)  ──▶  página da loja
                           │                    │
                           │                    ▼
                           │            histórico + comparação com o alvo
                           ▼                    │
                         SQLite  ◀──────────────┘  alerta (aparece no painel)
                           ▲
            APScheduler ───┘  dispara a coleta a cada N minutos
```

### Estrutura de pastas

```
noprecinhobot/
├── backend/
│   ├── app/
│   │   ├── main.py        API FastAPI (rotas)
│   │   ├── models.py      Produto, HistoricoPreco, Alerta
│   │   ├── schemas.py     Contratos de entrada/saída (Pydantic)
│   │   ├── scraper.py     Extração adaptativa de nome/preço/imagem
│   │   ├── monitor.py     Coleta + regras de alerta
│   │   ├── scheduler.py   Agendador interno (APScheduler)
│   │   ├── navegador.py   Fallback de navegador (Playwright), opcional
│   │   ├── demo_store.py  Loja fictícia TechPrecinho
│   │   ├── database.py    Engine e sessão do SQLAlchemy
│   │   └── config.py      Configuração por variáveis de ambiente
│   └── tests/             Scraper, regras de alerta e rotas da API
└── frontend/
    └── src/
        ├── App.jsx        Estado e navegação por abas
        ├── api.js         Chamadas à API
        ├── styles.css     Estilo (claro e escuro)
        └── components/    Formulário, cards, gráfico, alertas, loja-demo
```

### Entidades

- **Produto** — nome, URL, imagem, loja, preço-alvo, preço atual, preço inicial e status
  (`aguardando`, `alvo_atingido`, `pausado`, `erro`). Guarda também a memória do scraper:
  qual seletor, qual fonte e qual perfil de navegador funcionaram na última coleta.
- **HistoricoPreco** — um registro por coleta: produto, preço, data/hora.
- **Alerta** — gerado quando o preço atinge o alvo: preço de disparo, alvo, mensagem, se já
  foi lido.

A especificação trazia **Usuário** como entidade opcional. Como o sistema roda na máquina de
quem usa, há uma lista só e nenhum login.

### O scraper adaptativo

Três mecanismos fazem o scraper funcionar em loja real e se manter funcionando quando
a loja muda.

#### 1. Impersonação de navegador

Lojas grandes não olham o `User-Agent` — olham a impressão digital do handshake TLS/HTTP2
(JA3). O `requests` tem uma assinatura que grita "sou um script Python" e leva 403 antes de
qualquer header ser lido. A [`curl_cffi`](https://github.com/lexiforest/curl_cffi) reproduz o
handshake de um navegador real.

O detalhe que só aparece testando: **o perfil que funciona muda de loja para loja.**

| Loja | chrome | edge | safari | firefox |
| --- | --- | --- | --- | --- |
| Amazon | 403 (desafio) | ✅ | ✅ | 403 |
| Magazine Luiza | 200 | 403 | 403 | 200 |
| Mercado Livre | 200 | 200 | 200 | 200 |
| KaBuM | ✅ | ✅ | ✅ | ✅ |

Por isso o scraper testa os perfis em sequência e **guarda qual funcionou** para aquele
domínio (`Produto.perfil_http`) — a segunda coleta já vai direto no certo. E o critério de
sucesso é ter *extraído o preço*, não ter recebido HTTP 200: sites com antibot devolvem 200
com uma página de desafio vazia.

#### 2. Consenso entre fontes, em vez de cascata

Seis estratégias rodam **todas**, cada uma produzindo candidatos com um peso:

| Fonte | Peso | O que é |
| --- | --- | --- |
| Seletor aprendido | 1,10 | caminho CSS que já funcionou neste produto |
| JSON-LD | 0,95 | `schema.org/Product` |
| Microdata | 0,85 | `itemprop="price"` |
| Seletor da loja | 0,80 | regra específica (Amazon, Magalu, KaBuM…) |
| Meta tags | 0,75 | OpenGraph / Twitter |
| JSON embutido | 0,70 | `__NEXT_DATA__`, `__PRELOADED_STATE__` e afins |
| Varredura | 0,45 | regex `R$ ...` em elementos com cara de preço |

Os pesos são somados **por valor** e o maior vence. Isso resolve um caso comum e traiçoeiro:
a loja bota o produto em promoção mas esquece de atualizar o JSON-LD. O preço velho aparece
em uma fonte (0,95); o novo aparece em três (0,75 + 0,70 + 0,45 = 1,90) e ganha.

A confiança do resultado vai junto para o painel: fonte estruturada sozinha fica em ~80%,
duas fontes concordando chegam a 100%, e a varredura sozinha fica em 37% — que é honesto,
ela adivinha.

#### 3. Memória de seletor (o auto-conserto)

Quando um preço é confirmado, o scraper **procura aquele valor no DOM** e guarda o caminho
CSS mais curto que o identifica (`Produto.seletor_preco`). Na coleta seguinte tenta esse
caminho primeiro — é rápido e não depende de nada.

Se a loja trocar o layout, o caminho deixa de existir, a cascata inteira assume e um caminho
novo é aprendido. Ninguém precisa reescrever código.

Classes geradas por CSS-in-JS (`css-1x2y3z`, `sc-fjdhpX`) mudam a cada build da loja, então
são descartadas na hora de montar o caminho — só entram classes estáveis.

#### 4. Barreira contra extração errada

O erro perigoso do scraper não é falhar — é acertar o número errado: ler `10x de R$ 129,90`
e gravar 129,90 como preço do produto. Isso corromperia o histórico e dispararia alerta
falso.

Toda coleta compara o valor novo com o anterior. Se saltar mais que `VARIACAO_MAXIMA_FATOR`
(padrão 4x) para cima ou para baixo, a coleta é **descartada**, o produto vai para `erro` com
a explicação, e o seletor aprendido é esquecido — para não repetir o mesmo engano. Promoção
de -50% passa normalmente; "preço" que virou 1/10 do anterior, não.

### O que funciona hoje, de fato

Testado contra as lojas reais:

| Loja | Resultado |
| --- | --- |
| **Amazon** | ✅ R$ 4.699,90 — perfil `edge`, seletor da loja (era 403 antes da impersonação) |
| **KaBuM** | ✅ R$ 94,90 — JSON-LD, confiança 79% |
| **books.toscrape.com** | ✅ R$ 51,77 — varredura, confiança 37% |
| **Loja-demo** | ✅ 4 fontes concordando, confiança 100% |
| **Mercado Livre** | ❌ bloqueado por antibot |
| **Magazine Luiza** | ❌ bloqueado por antibot |
| **Shopee** | ❌ bloqueada por antibot |

### Por que Mercado Livre, Magalu e Shopee não funcionam

Vale registrar porque a resposta não é "faltou tentar". Foi tudo testado:

| Tentativa | Mercado Livre | Magazine Luiza | Shopee |
| --- | --- | --- | --- |
| 4 perfis de TLS (`curl_cffi`) | desvia para `/gz/account-verification` | 403 ou desafio JS | 200, mas é shell de SPA sem preço |
| Sessão com cookies da home | 7k, sem preço | home dá 403 | — |
| `Referer` do Google | sem efeito | sem efeito | — |
| Variações de caminho da URL | — | os caminhos livres servem só a página 404 | — |
| API interna / oficial | 401/403 — exige token OAuth | não tem | 403, erro `90309999` |
| Playwright Chromium headless | interstício de verificação | "Não é possível acessar a página" | SPA nunca renderiza |
| Playwright Edge headless | idem | idem | — |
| Playwright Edge **com janela** | carrega o bundle, nunca renderiza | idem | — |

O que cada uma faz:

- **Magazine Luiza** usa um antibot ("Powered and protected by Privacy") que devolve um
  desafio em JavaScript ofuscado e só libera depois de validar o resultado.
- **Mercado Livre** faz fingerprint de dispositivo por JavaScript e desvia para uma
  verificação de conta. Com Edge em janela a página até carrega 208 kB, mas é só o bundle de
  CSS/JS: o conteúdo nunca aparece.
- **Shopee** é os dois problemas somados: SPA que renderiza tudo no cliente **e** antibot na
  API interna. O navegador headless carrega a casca, a API recusa a chamada e a tela fica
  vazia para sempre.

O padrão é o mesmo nos três: não é uma questão de layout ou de seletor, é bloqueio
deliberado. Passar disso exigiria proxies residenciais rotativos, serviço pago de scraping
(ScraperAPI, Zyte) ou API oficial com OAuth — fora do escopo de um trabalho acadêmico. O
scraper detecta e **explica** o bloqueio em vez de falhar em silêncio.

#### 5. Fallback de navegador (automático)

Última camada, para o *outro* problema — a loja que responde normalmente mas só preenche o
preço depois de rodar JavaScript. Entra sozinha quando **todos** os perfis HTTP falham; não é
preciso ligar nada. O padrão `NAVEGADOR_FALLBACK=auto` usa o Playwright se ele estiver
instalado e ignora em silêncio se não estiver.

Um detalhe que custou depuração: esperar `networkidle` **não basta**. Uma página sem
requisição pendente ainda pode escrever o preço num `setTimeout` — foi exatamente o que
aconteceu no primeiro teste, que capturou o HTML meio segundo cedo demais. O navegador agora
espera até um preço **aparecer no texto visível**, com timeout.

Para ver funcionando, a loja-demo tem uma versão que monta o preço por JS em
`/loja-demo/js/{slug}` — o HTML que sai de lá não tem preço nenhum:

| | Página HTML normal | Página com preço via JS |
| --- | --- | --- |
| Caminho usado | HTTP, perfil `chrome` | fallback de navegador |
| Tempo | 0,0 s | 1,2 s |
| Fonte | JSON-LD | varredura |

**Duas travas contra desperdício.** Abrir navegador custa ~15-20 s, então:

- domínio onde o navegador já rodou e mesmo assim não achou preço fica marcado e é pulado
  nas próximas coletas (medido com a Shopee: 1ª tentativa 15,2 s, seguintes 2,5 s);
- duas falhas seguidas ao abrir o navegador desligam o fallback no processo inteiro — é o
  caso de quem instalou o pacote mas esqueceu o `playwright install chromium`.

**Custo:** ~150 MB de Chromium baixados uma vez. Se preferir não usar,
`NAVEGADOR_FALLBACK=false` e tudo segue por HTTP. **Não resolve antibot** — Shopee, Magalu
e Mercado Livre foram testados e continuam bloqueando.

### Regra de alerta

O alerta nasce **na transição** para "alvo atingido", não a cada coleta — senão uma promoção
que dura três dias geraria um aviso novo a cada 6 horas. Se o preço volta a subir, o produto
retorna para `aguardando` e uma nova queda dispara um novo alerta.

---

## Configuração

Copie `backend/.env.example` para `backend/.env` e ajuste. Tudo tem padrão; nada é obrigatório.

| Variável | Padrão | Para que serve |
| --- | --- | --- |
| `SCHEDULER_ENABLED` | `true` | Liga o agendador interno |
| `SCRAPE_INTERVAL_MINUTES` | `360` | Intervalo entre coletas (6 h) |
| `COLETA_AO_INICIAR` | `false` | Dispara uma coleta ao subir a API |
| `SCRAPER_TIMEOUT` | `20` | Timeout de cada requisição, em segundos |
| `SCRAPER_DELAY_SEGUNDOS` | `1.0` | Pausa entre produtos numa rodada |
| `SCRAPER_TENTATIVAS` | `3` | Novas tentativas em HTTP 429/5xx, com espera crescente |
| `VARIACAO_MAXIMA_FATOR` | `4.0` | Acima disso a coleta é descartada como erro de extração |
| `NAVEGADOR_FALLBACK` | `auto` | `auto` usa o Playwright se instalado; `true` exige; `false` desliga |
| `NAVEGADOR_ESPERA_PRECO_MS` | `8000` | Quanto o navegador espera um preço aparecer na tela |
| `BASE_URL` | `http://127.0.0.1:8000` | Endereço da API (usado nos links da loja-demo) |

---

## Endpoints principais

| Método | Rota | O que faz |
| --- | --- | --- |
| `POST` | `/api/produtos` | Cadastra por URL + preço-alvo (faz a 1ª coleta e valida o link) |
| `GET` | `/api/produtos` | Lista com filtro por `status` e `busca` |
| `PATCH` | `/api/produtos/{id}` | Altera preço-alvo ou nome |
| `DELETE` | `/api/produtos/{id}` | Remove (histórico e alertas caem junto) |
| `POST` | `/api/produtos/{id}/pausar` · `/retomar` | Pausa ou retoma o monitoramento |
| `POST` | `/api/produtos/{id}/coletar` | Coleta manual de um produto |
| `GET` | `/api/produtos/{id}/historico` | Pontos do gráfico + mínimo/médio/máximo |
| `POST` | `/api/coletas/executar` | Roda a coleta em todos (o que o agendador faz) |
| `POST` | `/api/previa` | Testa uma URL sem cadastrar (mostra fonte e confiança) |
| `GET` | `/api/alertas` | Lista de alertas |
| `GET` | `/api/resumo` | Números do painel + estado do agendador |
| `GET` | `/api/lojas` | Taxa de sucesso do scraper por loja |
| `GET` | `/loja-demo` | Vitrine da loja fictícia |
| `POST` | `/api/demo/promocao` | Derruba os preços da loja-demo (para demonstrar) |

Documentação completa e testável em `/docs`.

---

## Decisões de projeto

- **SQLite, um arquivo só.** Ninguém precisa instalar servidor de banco para rodar. As
  foreign keys são ligadas explicitamente (`PRAGMA foreign_keys=ON`), senão o SQLite
  ignora `ON DELETE CASCADE` e deixaria histórico órfão.
- **Loja fictícia própria.** Depender de loja real numa apresentação é apostar contra o
  antibot. A TechPrecinho serve HTML real para o scraper real.
- **Gráfico em SVG escrito à mão.** Nenhuma biblioteca de charts — menos peso e o código
  fica legível para quem for avaliar.
- **`brand` não é a loja.** No schema.org, `brand` é o fabricante — um ventilador da Britânia
  vendido na KaBuM tem `brand: Britânia`. Quem identifica o vendedor é `offers.seller`, com
  `og:site_name` e o domínio como planos B.
- **Migração mínima sem Alembic.** O `create_all` cria tabelas mas nunca altera as
  existentes. Em vez de arrastar o Alembic inteiro, uma rotina curta adiciona colunas
  anuláveis novas e remove as que saíram do modelo (hoje só `alertas.email_enviado`, do
  tempo em que havia e-mail) — um banco criado por versão anterior continua funcionando.

---

## Evolução possível

O que ficou de fora conscientemente, e o que custaria:

**Proxies residenciais ou serviço de scraping.** É o que destravaria Magalu e Mercado Livre.
ScraperAPI, ScrapingBee e Zyte entregam o HTML já renderizado e já passado pelo antibot, com
IP residencial rotativo, por volta de US$ 30-50/mês. É o que rastreadores de preço reais usam
nessa escala — sai mais barato que manter infraestrutura antibot própria.

**API oficial.** É a resposta certa quando existe. O Mercado Livre tem API pública documentada
(exige registrar uma aplicação e usar token OAuth, que expira em algumas horas e precisa de
fluxo de renovação). Programas de afiliados entregam feeds de preço de várias lojas de uma
vez, legalmente e sem raspagem.

**Fila com workers.** Hoje a rodada é um laço sequencial com pausa entre produtos. Passando
de algumas dezenas de itens, o certo é uma fila com rate limit por domínio.

**Uso por mais de uma pessoa.** Para publicar o sistema na internet, ele precisaria de novo
de login com escopo por usuário, limite de requisições e bloqueio de endereços internos no
scraper (a URL é do usuário, mas quem faz a requisição é o servidor). Uma versão anterior
tinha tudo isso, e está no histórico do git.

**Aviso fora do painel.** O alerta hoje aparece no painel. Um canal que chegue sem o painel
aberto (e-mail, Telegram, notificação do sistema) é o passo natural — uma versão antiga
enviava e-mail pela Resend, e está no histórico do git.

**Sobre legalidade.** Raspar preço público é geralmente tolerado, mas os Termos de Uso da
maioria das lojas proíbem explicitamente. Para trabalho acadêmico, sem problema. Virando
produto com usuários, a rota é API oficial ou feed de afiliado.
