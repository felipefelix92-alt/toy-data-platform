-- Fato de lançamentos de jogos: grão de exatamente um lançamento (jogo × plataforma × ano).
--
-- Pergunta que este fato responde: a nota da crítica e a nota do público se
-- afastaram ao longo dos anos? Em que gêneros e plataformas a distância é maior?
--
-- As duas notas vêm em escalas diferentes na fonte: crítica de 0 a 100, usuários de
-- 0 a 10. Aqui a nota de usuário é levada para 0–100 (`user_score_100`, arredondada
-- para não carregar resíduo de ponto flutuante como 70.99999) antes de
-- qualquer comparação; o teste `assert_game_scores_same_scale` falha se alguém
-- voltar a comparar escalas diferentes.
--
-- `score_gap` = crítica − público, só quando o lançamento tem as DUAS notas:
-- positivo = a crítica gostou mais que o público; negativo = o contrário.

with games as (

    select * from {{ ref('games_metacritic') }}

)

select
    game_id as game_key,
    game_name,
    platform_key,
    genre as genre_key,
    coalesce(publisher, 'Unknown') as publisher_key,
    release_year,

    critic_score,
    critic_count,
    round(user_score * 10, 1) as user_score_100,
    user_count,
    user_score_status,
    (critic_score is not null and user_score is not null) as has_both_scores,
    case
        when critic_score is not null and user_score is not null
            then round(critic_score - user_score * 10, 1)
    end as score_gap,

    global_sales_mi
from games
where genre is not null
