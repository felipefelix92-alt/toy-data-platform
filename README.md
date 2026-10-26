# 🛠️ Toy Data Platform

Laboratório de dados didático que roda inteiro na sua máquina — **offline**, sem
conta em nuvem. Os CSVs entram por **ingestão**, viram um **modelo dimensional** no
dbt, ganham **definições governadas** (métricas e dimensões) numa **camada semântica**
e são consumidos por **dois clientes diferentes**: um dashboard no Superset e um
agente de IA via MCP. A mesma métrica nos dois — e o agente não escreve SQL.

> **Extensão neste fork:** jogos do Metacritic — *a crítica e o público concordam?*
> Nova fonte com carga incremental, modelo dimensional, medida no Cube, dashboard e
> agente. Guia e números esperados em [`JOGOS.md`](JOGOS.md).

A narrativa da aula é essa: *da tabela larga ao contexto governado*. O vocabulário
(camada semântica, modelo semântico, métrica, grão, tabela de ponte, context
engineering) está em [`GLOSSARY.md`](GLOSSARY.md).

## A aula em cinco etapas

| # | Etapa | Ferramenta | O que acontece |
| - | - | - | - |
| 1 | Ingestão | **dlt** | os CSVs de `dlt/data/` viram tabelas **Iceberg** no catálogo `raw` |
| 2 | Transformação | **dbt** | `raw` → `trusted` → `refined`: fato `fct_titles` + dimensões |
| 3 | Camada semântica | **Cube** | medidas e dimensões governadas, lidas do Trino |
| 4 | Consumo (BI) | **Superset** | conectado ao Cube pelo protocolo Postgres |
| 5 | Consumo (agente) | **servidor MCP** | ferramentas para o agente consultar o Cube por REST |

## Arquitetura

![Arquitetura do stack: fontes → dlt → catálogo Iceberg (MinIO/Lakekeeper) → Trino → dbt → Cube (camada semântica) → Superset e servidor MCP → agente](eng-diagram.png)

Dois pontos de arquitetura que a aula costuma perguntar estão em
[Detalhes](#detalhes-que-a-aula-costuma-perguntar): por que o **dlt roda em
container** e por que o **Cube lê o Trino** em vez de os consumidores lerem o Trino.

## Pré-requisitos

- [Docker](https://www.docker.com/) com Docker Compose v2 (`docker compose`)
- `make`
- Python 3 — só para o **agente** rodar no host (etapa 5). O resto é tudo container.
- VM do Docker com no mínimo **4 GB de RAM, 2 CPUs e 10 GB de disco livre**
  (recomendado: 6 GB e 4 CPUs). Parado, o stack ocupa ~2,1 GB de RAM; o Trino
  sozinho, ~760 MB, e cresce durante o `dbt build`.

## Caminho único (do zero)

### 1. Clonar e subir o stack

```bash
git clone https://github.com/lorransr/toy-data-platform.git
cd toy-data-platform
docker compose up -d
```

Na primeira subida o Compose cria os buckets, registra os catálogos `raw`, `trusted`
e `refined` no Lakekeeper, sobe o Superset (migrations + admin) e publica o dashboard
de exemplo. Leva alguns minutos; o serviço que registra o Cube no Superset
(`superset-bootstrap`) roda uma vez e sai.

```bash
docker compose ps          # tudo `running`/`healthy` (os one-shot ficam `exited`)
```

Máquina apertada? O Airflow não entra nas etapas abaixo (a ingestão roda por
`make dlt-run`). Suba só o resto e economize ~700 MB de RAM e 2,2 GB de disco:

```bash
docker compose up -d trino cube superset superset-bootstrap create-warehouse
```

### 2. Ingerir os CSVs

Um comando por tabela, dentro da rede do Compose (é o caminho oficial — ver
[por que](#por-que-o-dlt-roda-em-container)):

```bash
make dlt-run DLT_TABLE=netflix_titles    # 8807 linhas
make dlt-run DLT_TABLE=meta_critic       # 16290 linhas
make dlt-run                             # imdb_top_1000 (default, 1000 linhas)
```

Reexecutar substitui os dados (`write_disposition="replace"`), sem tabela duplicada —
pode repetir à vontade durante a aula.

Conferindo no Trino (o CLI roda dentro do container do Trino):

```bash
docker compose exec trino trino --execute \
  "SELECT count(*) FROM raw.raw_movies.netflix_titles"
```

Ou abra o Trino em <http://localhost:8081> e rode o mesmo SQL.

### 3. Transformar (fato + dimensões)

```bash
make dbt-build      # dbt build: seeds + models + testes de dados
```

Isso monta `trusted.movies` / `trusted.delivery` e o modelo dimensional em
`refined.ml`: o fato `fct_titles` (grão = **um título**), as dimensões `dim_year`,
`dim_type` e as pontes `bridge_title_genre` / `bridge_title_country` (gênero e país
são multi-valor). Os testes de dados do dbt (`unique`, `not_null`, `relationships` e
as asserções de grão em `dbt/movies_transform/tests/`) rodam no mesmo comando.

```bash
docker compose exec trino trino --execute \
  "SELECT count(*), count(DISTINCT title_key) FROM refined.ml.fct_titles"
# 1813  1813  -> o fato tem exatamente um título por linha
```

### 4. Consultar a camada semântica

O Cube serve `titles_overview` (medidas × dimensões) por SQL API, no protocolo
Postgres, e por REST. Sem escrever SQL contra o catálogo:

```bash
docker run --rm --network platform-net -e PGPASSWORD=cubecubecube postgres:16 \
  psql -h cube -p 15432 -U cube -d cube \
  -c "SELECT title_type, MEASURE(count_titles) AS titulos,
             round(MEASURE(avg_rating)::numeric, 3) AS nota
      FROM titles_overview GROUP BY 1 ORDER BY 1"
```

```
 title_type | titulos | nota
------------+---------+-------
 Movie      |    1673 | 6.627
 TV Show    |     140 | 6.597
```

Pela REST API:

```bash
curl -sG http://localhost:4000/cubejs-api/v1/load \
  --data-urlencode 'query={"measures":["titles_overview.count_titles","titles_overview.avg_rating"],"dimensions":["titles_overview.genre"]}' \
  | python3 -c 'import json,sys; [print(r) for r in json.load(sys.stdin)["data"]]'
```

O **Playground** (<http://localhost:4000>) explora o mesmo modelo clicando, sem
escrever cliente nenhum — bom para a aula.

### 5. Ver no Superset

Abra <http://localhost:8088> (`admin` / `secret`) → **Dashboards** → *Camada
semântica — títulos*: um gráfico de barras de nota média por país e uma tabela de
medidas por tipo de título. O Superset enxerga o Cube como se fosse um banco
Postgres (`titles_overview` = uma tabela, medidas e dimensões = colunas), então o
builder normal funciona — mas não há SQL livre nem joins ad-hoc ([limitações](#por-que-o-superset-vê-um-banco)).

### 6. Perguntar ao agente

```bash
make mcp-install     # cria mcp/.venv e instala o SDK do MCP
make mcp-demo        # roteiro de perguntas pelo protocolo MCP (sem LLM)
```

```
Pergunta: Qual país tem a melhor nota média entre os que têm pelo menos 20 títulos?

[1] list_measures()    → count_titles, avg_rating, total_votes
[2] list_dimensions()  → release_year, title_type, genre, country
[3] query(...)         → chamada governada (medidas × dimensão × filtro)

Resposta: Japan — nota média 7.079 em 29 títulos.
```

O agente **descobre** o que existe antes de perguntar e devolve a chamada que gerou a
resposta — é o *context engineering* da aula. Para ligar um cliente MCP de verdade
(Claude Desktop, Cursor etc.) veja [`mcp/README.md`](mcp/README.md).

## Serviços e endereços

| Serviço | Papel | Endereço / credenciais |
| - | - | - |
| Airflow | orquestração (DAG `extract_movies` ingere os 3 CSVs) | <http://localhost:8080> — `admin` / `admin` |
| MinIO | object storage dos arquivos Iceberg | console: <http://localhost:9001> — `root` / `rootrootroot` |
| Lakekeeper | catálogo Iceberg (API REST; sem UI) | <http://localhost:8181> |
| Trino | engine SQL sobre os três catálogos | <http://localhost:8081> |
| dlt | ingestão (imagem `my-dlt-pipeline`) | `make dlt-run` |
| dbt | transformação (imagem `movies_transform`) | `make dbt-build`, `make dbt-shell` |
| Cube | camada semântica: REST, SQL API e Playground | <http://localhost:4000> (Playground e `/cubejs-api/v1`) — SQL em `localhost:15432`, `cube` / `cubecubecube` |
| Superset | BI, consumindo o Cube | <http://localhost:8088> — `admin` / `secret` |
| MCP | agente (fala com o Cube por REST) | `make mcp-demo` — stdio, ver `mcp/README.md` |

## O que é governado

| Medida | Definição |
| - | - |
| `count_titles` | quantidade de títulos distintos |
| `avg_rating` | nota média da crítica |
| `total_votes` | total de votos da crítica |

Dimensões: `release_year`, `title_type`, `genre`, `country`.

O modelo semântico é YAML versionado em `cube/model/` — a medida é definida **uma vez
só**, no cubo `titles`, e a view `titles_overview` é a fachada plana que o Superset e
o agente consomem (`cube/README.md` tem o detalhe, inclusive de como fatiar por
gênero/país sem inflar as medidas).

## Smoke antes da aula

Roteiro de 5 minutos para rodar com o stack no ar, antes de entrar na sala:

1. **Ingerir** as duas fontes do dbt:
   `make dlt-run DLT_TABLE=netflix_titles` → `8807` linhas, e
   `make dlt-run DLT_TABLE=meta_critic` → `16290` linhas, em `raw.raw_movies`.
2. **Transformar:** `make dbt-build` → `Done. PASS=45`, e `refined.ml.fct_titles` com `1813` linhas = `1813` chaves distintas.
3. **Camada semântica:**
   ```bash
   docker run --rm --network platform-net -e PGPASSWORD=cubecubecube postgres:16 \
     psql -h cube -p 15432 -U cube -d cube \
     -c "SELECT title_type, MEASURE(count_titles), MEASURE(avg_rating) FROM titles_overview GROUP BY 1"
   ```
   → `Movie 1673 / 6.627` e `TV Show 140 / 6.597` (sem dimensão: `1813 / 6.625 / 322914`).
4. **Superset:** o dashboard *Camada semântica — títulos* abre com o gráfico de barras e a tabela preenchidos.
5. **Agente:** `make mcp-demo` → `Japan — nota média 7.079 em 29 títulos`.

Se os números não baterem, o problema é a etapa que não rodou: o Cube lê o `refined`,
o Superset lê o Cube, o agente lê o Cube.

## Caminho opcional: dlt no host (venv)

O caminho oficial é o container. Rodar o dlt direto no host existe para *ver o que o
container esconde*, e **exige um pré-requisito**: com catálogo REST, o endpoint de
storage vem do catálogo e não é sobrescrevível pelo destino `filesystem` do dlt — então
o seu host precisa resolver o nome interno do MinIO:

```bash
# /etc/hosts
127.0.0.1 minio

cd dlt
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
set -a; source .env.host; set +a
python filesystem_pipeline.py -t imdb_top_1000
```

Sem essa linha a gravação falha por resolução de nome/conexão. A explicação completa
(por que não é bug de código) está em [`dlt/README.md`](dlt/README.md).

## Estrutura do repositório

```
airflow/      DAG de ingestão (DockerOperator na imagem do dlt)
cube/         modelo semântico em YAML (cube/model/) + README da camada semântica
dbt/          projeto dbt: trusted (limpeza) e refined (fato + dimensões)
dlt/          pipeline de ingestão dos CSVs (data/) para o Iceberg
lakekeeper/   criação dos catálogos raw/trusted/refined no catálogo REST
mcp/          servidor MCP do agente (+ testes e demo)
minio/        placeholder vazio (os dados ficam no volume Docker do MinIO)
superset/     imagem, setup e bootstrap do banco/dataset/dashboard do Superset
trino/        catálogos (raw, trusted, refined) apontando para o Lakekeeper
GLOSSARY.md   vocabulário da aula
```

## Detalhes que a aula costuma perguntar

### Por que o dlt roda em container

Com **catálogo REST**, quem define como o cliente fala com o storage é o catálogo, não
o cliente. O warehouse aponta para o endereço interno do MinIO (`http://minio:9000`),
que não resolve no host — por isso o caminho que funciona sem mexer na máquina é rodar
o dlt **na rede do Compose**. Não é bug de configuração: é a arquitetura de catálogo
decidindo onde estão os dados.

### Por que o Cube lê o Trino

Porque o Trino já sabe ler os três catálogos Iceberg. O Cube aponta para
`refined.ml` e não introduz mais uma cópia dos dados; a camada semântica é uma
*definição* servida sobre o dado que já existe.

### Por que o Superset vê "um banco"

O Cube expõe a SQL API no **protocolo Postgres**, então o Superset o registra como um
banco normal e `titles_overview` aparece como tabela — é o que permite montar gráfico
com o builder padrão. As limitações: **(i)** as métricas precisam ser escritas como
`MEASURE(nome_da_medida)` (a forma canônica da SQL API; as colunas agregadas
“naturais” não existem como colunas de banco); **(ii)** sem joins ad-hoc entre cubos —
você consulta o que o modelo semântico expõe. Um dashboard que funcionava no Trino pode
precisar de ajuste: as colunas que entraram no dataset são as **governadas**.

### País tem um balde nulo

A ponte título ↔ país é inner join no dbt (título sem país na origem não entra), mas ao
fatiar por país o Cube faz LEFT JOIN para não perder o fato: 36 dos 1813 títulos
aparecem numa linha `country = null`. Quem pergunta por país filtra
`{"member": "titles_overview.country", "operator": "set"}` — é o que o demo do MCP faz
(por isso são 15 países, não 16).

### A armadilha da localização da tabela

Os catálogos declaram `iceberg.unique-table-location=true` (o default do Trino). Com
`false` a localização de cada tabela é determinística, o `DROP` deixa os arquivos no
mesmo caminho e o catálogo recusa recriar a tabela ali (*"tabular locations have to be
empty"*) — o Trino, por sua vez, reporta isso como um obscuro `Failed to create
transaction`. Como o seed do dbt faz `drop` + `create` a cada execução, `dbt build`
falhava na segunda vez. Quem apaga uma tabela precisa saber que "dropar" no Iceberg não
é "dropar com purge".

### MinIO fora do Docker Hub

O MinIO removeu as imagens do Docker Hub e o `quay.io/minio/minio` nega pull anônimo.
O Compose usa o build público da Chainguard (`chainguard/minio`), que traz o mesmo
server e o cliente `mc` (usado para criar os buckets).

## Personalizar

- Novos fluxos: adicione DAGs em `airflow/dags` (a imagem do dlt é `my-dlt-pipeline`).
- Novos dados: solte o CSV em `dlt/data/` e rode `make dlt-run DLT_TABLE=<nome>`; depois
  declare a tabela como *source* no dbt (`dbt/movies_transform/models/trusted/`).
- Novos modelos dbt: `make dbt-shell` abre um shell na imagem com o projeto montado
  (`dbt run --select ...`, `dbt test`, `dbt docs generate`).
- Novas métricas/dimensões: edite `cube/model/` e reinicie o serviço (`docker compose
  restart cube`).
- Contas e senhas locais: `airflow/.env`, `trino/.env`, `dlt/.env.docker`,
  `dbt/.env`, `cube/.env` (todas com um `.sample`/par correspondente).

## Contribuindo

Pull Requests são bem-vindos! Se tiver ideia ou encontrar problema, abra uma issue.
