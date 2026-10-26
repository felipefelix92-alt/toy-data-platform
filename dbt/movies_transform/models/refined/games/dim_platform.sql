-- Dimensão de plataforma: vem do seed `game_platforms` (nome, fabricante e tipo).
--
-- O fabricante não existe na fonte — é conhecimento de negócio versionado como seed.
-- O teste de `relationships` do fato contra esta dimensão garante que nenhuma
-- plataforma nova chegue da fonte sem estar mapeada aqui.

select
    platform_key,
    platform_name,
    manufacturer,
    platform_kind
from {{ ref('game_platforms') }}
