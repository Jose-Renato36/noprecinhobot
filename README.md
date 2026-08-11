# 🏷️ NoPrecinhoBot

**Sistema de Monitoramento Automático de Preços** — atividade acadêmica.

O usuário cadastra um produto a partir de uma URL e define um preço-alvo. Um processo
automático (scraper) revisita cada produto periodicamente, registra o preço no histórico e,
quando o valor atinge o alvo, dispara um alerta.

**Integrantes:** José Renato · João Pedro · Tiago Ferrari · Jean Lucas · Pedro Henrique

---

## Como rodar

Precisa de **Python 3.12+** e **Node.js 18+**.

### 1. Backend (API + scraper + agendador)

```bash
cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt -r requirements-dev.txt && playwright install chromium && uvicorn app.main:app --reload
```

Sobe em <http://127.0.0.1:8000> — documentação interativa em <http://127.0.0.1:8000/docs>.

O `requirements-dev.txt` traz o `pytest` e o Playwright — este último baixa o navegador
(`playwright install chromium`) usado como último recurso em lojas que montam o preço por
JavaScript. Se pular esse passo, o scraper funciona igual, só sem essa camada — ele se
desliga sozinho. Em produção só o `requirements.txt` é instalado.

Sem nenhuma configuração ele já funciona: usa **SQLite** local (`backend/noprecinho.db`) e
registra os alertas no banco. Para PostgreSQL e e-mail, veja [Configuração](#configuração).

### 2. Frontend (painel React)

Em outro terminal:

```bash
cd frontend && npm install && npm run dev
```

Abra <http://localhost:5173>. O Vite faz proxy de `/api` para o backend, então não há
URL de API para configurar em desenvolvimento.

### 3. Rodar os testes

```bash
cd backend && .venv\Scripts\python -m pytest
```

---

## Como demonstrar em 1 minuto

As lojas reais (Amazon, Mercado Livre, Magalu) respondem **HTTP 403** para robôs, o que
inviabiliza uma apresentação ao vivo confiável. Por isso o backend serve a **TechPrecinho**,
uma loja fictícia em <http://127.0.0.1:8000/loja-demo>: são páginas HTML de verdade, com
JSON-LD e OpenGraph, cujo preço oscila ±12% num ciclo de 10 minutos. O scraper acessa por
HTTP igual a qualquer outra loja — nada é simulado do lado dele.

1. No painel, abra a aba **Loja de teste** e copie o link de um produto.
2. Cole na aba **Painel**, clique em **Testar link** (o scraper roda e mostra o que achou) e
   defina um preço-alvo um pouco abaixo do atual.
3. Clique em **Coletar tudo agora** algumas vezes: o histórico cresce e o gráfico se forma.
4. Clique em **💥 Derrubar preços 40%** na aba Loja de teste e colete de novo — o alerta
   dispara, o card fica verde e o alerta aparece na aba **Alertas**.

O produto também é monitorado sozinho: o agendador roda no intervalo definido em
`SCRAPE_INTERVAL_MINUTES` (o `.env` de desenvolvimento vem com 3 minutos para dar para ver
acontecendo; a especificação pede 360 = 6 horas).

---

## Arquitetura

| Camada | Tecnologia | Papel |
| --- | --- | --- |
| Frontend | React 18 + Vite + CSS | Cadastro, painel, histórico e alertas |
| Backend / API | Python + FastAPI | CRUD de produto, coleta, histórico, alertas |
| Scraper | BeautifulSoup + curl_cffi | Extrai nome, preço e imagem; se adapta ao HTML da loja |
| Agendador | APScheduler / cron da Railway | Dispara a coleta periodicamente |
| Banco | PostgreSQL (SQLite em dev) | Produtos, histórico e alertas |
| Notificação | Resend | E-mail quando o alerta dispara |

```
React  ──HTTP──▶  FastAPI  ──▶  scraper (BeautifulSoup)  ──▶  página da loja
                     │                    │
                     │                    ▼
                     │            histórico + comparação com o alvo
                     │                    │
                     ▼                    ▼
                PostgreSQL           alerta ──▶ Resend (e-mail)
                     ▲
        APScheduler / cron ─── dispara a coleta a cada N minutos
```

### Estrutura de pastas

```
noprecinhhobot/
├── backend/
│   ├── app/
│   │   ├── main.py        API FastAPI (rotas)
│   │   ├── models.py      Usuário, Produto, HistoricoPreco, Alerta
│   │   ├── schemas.py     Contratos de entrada/saída (Pydantic)
│   │   ├── scraper.py     Extração adaptativa de nome/preço/imagem
│   │   ├── monitor.py     Coleta + regras de alerta
│   │   ├── scheduler.py   Agendador interno (APScheduler)
│   │   ├── run_coleta.py  Entrypoint para o cron da Railway
│   │   ├── notifier.py    Envio de e-mail via Resend
│   │   ├── demo_store.py  Loja fictícia TechPrecinho
│   │   ├── database.py    Engine e sessão do SQLAlchemy
│   │   └── config.py      Configuração por variáveis de ambiente
│   └── tests/             Testes do scraper e das regras de alerta
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
- **Alerta** — gerado quando o preço atinge o alvo: preço de disparo, alvo, mensagem, se o
  e-mail saiu.
- **Usuario** — entidade opcional na especificação. Existe no modelo e é o destinatário do
  e-mail, mas **não há tela de login**: tudo roda sob um "Usuário Demo" criado no primeiro boot.

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

**Custo:** ~400 MB de Chromium. Na Railway, exige trocar o Nixpacks por um Dockerfile com as
libs de sistema; se preferir não usar lá, `NAVEGADOR_FALLBACK=false` e tudo segue por HTTP.
**Não resolve antibot** — Shopee, Magalu e Mercado Livre foram testados e continuam bloqueando.

### Regra de alerta

O alerta nasce **na transição** para "alvo atingido", não a cada coleta — senão uma promoção
que dura três dias geraria um e-mail a cada 6 horas. Se o preço volta a subir, o produto
retorna para `aguardando` e uma nova queda dispara um novo alerta.

---

## Configuração

Copie `backend/.env.example` para `backend/.env` e ajuste. Tudo tem padrão; nada é obrigatório.

| Variável | Padrão | Para que serve |
| --- | --- | --- |
| `DATABASE_URL` | SQLite local | Conexão do banco. Aceita `postgres://` (a Railway preenche sozinha) |
| `SCHEDULER_ENABLED` | `true` | Liga o agendador interno |
| `SCRAPE_INTERVAL_MINUTES` | `360` | Intervalo entre coletas (6 h) |
| `COLETA_AO_INICIAR` | `false` | Dispara uma coleta ao subir a API |
| `SCRAPER_TIMEOUT` | `20` | Timeout de cada requisição, em segundos |
| `SCRAPER_DELAY_SEGUNDOS` | `1.0` | Pausa entre produtos numa rodada |
| `SCRAPER_TENTATIVAS` | `3` | Novas tentativas em HTTP 429/5xx, com espera crescente |
| `VARIACAO_MAXIMA_FATOR` | `4.0` | Acima disso a coleta é descartada como erro de extração |
| `NAVEGADOR_FALLBACK` | `auto` | `auto` usa o Playwright se instalado; `true` exige; `false` desliga |
| `NAVEGADOR_ESPERA_PRECO_MS` | `8000` | Quanto o navegador espera um preço aparecer na tela |
| `EMAIL_ENABLED` | `true` | `false` desliga o envio por completo, mesmo com chave |
| `RESEND_API_KEY` | — | Chave da Resend. **Sem ela o alerta é só registrado no banco** |
| `RESEND_FROM` | `onboarding@resend.dev` | Remetente |
| `EMAIL_DESTINO` | — | Destinatário (se o usuário não tiver e-mail) |
| `SECRET_KEY` | aleatória por boot | Assina os tokens. **Defina em produção**, senão todo reinício desloga todo mundo |
| `JWT_EXPIRA_MINUTOS` | `720` | Validade do token (12 horas) |
| `COOKIE_PERSISTENTE` | `false` | `false` = sessão morre ao fechar o navegador |
| `COOKIE_SEGURO` | segue a `BASE_URL` | Exige HTTPS; ligado sozinho quando a `BASE_URL` é `https` |
| `COOKIE_SAMESITE` | `strict` | Proteção contra CSRF |
| `REGISTRO_ABERTO` | `true` | Com `false`, ninguém cria conta nova; as existentes seguem entrando |
| `RATE_LIMIT_ENABLED` | `true` | Liga as proteções contra abuso |
| `CONFIAR_PROXIES` | `1` | Proxies confiáveis à frente da API. **Use `0` sem proxy** |
| `LIMITE_LOGIN` · `_JANELA` | `10` · `300` | Tentativas de login por IP a cada 5 min |
| `LIMITE_REGISTRO` · `_JANELA` | `5` · `3600` | Contas criadas por IP por hora |
| `LIMITE_SCRAPING` · `_JANELA` | `20` · `60` | Chamadas que disparam o scraper, por IP por minuto |
| `LOGIN_MAX_FALHAS` | `5` | Senhas erradas antes de trancar a conta |
| `LOGIN_BLOQUEIO_SEGUNDOS` | `60` | Duração do 1º bloqueio (dobra a cada rodada) |
| `LOGIN_BLOQUEIO_TETO_SEGUNDOS` | `900` | Teto do bloqueio (15 min) |
| `BASE_URL` | `http://127.0.0.1:8000` | URL pública da API (usada nos links da loja-demo) |
| `CORS_ORIGINS` | `localhost:5173` | Origens liberadas para o frontend |
| `DEMO_STORE_ENABLED` | `true` | Liga a loja fictícia |

### E-mail (Resend)

Sem `RESEND_API_KEY` o sistema **não quebra**: o alerta é gravado, aparece no painel e o
card do alerta indica "e-mail não configurado". Para ativar de verdade, crie uma conta na
[Resend](https://resend.com), gere uma API key e preencha `RESEND_API_KEY` + `EMAIL_DESTINO`.
Na conta gratuita, o remetente `onboarding@resend.dev` só entrega para o e-mail cadastrado
na própria Resend.

---

## Deploy na Railway

Há dois caminhos. O primeiro é mais simples e é o recomendado.

### Opção A — um serviço só (Dockerfile)

Crie **um** serviço apontando para este repositório e **não configure Root Directory**. A
Railway encontra o `Dockerfile` na raiz e usa ele, sem depender de detecção de linguagem.
Ele compila o painel React e o entrega junto com a API, servidos pela mesma origem.

Adicione o PostgreSQL (`+ New` → `Database` → `PostgreSQL`) e configure:

```
DATABASE_URL        → referência ao serviço Postgres
BASE_URL            → https://<dominio-do-servico>
DEMO_STORE_ENABLED  → false
NAVEGADOR_FALLBACK  → false
```

Não é preciso `CORS_ORIGINS` nem `VITE_API_URL`: com uma origem só, o painel chama `/api`
por caminho relativo e o navegador nem passa pelo CORS.

### Opção B — três serviços

Mais fiel à separação de responsabilidades, e é o desenho descrito na especificação.

> ⚠️ **O passo que faz o build falhar se for esquecido:** em cada serviço, defina o
> **Root Directory** em *Settings → Source*. A raiz do repositório só contém `backend/` e
> `frontend/`, então sem esse ajuste o builder não identifica linguagem nenhuma e aborta
> com *"could not determine how to build the app"*. Essa configuração vive no painel da
> Railway — nenhum arquivo do repositório substitui ela.

**1. PostgreSQL** — adicione pelo painel (`+ New` → `Database` → `PostgreSQL`). A Railway
cria a variável `DATABASE_URL` automaticamente.

**2. API** — Root Directory `backend`.
- Build e start já vêm fixados em `backend/railway.json`; a versão do Python, em
  `backend/.python-version`.
- Variáveis: referencie o `DATABASE_URL` do Postgres, e defina `BASE_URL` com o domínio
  público do serviço, `CORS_ORIGINS` com a URL do frontend, `DEMO_STORE_ENABLED=false` e,
  opcionalmente, `RESEND_API_KEY` e `EMAIL_DESTINO`.
- As tabelas são criadas no primeiro boot; não há migração para rodar.

**3. Frontend** — Root Directory `frontend`.
- Build e start já vêm fixados em `frontend/railway.json`.
- Variável: `VITE_API_URL` = URL pública da API.
- O `vite preview` recusa requisições de hosts desconhecidos desde o Vite 5.4.12. O
  `vite.config.js` libera automaticamente o `RAILWAY_PUBLIC_DOMAIN`, que a Railway injeta
  sozinha — se você usar domínio próprio, adicione-o em `preview.allowedHosts`.

> **Por que `DEMO_STORE_ENABLED=false` em produção:** a loja-demo expõe
> `POST /api/demo/reiniciar`, que apaga produtos, histórico e alertas sem pedir
> autenticação. Em ambiente público isso é um botão de autodestruição aberto.

**Agendador — escolha uma das duas formas:**

- **Worker interno (padrão):** deixe `SCHEDULER_ENABLED=true` na API. O APScheduler roda
  dentro do processo e dispara a coleta a cada `SCRAPE_INTERVAL_MINUTES`. Mais simples, mas
  a coleta para se a API dormir.
- **Cron job da Railway:** defina `SCHEDULER_ENABLED=false` na API e crie um quarto serviço
  com Root Directory `backend`, comando `python -m app.run_coleta` e um cron schedule
  (`0 */6 * * *` para cada 6 horas). Mais robusto e é o que a especificação descreve.

> **Alternativa tudo-em-um:** se `frontend/dist` existir, a API serve o painel na raiz
> (`/`). Basta rodar `npm run build` antes do deploy e usar um único serviço.

---

## Endpoints principais

Com exceção de `/api/health`, das rotas de autenticação e das páginas da loja-demo, tudo
exige sessão. O painel usa o cookie `httpOnly` gravado no login; clientes que não são
navegador (o `/docs`, curl, scripts) mandam `Authorization: Bearer <token>`, e o token vem
no corpo da resposta de login justamente para isso.

| Método | Rota | O que faz |
| --- | --- | --- |
| `POST` | `/api/auth/registrar` | Cria conta e já devolve o token |
| `POST` | `/api/auth/login` | Autentica e devolve o token |
| `POST` | `/api/auth/sair` | Apaga o cookie de sessão |
| `GET` | `/api/auth/eu` | Confirma se a sessão ainda vale |
| `POST` | `/api/produtos` | Cadastra por URL + preço-alvo (faz a 1ª coleta e valida o link) |
| `GET` | `/api/produtos` | Lista com filtro por `status` e `busca` |
| `PATCH` | `/api/produtos/{id}` | Altera preço-alvo ou nome |
| `DELETE` | `/api/produtos/{id}` | Remove (histórico e alertas caem junto) |
| `POST` | `/api/produtos/{id}/pausar` · `/retomar` | Pausa ou retoma o monitoramento |
| `POST` | `/api/produtos/{id}/coletar` | Coleta manual de um produto |
| `GET` | `/api/produtos/{id}/historico` | Pontos do gráfico + mínimo/médio/máximo |
| `POST` | `/api/coletas/executar` | Roda a coleta em todos (o que o cron faz) |
| `POST` | `/api/previa` | Testa uma URL sem cadastrar (mostra fonte e confiança) |
| `GET` | `/api/alertas` | Lista de alertas |
| `GET` | `/api/resumo` | Números do painel + estado do agendador |
| `GET` | `/api/lojas` | Taxa de sucesso do scraper por loja |
| `GET` | `/loja-demo` | Vitrine da loja fictícia |
| `POST` | `/api/demo/promocao` | Derruba os preços da loja-demo (para demonstrar) |

Documentação completa e testável em `/docs`.

---

## Decisões de projeto

- **SQLite em dev, PostgreSQL em produção.** O mesmo código roda nos dois: o
  `DATABASE_URL` decide. Assim ninguém precisa instalar Postgres para desenvolver. As
  foreign keys são ligadas explicitamente no SQLite (`PRAGMA foreign_keys=ON`), senão ele
  ignora `ON DELETE CASCADE` e deixaria histórico órfão.
- **Loja fictícia própria.** Depender de loja real numa apresentação é apostar contra o
  antibot. A TechPrecinho serve HTML real para o scraper real.
- **Gráfico em SVG escrito à mão.** Nenhuma biblioteca de charts — menos peso e o código
  fica legível para quem for avaliar.
- **E-mail nunca derruba a coleta.** Falha de rede ou chave ausente só geram log; o alerta
  já está salvo no banco.
- **`brand` não é a loja.** No schema.org, `brand` é o fabricante — um ventilador da Britânia
  vendido na KaBuM tem `brand: Britânia`. Quem identifica o vendedor é `offers.seller`, com
  `og:site_name` e o domínio como planos B.
- **Migração aditiva sem Alembic.** O `create_all` cria tabelas mas nunca altera as
  existentes. Em vez de arrastar o Alembic inteiro, há uma rotina de ~20 linhas que só
  adiciona colunas anuláveis novas — resolve o caso real sem tocar em dado existente.
- **Autorização por dono, não só autenticação.** O login responde "quem é você"; o risco
  real está em "a que você tem direito". Toda rota que recebe um id confere o dono, e
  produto de outra pessoa responde **404, não 403** — dizer "existe, mas não é seu"
  permitiria mapear a base alheia testando ids em sequência.
- **Unicidade de URL por usuário.** Antes do login era global, o que faria o segundo
  usuário a cadastrar um link já monitorado levar 409. Trocar isso num banco que já existe
  exige `ALTER TABLE`, então há uma migração dedicada (só PostgreSQL; em SQLite de
  desenvolvimento, apagar o `.db` resolve).
- **Sessão em cookie `httpOnly`, não em `localStorage`.** Os dois armazenamentos do
  navegador (`localStorage` e `sessionStorage`) são legíveis por JavaScript: um XSS copia
  o token e o reusa de outro lugar. O cookie `httpOnly` a página não consegue nem ler. O
  custo normal dessa escolha é ter que tratar CSRF, mas painel e API são servidos pela
  mesma origem, então `SameSite=Strict` resolve. Sem data de expiração, o cookie morre ao
  fechar o navegador; o JWT de 12 h é a rede de segurança para quem deixa o navegador
  aberto por dias.
- **Duas defesas contra abuso, não uma.** O limite por IP segura quem martela a API; a
  trava por conta segura o ataque distribuído contra *um* e-mail, em que cada tentativa
  vem de um IP diferente e nenhum limite por IP chega a disparar. Uma não substitui a
  outra.
- **`CONFIAR_PROXIES` é explícito de propósito.** Atrás de um proxy, todas as requisições
  chegam com o IP dele: limitar por `request.client.host` colocaria todos os usuários no
  mesmo balde, e um atacante derrubaria o acesso de todo mundo junto. Já confiar no
  `X-Forwarded-For` *sem* proxy na frente é pior que não limitar — qualquer um forja o
  cabeçalho e escapa trocando de "IP" a cada requisição. Não existe padrão seguro para os
  dois casos, então a topologia é declarada.
- **Estado do limitador em memória.** Com uma instância, basta, e evita arrastar Redis
  para o projeto. Escalando para várias, cada uma conta em separado e o limite efetivo
  vira N vezes o configurado — o caminho então é trocar o miolo de `limitador.py` por um
  armazenamento compartilhado, sem tocar nas rotas.

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

**Sobre legalidade.** Raspar preço público é geralmente tolerado, mas os Termos de Uso da
maioria das lojas proíbem explicitamente. Para trabalho acadêmico, sem problema. Virando
produto com usuários, a rota é API oficial ou feed de afiliado.
