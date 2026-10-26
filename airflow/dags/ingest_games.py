"""Ingestão incremental dos jogos do Metacritic (dlt, merge/upsert em raw.raw_games).

Diferente de `extract_movies` (carga `@once` com replace), esta DAG pode rodar
todo dia: o merge por `game_id` torna a execução idempotente — rodar duas vezes
com o mesmo arquivo não duplica nada, e um arquivo novo só insere/atualiza o que
mudou. É o que permite agendar a ingestão sem medo de reprocessar.

Usa a mesma imagem do dlt (`my-dlt-pipeline`, `make dlt-build`) e as mesmas
variáveis da DAG de filmes.
"""

from __future__ import annotations

import os
from datetime import datetime

from airflow import models
from airflow.providers.docker.operators.docker import DockerOperator

# Mesmas variáveis da DAG de filmes. Copiadas (e não importadas de
# `extract_movies`) porque importar outro arquivo de DAG também registraria a DAG
# dele aqui, e o Airflow acusaria DAG duplicada.
env_vars = {
    "DESTINATION__FILESYSTEM__BUCKET_URL": "s3://raw",
    "DESTINATION__FILESYSTEM__CREDENTIALS__ENDPOINT_URL": "http://minio:9000",
    "DESTINATION__FILESYSTEM__CREDENTIALS__REGION_NAME": "us-east-1",
    "DESTINATION__FILESYSTEM__CREDENTIALS__AWS_ACCESS_KEY_ID": str(
        os.environ.get("DESTINATION__FILESYSTEM__CREDENTIALS__AWS_ACCESS_KEY_ID")
    ),
    "DESTINATION__FILESYSTEM__CREDENTIALS__AWS_SECRET_ACCESS_KEY": str(
        os.environ.get("DESTINATION__FILESYSTEM__CREDENTIALS__AWS_SECRET_ACCESS_KEY")
    ),
    "NORMALIZE__LOADER_FILE_FORMAT": "parquet",
    "PYICEBERG_CATALOG__RAW__URI": "http://lakekeeper:8181/catalog",
    "PYICEBERG_CATALOG__RAW__WAREHOUSE": "raw",
    "ICEBERG_CATALOG__ICEBERG_CATALOG_NAME": "raw",
    "ICEBERG_CATALOG__ICEBERG_CATALOG_TYPE": "rest",
}

DAG_ID = "ingest_games"

with models.DAG(
    DAG_ID,
    schedule="@daily",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["games", "incremental"],
) as dag:
    DockerOperator(
        docker_url="unix://var/run/docker.sock",
        image="my-dlt-pipeline:latest",
        command=["python", "games_pipeline.py"],
        network_mode="container:airflow_scheduler",
        task_id="ingestion-games-merge",
        auto_remove="force",
        environment={**env_vars},
    )
