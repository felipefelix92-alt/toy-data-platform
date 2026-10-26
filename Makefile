DBT_IMAGE = movies_transform
DBT_TARGET ?= dev
NETWORK = platform-net
DLT_IMAGE = my-dlt-pipeline
DLT_TABLE ?= imdb_top_1000

build: 
	docker build -t $(DBT_IMAGE) dbt/

# --- dbt transformation (roda em container na rede do Compose, como o dlt) ---

# Seeds + models + testes de dados, na ordem de dependência (`dbt build`).
# É o comando único de transformação do caminho do README.
# Requires the stack to be up (`docker compose up -d`) and the raw tables ingested.
dbt-build: build
	docker run --rm \
	    -v $(PWD)/dbt/$(DBT_IMAGE):/usr/app/$(DBT_IMAGE) \
	    --env-file $(PWD)/dbt/.env \
	    --network $(NETWORK) \
	    -w /usr/app/$(DBT_IMAGE) \
	    $(DBT_IMAGE) \
	    dbt build --target-path target/prod

# Slim CI: em dev, constrói só o que mudou desde o último `make dbt-build` (o manifest
# de target/prod) e o que depende disso; o resto o `ref()` lê de prod (--defer),
# mesmo que exista uma cópia velha em dev (--favor-state).
dbt-slim: build
	docker run --rm \
	    -v $(PWD)/dbt/$(DBT_IMAGE):/usr/app/$(DBT_IMAGE) \
	    --env-file $(PWD)/dbt/.env \
	    --network $(NETWORK) \
	    -w /usr/app/$(DBT_IMAGE) \
	    $(DBT_IMAGE) \
	    dbt build --target dev --target-path target/dev \
	        --select state:modified+ --defer --favor-state --state target/prod

# --- dlt ingestion (official path: run inside the Compose network) ---

dlt-build:
	docker build -t $(DLT_IMAGE) dlt/

# Requires the stack to be up (`docker compose up -d`).
# Pick the CSV to ingest with DLT_TABLE, e.g. `make dlt-run DLT_TABLE=netflix_titles`.
dlt-run: dlt-build
	docker run --rm \
	    --env-file $(PWD)/dlt/.env.docker \
	    --network $(NETWORK) \
	    $(DLT_IMAGE) \
	    python filesystem_pipeline.py -t $(DLT_TABLE)

# Jogos do Metacritic: carga incremental (merge/upsert) em raw.raw_games.
# `make dlt-games` carrega tudo; `make dlt-games GAMES_MAX_YEAR=2010` carrega só até 2010
# (para demonstrar que a carga seguinte insere apenas o que falta, sem duplicar).
GAMES_MAX_YEAR ?=
dlt-games: dlt-build
	docker run --rm \
	    --env-file $(PWD)/dlt/.env.docker \
	    --network $(NETWORK) \
	    $(DLT_IMAGE) \
	    python games_pipeline.py $(if $(GAMES_MAX_YEAR),--max-year $(GAMES_MAX_YEAR),)

# Contagem de linhas e de chaves distintas em raw.raw_games (evidência do merge).
games-count:
	docker compose exec trino trino --execute \
	    "SELECT count(*) AS linhas, count(DISTINCT game_id) AS chaves FROM raw.raw_games.games_metacritic"

dbt-shell:
	docker run --rm -v $(PWD)/dbt/$(DBT_IMAGE):/usr/app/$(DBT_IMAGE) \
	    -e DBT_TARGET=$(DBT_TARGET) \
	    -e DBT_TARGET_PATH=target/$(DBT_TARGET) \
	    -p 8082:8082 \
	    --env-file $(PWD)/dbt/.env \
		--network $(NETWORK) \
		-w /usr/app/$(DBT_IMAGE) -it $(DBT_IMAGE) \
		bash

docs-generate:
	docker run --rm \
	  -v $(PWD)/dbt/$(DBT_IMAGE):/usr/app/$(DBT_IMAGE) \
	  --env-file $(PWD)/dbt/.env \
	  -e DBT_TARGET=$(DBT_TARGET) \
	  --network $(NETWORK) \
	  -w /usr/app/$(DBT_IMAGE) \
	  $(DBT_IMAGE) \
	  dbt docs generate

docs: docs-generate
	docker run --rm \
	  -v $(PWD)/dbt/$(DBT_IMAGE):/usr/app/$(DBT_IMAGE) \
	  --env-file $(PWD)/dbt/.env \
	  -e DBT_TARGET=$(DBT_TARGET) \
	  -p 8082:8082 \
	  --network $(NETWORK) \
	  -w /usr/app/$(DBT_IMAGE)/target \
	  -it $(DBT_IMAGE) \
	  python3 -m http.server 8082

# --- agente MCP (roda no host, fala com o Cube publicado em localhost:4000) ---

mcp-install:
	python3 -m venv mcp/.venv && mcp/.venv/bin/pip install -r mcp/requirements.txt

mcp-test:
	mcp/.venv/bin/python -m unittest discover -s mcp/tests -v

mcp-demo:
	mcp/.venv/bin/python mcp/demo.py

# Pergunta dos jogos: a distância crítica × público mudou ao longo dos anos?
mcp-demo-games:
	mcp/.venv/bin/python mcp/demo.py mudou ao longo dos anos
