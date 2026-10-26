-- Jogos do Metacritic, limpos e tipados. Uma linha por lançamento (`game_id`).
--
-- A raw já chega com chave única (o dlt faz upsert por `game_id`). Aqui só se
-- tipa e normaliza:
--   * `user_score` vem como texto porque a fonte mistura número (0–10) com "tbd"
--     (jogo sem votos suficientes). "tbd" vira nulo, e `user_score_status` guarda
--     o motivo — "sem nota" e "nota ainda não calculada" não são a mesma coisa.
--   * `year_of_release` chega como double (o CSV tem anos vazios). Anos depois da
--     data do snapshot da fonte (dez/2016) não são lançamentos que já aconteceram:
--     viram nulo em `release_year`, e o teste em `tests/` mostra quantos são.

with source as (

    select * from {{ source('raw_games', 'games_metacritic') }}

)

select
    game_id,
    trim(name) as game_name,
    trim(platform) as platform_key,
    cast(year_of_release as integer) as year_of_release_raw,
    case
        when year_of_release <= {{ var('games_snapshot_year') }}
            then cast(year_of_release as integer)
    end as release_year,
    trim(genre) as genre,
    trim(publisher) as publisher,
    trim(developer) as developer,
    rating as esrb_rating,

    cast(critic_score as integer) as critic_score,
    cast(critic_count as integer) as critic_count,
    try_cast(nullif(trim(user_score), 'tbd') as double) as user_score,
    case
        when trim(user_score) = 'tbd' then 'tbd'
        when user_score is null then 'sem nota'
        else 'avaliado'
    end as user_score_status,
    cast(user_count as integer) as user_count,

    global_sales as global_sales_mi
from source
