-- Dimensão de gênero de jogo: um gênero por linha. Na fonte de jogos o gênero é
-- valor único (diferente do Netflix, que precisa de tabela de ponte).

select distinct
    genre as genre_key
from {{ ref('games_metacritic') }}
where genre is not null
