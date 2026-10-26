-- Dimensão de publisher: um publisher por linha. Publisher ausente na fonte entra
-- como 'Unknown' (a fonte já usa esse valor para 201 jogos), a mesma regra do fato.

select distinct
    coalesce(publisher, 'Unknown') as publisher_key
from {{ ref('games_metacritic') }}
