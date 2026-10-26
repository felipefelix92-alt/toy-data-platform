"""Testes das ferramentas MCP, por equivalência ao resultado do Cube.

O Cube entra mockado (`fake_cube.py`, com respostas gravadas do Cube real); o
cliente fala com o servidor MCP pelo protocolo (stdio), como qualquer cliente
MCP faria. O que se verifica é comportamento observável pelas ferramentas: o
catálogo que o agente enxerga, a tabela que volta de `query` e a chamada
governada que o servidor faz no Cube — nada de nomes de função internos.

    mcp/.venv/bin/python -m unittest discover -s mcp/tests -v

(ou `make mcp-test`)
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
from typing import Any, Callable

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

MCP_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MCP_DIR))
sys.path.insert(0, str(MCP_DIR / "tests"))

from fake_cube import FakeCube, normalized  # noqa: E402

SERVER = MCP_DIR / "server.py"
MODEL = "titles_overview"
DEVNULL = open(os.devnull, "w", encoding="utf-8")
CUBE = FakeCube()

MEASURES = [
    "titles_overview.count_titles",
    "titles_overview.avg_rating",
    "titles_overview.total_votes",
]
DIMENSIONS = [
    "titles_overview.release_year",
    "titles_overview.title_type",
    "titles_overview.genre",
    "titles_overview.country",
]


def setUpModule() -> None:  # noqa: N802 (nome exigido pelo unittest)
    CUBE.__enter__()


def tearDownModule() -> None:  # noqa: N802
    CUBE.__exit__()


def _parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={"CUBE_URL": CUBE.url, "CUBE_MODEL": MODEL},
    )


async def _session(operation: Callable[[ClientSession], Any]) -> Any:
    async with stdio_client(_parameters(), errlog=DEVNULL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await operation(session)


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Chama uma ferramenta pelo protocolo MCP e devolve o resultado cru."""
    return anyio.run(lambda: _session(lambda session: session.call_tool(name, arguments or {})))


def list_tools() -> Any:
    return anyio.run(lambda: _session(lambda session: session.list_tools()))


def governed_view(what: str) -> list[dict[str, Any]]:
    """As medidas/dimensões da view no catálogo gravado — o oráculo do teste."""
    view = next(cube for cube in CUBE.meta["cubes"] if cube["name"] == MODEL)
    return [
        {"name": member["name"], "type": member["type"], "description": member.get("description", "")}
        for member in view[what]
        if member.get("isVisible", True)
    ]


def table_of(fixture: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    """A mesma tabela que as ferramentas devolvem, montada a partir da resposta do Cube."""
    return {
        "columns": columns,
        "rows": [[row.get(column) for column in columns] for row in fixture["data"]],
        "row_count": len(fixture["data"]),
    }


class ToolsTest(unittest.TestCase):
    def test_expoe_exatamente_as_quatro_ferramentas_governadas(self) -> None:
        self.assertEqual(
            {tool.name for tool in list_tools().tools},
            {"list_models", "list_measures", "list_dimensions", "query"},
        )

    def test_list_models_mostra_so_as_views_governadas(self) -> None:
        # O servidor do teste governa só `titles_overview` (CUBE_MODEL); os cubos
        # internos do catálogo (titles, title_genre...) não aparecem.
        result = call_tool("list_models")
        self.assertFalse(result.is_error)
        view = next(cube for cube in CUBE.meta["cubes"] if cube["name"] == MODEL)
        self.assertEqual(
            result.structured_content,
            {"models": [{"name": MODEL, "description": view.get("description", "")}]},
        )

    def test_view_fora_da_lista_governada_e_recusada(self) -> None:
        before = len(CUBE.load_queries)
        for tool, arguments in [
            ("list_measures", {"model": "titles"}),
            ("query", {"measures": ["count_titles"], "model": "titles"}),
        ]:
            result = call_tool(tool, arguments)
            self.assertTrue(result.is_error)
            self.assertIn("titles", result.content[0].text)
            self.assertIn(MODEL, result.content[0].text)  # o que existe, para o modelo se corrigir
        self.assertEqual(len(CUBE.load_queries), before)

    def test_model_explicito_equivale_ao_padrao(self) -> None:
        self.assertEqual(
            call_tool("list_measures", {"model": MODEL}).structured_content,
            call_tool("list_measures").structured_content,
        )

    def test_query_exige_uma_medida(self) -> None:
        schema = next(tool for tool in list_tools().tools if tool.name == "query").input_schema
        self.assertEqual(schema["required"], ["measures"])

    def test_list_measures_espelha_o_catalogo_do_cube(self) -> None:
        result = call_tool("list_measures")
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content, {"measures": governed_view("measures")})

    def test_list_dimensions_espelha_o_catalogo_do_cube(self) -> None:
        result = call_tool("list_dimensions")
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content, {"dimensions": governed_view("dimensions")})

    def test_o_agente_so_ve_a_fachada_governada(self) -> None:
        # O catálogo do Cube tem os cubos internos; as ferramentas não os expõem.
        self.assertEqual(
            {cube["name"] for cube in CUBE.meta["cubes"]},
            {"titles", "title_genre", "title_country", MODEL},
        )
        listed = call_tool("list_measures").structured_content["measures"]
        listed += call_tool("list_dimensions").structured_content["dimensions"]
        self.assertEqual({member["name"].split(".")[0] for member in listed}, {MODEL})

    def test_query_devolve_o_resultado_do_cube_como_tabela(self) -> None:
        fixture = CUBE.fixture_named("load_country.json")
        columns = ["titles_overview.country", "titles_overview.count_titles", "titles_overview.avg_rating"]
        result = call_tool("query", {"measures": ["count_titles", "avg_rating"], "dimensions": ["country"], "limit": 5})

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content, table_of(fixture, columns))
        self.assertEqual(normalized(CUBE.load_queries[-1]), normalized(fixture["query"]))
        # Nome curto vira membro do modelo governado — é o agente não precisar
        # conhecer cubos nem joins.
        self.assertEqual(CUBE.load_queries[-1]["measures"], [f"{MODEL}.count_titles", f"{MODEL}.avg_rating"])
        self.assertEqual(CUBE.load_queries[-1]["dimensions"], [f"{MODEL}.country"])

    def test_query_repassa_os_filtros_governados(self) -> None:
        fixture = CUBE.fixture_named("load_country_min20.json")
        columns = ["titles_overview.country", "titles_overview.count_titles", "titles_overview.avg_rating"]
        result = call_tool(
            "query",
            {
                "measures": ["count_titles", "avg_rating"],
                "dimensions": ["country"],
                "filters": [{"member": "count_titles", "operator": "gte", "values": ["20"]}],
                "limit": 5,
            },
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content, table_of(fixture, columns))
        sent = CUBE.load_queries[-1]
        self.assertEqual(normalized(sent), normalized(fixture["query"]))
        self.assertEqual(
            sent["filters"], [{"member": f"{MODEL}.count_titles", "operator": "gte", "values": ["20"]}]
        )

    def test_membro_fora_do_catalogo_e_recusado_antes_de_consultar_o_cube(self) -> None:
        before = len(CUBE.load_queries)
        result = call_tool("query", {"measures": ["receita"], "dimensions": ["country"]})

        self.assertTrue(result.is_error)
        message = result.content[0].text
        self.assertIn("receita", message)
        self.assertIn(f"{MODEL}.count_titles", message)  # o que existe, para o modelo se corrigir
        self.assertEqual(len(CUBE.load_queries), before)  # não virou consulta

    def test_query_sem_medida_e_erro(self) -> None:
        result = call_tool("query", {"measures": []})

        self.assertTrue(result.is_error)
        self.assertIn("medida", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
