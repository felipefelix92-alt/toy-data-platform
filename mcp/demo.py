"""Demo do agente sobre a camada semântica, pelo MCP.

Sobe o servidor MCP (`server.py`) como processo filho e fala com ele pelo
protocolo (stdio) — o mesmo caminho de um cliente MCP de verdade (o trecho de
configuração do cliente está no `README.md`).

O "agente" aqui é um roteiro fixo, **sem LLM**: ele descobre as medidas e
dimensões governadas, confere que o plano do roteiro existe nesse catálogo e só
então consulta. É exatamente o que interessa mostrar em aula — o agente não
escreve SQL, ele escolhe membros governados; e o número vem da mesma definição
que o Superset usa.

    mcp/.venv/bin/python mcp/demo.py [pergunta]

(ou `make mcp-demo`) — sem argumento, roda a primeira pergunta do roteiro.
`make mcp-demo-games` roda a pergunta dos jogos (crítica × público).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = pathlib.Path(__file__).resolve().parent / "server.py"
MODEL = os.environ.get("CUBE_MODEL", "titles_overview")  # a mesma variável que o servidor lê


def member(name: str) -> str:
    """O membro como o catálogo o nomeia (o Cube qualifica com o modelo)."""
    return f"{MODEL}.{name}"


# O roteiro: pergunta de negócio → plano em membros governados. Um agente com
# LLM descobriria esse plano sozinho a partir de `list_measures`/`list_dimensions`.
QUESTIONS: dict[str, dict[str, Any]] = {
    "Qual país tem a melhor nota média entre os que têm pelo menos 20 títulos?": {
        "measures": [member("count_titles"), member("avg_rating")],
        "dimensions": [member("country")],
        "filters": [
            # `set` = país conhecido: o join da ponte preserva os títulos sem país
            # numa linha NULL, que não é um país (ver `cube/README.md`).
            {"member": member("country"), "operator": "set"},
            {"member": member("count_titles"), "operator": "gte", "values": ["20"]},
        ],
        "limit": 1000,
        "rank_by": member("avg_rating"),
    },
    "Quantos títulos e qual a nota média, por gênero?": {
        "measures": [member("count_titles"), member("avg_rating")],
        "dimensions": [member("genre")],
        "limit": 1000,
        "rank_by": None,
    },
    # Jogos: outra view governada. O agente passa `model` para escolher o assunto.
    "A distância entre a nota da crítica e a do público mudou ao longo dos anos?": {
        "model": "games_overview",
        "measures": [
            "games_overview.count_scored_releases",
            "games_overview.avg_critic_score",
            "games_overview.avg_user_score",
            "games_overview.avg_score_gap",
        ],
        "dimensions": ["games_overview.release_year"],
        "filters": [
            # antes de 2000 há poucos jogos com as duas notas (menos de 30 por ano)
            {"member": "games_overview.release_year", "operator": "gte", "values": ["2000"]},
        ],
        "limit": 1000,
        "rank_by": None,
        "trend_of": "games_overview.avg_score_gap",
    },
}


def _parameters() -> StdioServerParameters:
    """O transporte stdio não herda o ambiente; repassamos o que o servidor usa."""
    env = {name: os.environ[name] for name in ("CUBE_URL", "CUBE_MODEL", "CUBE_MODELS") if name in os.environ}
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


def _names(catalog: list[dict[str, Any]]) -> list[str]:
    return [member["name"] for member in catalog]


def _column(columns: list[str], member: str) -> str:
    """A coluna do membro (o Cube a devolve qualificada com o modelo)."""
    short = member.rsplit(".", 1)[-1]
    for column in columns:
        if column.rsplit(".", 1)[-1] == short:
            return column
    raise LookupError(f"a consulta não devolveu a coluna de {member}: {', '.join(columns)}")


def _print_table(columns: list[str], rows: list[list[Any]], indent: str = "      ") -> None:
    headers = [column.rsplit(".", 1)[-1] for column in columns]
    widths = [max([len(header)] + [len(str(row[index])) for row in rows]) for index, header in enumerate(headers)]
    print(indent + "  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    for row in rows:
        print(indent + "  ".join(str(value).ljust(width) for value, width in zip(row, widths)))


def _plan_members(plan: dict[str, Any]) -> list[str]:
    return plan["measures"] + plan["dimensions"]


async def _discover(session: ClientSession, model: str | None) -> set[str]:
    """O agente pergunta o que existe antes de escolher o que consultar."""
    scope = {"model": model} if model else {}
    shown = f'model="{model}"' if model else ""
    if model:
        models = (await session.call_tool("list_models", {})).structured_content["models"]
        print(f"[0] list_models()      → {', '.join(_names(models))}")
    measures = (await session.call_tool("list_measures", scope)).structured_content["measures"]
    dimensions = (await session.call_tool("list_dimensions", scope)).structured_content["dimensions"]
    print(f"[1] list_measures({shown})    → {', '.join(_names(measures))}")
    print(f"[2] list_dimensions({shown})  → {', '.join(_names(dimensions))}")
    return set(_names(measures)) | set(_names(dimensions))


def _print_trend(columns: list[str], rows: list[list[Any]], plan: dict[str, Any]) -> None:
    """Tabela ordenada pela dimensão (ano) e a resposta: como a medida evoluiu."""
    year = columns.index(plan["dimensions"][0])
    measure = columns.index(_column(columns, plan["trend_of"]))
    ordered = sorted((row for row in rows if row[year] is not None), key=lambda row: float(row[year]))
    for row in ordered:
        for index, value in enumerate(row):
            if index != year and value is not None and "." in str(value):
                row[index] = f"{float(value):.1f}"
    _print_table(columns, ordered)
    first, last = ordered[0], ordered[-1]
    flip = next((row for row in ordered if float(row[measure]) > 0), None)
    def side(gap: float) -> str:
        return f"{abs(gap):.1f} pontos {'acima' if gap > 0 else 'abaixo'} do público"

    print(
        f"\nResposta: em {int(float(first[year]))} a crítica ficava {side(float(first[measure]))}; "
        f"em {int(float(last[year]))}, {side(float(last[measure]))}."
    )
    if flip is not None:
        print(f"A distância fica positiva (crítica acima do público) a partir de {int(float(flip[year]))}.")


def run(question: str) -> int:
    plan = QUESTIONS[question]
    print(f"Pergunta: {question}\n")

    async def demo() -> int:
        async with stdio_client(_parameters()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                known = await _discover(session, plan.get("model"))

                invented = [member for member in _plan_members(plan) if member not in known]
                if invented:
                    print(f"\nFora da camada governada: {', '.join(invented)}. Governados: {', '.join(sorted(known))}")
                    return 1

                arguments = {name: value for name, value in plan.items() if name not in ("rank_by", "trend_of")}
                result = await session.call_tool("query", arguments)
                if result.is_error:
                    print(f"\nA consulta governada falhou: {result.content[0].text}")
                    return 1

                print("[3] query(...)         → chamada governada do agente:")
                print("\n".join(f"      {line}" for line in json.dumps(arguments, indent=2, ensure_ascii=False).splitlines()))

                table = result.structured_content
                columns, rows = table["columns"], table["rows"]
                print(f"\n      {table['row_count']} linhas devolvidas pelo Cube\n")

                if "trend_of" in plan:
                    _print_trend(columns, rows, plan)
                    return 0

                rank_by = plan["rank_by"]
                if rank_by is None:
                    _print_table(columns, rows)
                    return 0

                # O contrato governado é medidas × dimensões (+ filtros, limite):
                # ranking é apresentação, então ordenamos aqui, na ordem da medida.
                index = columns.index(_column(columns, rank_by))
                ordered = sorted(rows, key=lambda row: float(row[index]), reverse=True)
                _print_table(columns, ordered[:5])
                top = ordered[0]
                print(
                    f"\nResposta: {top[columns.index(_column(columns, plan['dimensions'][0]))]} — "
                    f"nota média {float(top[index]):.3f} em "
                    f"{int(top[columns.index(_column(columns, 'count_titles'))])} títulos."
                )
                return 0

    return anyio.run(demo)


def _question(argv: list[str]) -> str:
    if not argv:
        return next(iter(QUESTIONS))
    wanted = " ".join(argv).lower()
    for question in QUESTIONS:
        if wanted in question.lower():
            return question
    raise SystemExit("pergunta fora do roteiro do demo. Opções:\n  - " + "\n  - ".join(QUESTIONS))


if __name__ == "__main__":
    sys.exit(run(_question(sys.argv[1:])))
