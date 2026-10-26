{{ config(severity='warn') }}

-- Frescor/consistência da fonte: o snapshot dos jogos é de 22/dez/2016, então
-- nenhum lançamento pode ter ano posterior a 2016.
--
-- A fonte tem casos assim (anos 2017 e 2020) — é um erro real do dado, não do
-- pipeline. Por isso o teste é `warn`: ele denuncia na execução do dbt quantos são,
-- e o modelo trusted trata (esses anos viram nulo em `release_year`). Se o número
-- crescer numa carga futura, o aviso aparece no log do `dbt build`.

select
    game_id,
    name,
    platform,
    year_of_release
from {{ source('raw_games', 'games_metacritic') }}
where year_of_release > {{ var('games_snapshot_year') }}
