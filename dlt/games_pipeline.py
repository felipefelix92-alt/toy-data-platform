"""Ingestão incremental dos jogos do Metacritic (merge/upsert no Iceberg).

Diferente de `filesystem_pipeline.py` (que faz `replace` da tabela inteira), esta
fonte é carregada com `write_disposition=merge` + `strategy=upsert`: cada linha
tem uma chave natural (`game_id` = nome | plataforma | ano) e reexecutar a carga
**atualiza** as linhas que já existem e **insere** só as novas. É o comportamento
de uma fonte que cresce com o tempo (novos lançamentos, notas de usuário que
saem de "tbd" para um número), sem regravar a tabela toda a cada execução.

O upsert do Iceberg (pyiceberg) exige chave única dentro do lote — com chave
repetida ele recusa a carga inteira ("Duplicate rows found in source dataset
based on the key columns"). A fonte tem duplicatas reais, então elas são
consolidadas aqui, de forma explícita e logada (ver `consolidate_duplicates`).

Uso (dentro da rede do Compose, como o resto do dlt):

    python games_pipeline.py                  # carga completa
    python games_pipeline.py --max-year 2010  # só lançamentos até 2010 (simula uma carga parcial)
"""

from __future__ import annotations

import argparse

import dlt
import pandas as pd

SOURCE_FILE = "data/games_metacritic.csv"
TABLE_NAME = "games_metacritic"
DATASET_NAME = "raw_games"  # vira o schema `raw.raw_games` no Trino

KEY_COLUMNS = ["Name", "Platform", "Year_of_Release"]
SALES_COLUMNS = ["NA_Sales", "EU_Sales", "JP_Sales", "Other_Sales", "Global_Sales"]


def build_key(frame: pd.DataFrame) -> pd.Series:
    """Chave natural do lançamento: o mesmo jogo em outra plataforma é outro lançamento."""
    year = frame["Year_of_Release"].astype("Int64").astype("string").fillna("")
    return frame["Name"].str.strip() + "|" + frame["Platform"].str.strip() + "|" + year


def consolidate_duplicates(frame: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por `game_id`, para o upsert aceitar o lote.

    A fonte traz o mesmo lançamento em duas linhas (ex.: Madden NFL 13 / PS3 / 2012:
    uma com 2,56 mi de vendas e outra com 0,01 mi, notas idênticas). As vendas são
    aditivas, então são somadas; os demais atributos vêm da linha de maior venda.
    """
    duplicated = frame["game_id"].duplicated(keep=False)
    if duplicated.any():
        keys = sorted(frame.loc[duplicated, "game_id"].unique())
        print(f"[games] {duplicated.sum()} linhas com chave repetida consolidadas: {keys}")
    ordered = frame.sort_values("Global_Sales", ascending=False)
    first = ordered.groupby("game_id", sort=False).first()
    first[SALES_COLUMNS] = ordered.groupby("game_id", sort=False)[SALES_COLUMNS].sum()
    return first.reset_index()


def read_games(max_year: int | None) -> pd.DataFrame:
    frame = pd.read_csv(SOURCE_FILE)

    # Sem nome não há chave natural (são 2 linhas sem nome, sem notas e sem vendas
    # relevantes). Descartar aqui é melhor do que inventar uma chave.
    without_name = frame["Name"].isna()
    if without_name.any():
        print(f"[games] {without_name.sum()} linhas sem nome descartadas (sem chave natural)")
    frame = frame[~without_name].copy()

    if max_year is not None:
        frame = frame[frame["Year_of_Release"] <= max_year]

    frame["game_id"] = build_key(frame)
    return consolidate_duplicates(frame)


@dlt.resource(
    name=TABLE_NAME,
    primary_key="game_id",
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    table_format="iceberg",
)
def games(max_year: int | None = None):
    yield read_games(max_year)


def main(max_year: int | None) -> None:
    pipeline = dlt.pipeline(
        pipeline_name="iceberg_games_merge",
        destination="filesystem",
        dataset_name=DATASET_NAME,
        progress="log",
    )
    load_info = pipeline.run(games(max_year))
    print(load_info)
    print(pipeline.last_trace.last_normalize_info)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga incremental (merge) dos jogos do Metacritic.")
    parser.add_argument(
        "--max-year",
        type=int,
        default=None,
        help="carrega só lançamentos até este ano (para demonstrar a carga incremental)",
    )
    args = parser.parse_args()
    main(args.max_year)
