# Extensão: jogos — a crítica e o público concordam?

**Pergunta:** a distância entre a nota da crítica (Metacritic) e a nota do público
mudou ao longo dos anos? Em quais gêneros e fabricantes ela é maior?

**Fonte:** *Video Game Sales with Ratings* (Kaggle, snapshot de 22/dez/2016) —
16.719 linhas, uma por lançamento (jogo × plataforma × ano), com metascore (0–100),
nota de usuário (0–10 ou `tbd`), vendas, gênero, publisher e plataforma.
Arquivo: `dlt/data/games_metacritic.csv`.

## O que mudou em cada camada

| Camada | Mudança | Arquivos |
| - | - | - |
| Ingestão | nova fonte com **carga incremental** (`merge`/`upsert` por `game_id`) no lugar de `replace` | `dlt/games_pipeline.py`, `Makefile` (`dlt-games`) |
| Orquestração | DAG diária e idempotente da ingestão de jogos | `airflow/dags/ingest_games.py` |
| Transformação | trusted tipado (`tbd` → nulo + status, ano futuro → nulo) | `dbt/.../models/trusted/games/` |
| Modelagem | fato `fct_game_releases` + `dim_platform` (seed com fabricante), `dim_game_genre`, `dim_publisher` | `dbt/.../models/refined/games/`, `seeds/game_platforms.csv` |
| Qualidade | testes de grão, escala das notas e consistência da fonte (este último pega erro real) | `dbt/.../tests/assert_*game*.sql`, `schema.yml` |
| Camada semântica | cubo `game_releases` + view `games_overview` com a medida `avg_score_gap` | `cube/model/cubes/game_releases.yml`, `cube/model/views/games_overview.yml` |
| Consumo (BI) | dashboard *Jogos — crítica × público* | `superset/bootstrap_semantic_layer.py` |
| Consumo (agente) | ferramenta `list_models` e parâmetro `model`: o agente escolhe a view | `mcp/server.py`, `mcp/demo.py`, `mcp/tests/` |

## Rodando no GitHub Codespaces

1. Subir o stack (a primeira vez leva alguns minutos):
   ```bash
   docker compose up -d
   docker compose ps
   ```
2. Ingerir os filmes (o `dbt build` do projeto também transforma os filmes):
   ```bash
   make dlt-run DLT_TABLE=netflix_titles
   make dlt-run DLT_TABLE=meta_critic
   ```
3. Ingerir os jogos **em duas etapas**, para mostrar o merge:
   ```bash
   make dlt-games GAMES_MAX_YEAR=2010   # carga parcial: até 2010
   make games-count                     # esperado: 12422 linhas, 12422 chaves
   make dlt-games                       # carga completa: insere só o que falta
   make games-count                     # esperado: 16716 linhas, 16716 chaves
   make dlt-games                       # de novo, mesmo arquivo
   make games-count                     # continua 16716: o merge não duplica
   ```
   No log aparece `[games] 2 linhas com chave repetida consolidadas: ['Madden NFL 13|PS3|2012']`.
4. Transformar e testar:
   ```bash
   make dbt-build
   ```
   Esperado: o build termina com **1 aviso (WARN)** — o teste
   `assert_raw_games_release_year_not_after_snapshot` encontra **4** jogos com ano
   de lançamento 2017/2020 numa base de dezembro de 2016.
5. Conferir a resposta no Cube (SQL API):
   ```bash
   docker run --rm --network platform-net -e PGPASSWORD=cubecubecube postgres:16 \
     psql -h cube -p 15432 -U cube -d cube \
     -c "SELECT release_year, MEASURE(count_scored_releases) AS jogos,
                round(MEASURE(avg_critic_score)::numeric, 1) AS critica,
                round(MEASURE(avg_user_score)::numeric, 1) AS publico,
                round(MEASURE(avg_score_gap)::numeric, 1) AS distancia
         FROM games_overview WHERE release_year >= 2000 GROUP BY 1 ORDER BY 1"
   ```
6. Dashboard: aba **Ports** → porta **8088** (Superset, `admin` / `secret`) →
   **Dashboards** → *Jogos — crítica × público*.
7. Agente:
   ```bash
   make mcp-demo-games
   ```
8. Orquestração (pela linha de comando: no Codespaces a interface do Airflow
   recusa o login por causa do endereço `*.app.github.dev`):
   ```bash
   echo "DOCKER_GID=$(stat -c %g /var/run/docker.sock)" >> .env   # uma vez, antes de subir o Airflow
   docker compose up -d airflow-scheduler airflow-webserver airflow-dag-processor
   docker compose exec airflow-scheduler airflow dags unpause ingest_games
   docker compose exec airflow-scheduler airflow dags trigger ingest_games
   docker compose exec airflow-scheduler airflow dags list-runs ingest_games   # esperado: success
   ```

## Números esperados (para conferir)

Calculados sobre o mesmo CSV durante o desenvolvimento:

| | |
| - | - |
| `fct_game_releases` | 16.716 lançamentos, 7.016 com as duas notas |
| Médias gerais (só com as duas notas) | crítica 70,2 · público 71,8 · distância −1,6 |
| Distância em 2000 / 2009 / 2010 / 2016 | −3,2 / −0,5 / **+0,3** / +5,4 |
| Por fabricante | Nintendo −4,3 · Sony −2,7 · Microsoft +0,2 · PC +5,6 |
| Por gênero (extremos) | Sports +3,0 · Adventure −5,4 |

**Leitura:** até 2009 o público dava notas maiores que a crítica; a partir de 2010 a
relação se inverte e a distância chega a ~5 pontos em 2016.
