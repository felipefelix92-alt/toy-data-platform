"""Servidor MCP mínimo sobre a camada semântica do Cube.

Quatro ferramentas — o agente *descobre* o que existe e consulta o que é
governado, em vez de escrever SQL livre (é o ponto de *context engineering*):

  - list_models     → {"models": [{name, description}]}
  - list_measures   → {"measures": [{name, type, description}]}
  - list_dimensions → {"dimensions": [{name, type, description}]}
  - query           → {"columns": [...], "rows": [[...]], "row_count": N}

As ferramentas devolvem **objetos** (e não listas soltas) para o agente ler um
contrato explícito, igual em todas: o que veio é o que está escrito na chave.

Fala com o Cube pela REST API (`/meta`, `/load`). Enxerga só as views governadas
— fachadas planas como `titles_overview` e `games_overview` — para que o agente
não precise conhecer os cubos internos nem os joins.

Com mais de uma view, o agente começa por `list_models` e passa `model` nas outras
ferramentas; sem `model`, vale a primeira da lista (compatível com o uso antigo).
`CUBE_MODELS` (lista separada por vírgula) define as views governadas; `CUBE_MODEL`
sozinho continua funcionando e restringe a uma view só. `CUBE_URL` aponta o Cube.

Membro fora do catálogo vira `ToolError`: a mensagem (com os membros válidos)
chega ao modelo num resultado `is_error`, que é como ele se corrige sozinho.
Falha de infraestrutura (Cube fora do ar) continua sendo crash — aparece no log
do servidor, não no contexto do agente.

Rodar (stdio, o transporte que os clientes MCP usam):

    python server.py
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from cube import CubeClient, dimensions_of, measures_of, table

def _configured_models() -> list[str]:
    """Views governadas: `CUBE_MODELS` (lista) ou, no uso antigo, só `CUBE_MODEL`."""
    if "CUBE_MODELS" in os.environ:
        names = os.environ["CUBE_MODELS"].split(",")
    elif "CUBE_MODEL" in os.environ:
        names = [os.environ["CUBE_MODEL"]]
    else:
        names = ["titles_overview", "games_overview"]
    return [name.strip() for name in names if name.strip()]


MODELS = _configured_models()
client = CubeClient()

server = MCPServer(
    "camada-semantica",
    instructions=(
        "Camada semântica governada (Cube): títulos de streaming e jogos do Metacritic. "
        "Comece por list_models para ver as views governadas; descubra as medidas e "
        "dimensões de uma view com list_measures/list_dimensions (passando `model`) e "
        "consulte com query. Não invente métricas: use só o que o catálogo expõe."
    ),
)


def _model(model: str | None) -> str:
    """A view pedida, validada; sem `model`, a primeira governada."""
    if model is None:
        return MODELS[0]
    if model not in MODELS:
        raise ToolError(f"view fora da camada governada: {model}. Views disponíveis: {', '.join(MODELS)}.")
    return model


def _qualify(member: str, model: str) -> str:
    """Aceita `avg_rating` ou `titles_overview.avg_rating` e devolve o nome completo."""
    return member if "." in member else f"{model}.{member}"


def _governed_members(model: str) -> set[str]:
    """Membros que a view governada expõe (o que o agente pode pedir)."""
    catalog = client.meta()
    known = {member["name"] for member in measures_of(catalog, model)}
    known |= {member["name"] for member in dimensions_of(catalog, model)}
    return known


def _qualified(members: list[str], known: set[str], kind: str, model: str) -> list[str]:
    """Qualifica e valida uma lista de membros contra o catálogo governado."""
    qualified = [_qualify(member, model) for member in members]
    unknown = [member for member in qualified if member not in known]
    if unknown:
        raise ToolError(
            f"{kind} fora da camada governada: {', '.join(unknown)}. "
            f"Membros disponíveis: {', '.join(sorted(known))}."
        )
    return qualified


def _governed_filters(filters: list[dict[str, Any]], known: set[str], model: str) -> list[dict[str, Any]]:
    """Valida o membro de cada filtro; filtros compostos ficam de fora."""
    governed = []
    for condition in filters:
        if "member" not in condition:
            raise ToolError(
                "filtros compostos (and/or) não são suportados: use filtros simples "
                "no formato {\"member\": ..., \"operator\": ..., \"values\": [...]}."
            )
        governed.append({**condition, "member": _qualified([condition["member"]], known, "filtro", model)[0]})
    return governed


@server.tool(
    description=(
        "Lista as views governadas da camada semântica: um objeto {\"models\": "
        "[{name, description}]}. Cada view é um assunto (ex.: títulos, jogos); passe "
        "o nome em `model` nas outras ferramentas."
    )
)
def list_models() -> dict[str, Any]:
    descriptions = {cube["name"]: cube.get("description", "") for cube in client.meta().get("cubes", [])}
    return {
        "models": [
            {"name": name, "description": descriptions.get(name, "")}
            for name in MODELS
            if name in descriptions
        ]
    }


@server.tool(
    description=(
        "Lista as medidas governadas de uma view (`model`; padrão: a primeira de "
        "list_models): um objeto {\"measures\": [{name, type, description}]}. Use os "
        "nomes retornados em `query` — não invente métricas."
    )
)
def list_measures(model: str | None = None) -> dict[str, Any]:
    return {"measures": measures_of(client.meta(), _model(model))}


@server.tool(
    description=(
        "Lista as dimensões governadas de uma view (`model`): um objeto "
        "{\"dimensions\": [{name, type, description}]}. Qualquer dimensão pode "
        "fatiar qualquer medida da mesma view."
    )
)
def list_dimensions(model: str | None = None) -> dict[str, Any]:
    return {"dimensions": dimensions_of(client.meta(), _model(model))}


@server.tool(
    description=(
        "Consulta a camada semântica: medidas × dimensões de uma view (`model`), com "
        "filtros opcionais (formato do Cube: {member, operator, values}) e limite. "
        "Devolve uma tabela {columns, rows, row_count}. Só aceita membros do catálogo "
        "governado daquela view."
    )
)
def query(
    measures: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 1000,
    model: str | None = None,
) -> dict[str, Any]:
    if not measures:
        raise ToolError("informe ao menos uma medida.")
    view = _model(model)
    known = _governed_members(view)
    qualified_measures = _qualified(measures, known, "medida", view)
    qualified_dimensions = _qualified(dimensions or [], known, "dimensão", view)
    rows = client.load(
        {
            "measures": qualified_measures,
            "dimensions": qualified_dimensions,
            "filters": _governed_filters(filters or [], known, view),
            "limit": limit,
        }
    )
    # Colunas na ordem em que a tabela se lê: primeiro as dimensões, depois as medidas.
    return table(qualified_dimensions + qualified_measures, rows)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
