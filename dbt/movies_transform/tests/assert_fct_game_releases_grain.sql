-- Grão do fato de jogos: juntar as dimensões não altera a contagem de lançamentos.
-- Se uma dimensão tiver chave duplicada (ex.: uma plataforma repetida no seed),
-- o join multiplica as linhas e este teste falha.

with base as (

    select count(*) as n from {{ ref('fct_game_releases') }}

),

sliced as (

    select count(*) as n
    from {{ ref('fct_game_releases') }} f
    inner join {{ ref('dim_platform') }} p on f.platform_key = p.platform_key
    inner join {{ ref('dim_game_genre') }} g on f.genre_key = g.genre_key
    inner join {{ ref('dim_publisher') }} u on f.publisher_key = u.publisher_key

)

select base.n as base_count, sliced.n as sliced_count
from base
cross join sliced
where base.n <> sliced.n
