-- As duas notas precisam estar na mesma escala (0–100) antes de serem comparadas.
--
-- A fonte traz a crítica em 0–100 e o público em 0–10. Se a conversão for esquecida
-- (ou feita duas vezes), `score_gap` vira um número sem sentido — e nada quebra,
-- o dashboard só mostra a resposta errada.
--
-- Checar só a faixa 0–100 não basta: uma nota de 0–10 esquecida sem conversão também
-- cabe em 0–100. Por isso o teste confere cada lançamento contra a nota original do
-- trusted (`user_score` em 0–10) e recalcula a distância.

select
    f.game_key,
    t.user_score as user_score_original,
    f.user_score_100,
    f.critic_score,
    f.score_gap
from {{ ref('fct_game_releases') }} f
inner join {{ ref('games_metacritic') }} t on t.game_id = f.game_key
where f.critic_score not between 0 and 100
   or abs(f.user_score_100 - t.user_score * 10) > 0.05
   or (f.has_both_scores and abs(f.score_gap - (f.critic_score - t.user_score * 10)) > 0.05)
   or (not f.has_both_scores and f.score_gap is not null)
