"""Servidor MCP de pedidos de delivery.

Expõe ao Claude, como ferramentas (tools), o acesso somente leitura ao
banco SQLite gerado por `gerar_dados.py`. O Claude inicia este arquivo
como um processo e conversa com ele pelo transporte stdio (entrada e
saída padrão); por isso nada aqui pode usar `print`, que corromperia as
mensagens do protocolo. Logs vão para a saída de erro (stderr).

Para rodar manualmente (fica esperando mensagens MCP na entrada padrão):
    uv run python src/servidor.py
"""

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import banco

# Permite apontar para outro arquivo (útil em testes); o padrão é data/pedidos.db.
CAMINHO_BANCO = Path(os.environ.get("MCP_PEDIDOS_DB", banco.CAMINHO_PADRAO))

NomeTabela = Literal[tuple(banco.DESCRICOES)]

# Instruções gerais, enviadas ao Claude quando ele se conecta ao servidor.
# Valem para o servidor inteiro; cada ferramenta tem a sua descrição própria.
INSTRUCOES = """\
Banco de dados fictício de uma plataforma de delivery na cidade de Vila Aurora,
com pedidos de 01/08/2026 a 31/10/2026. Use estas ferramentas para responder
perguntas de negócio (volume de pedidos, faturamento, ticket médio, tempo de
entrega, notas, cancelamentos) com números calculados a partir dos dados, em vez
de estimar.

Antes de escrever SQL, confira os nomes e o significado das colunas com
listar_tabelas e descrever_tabela. O acesso é somente leitura.
"""

# Ferramentas que só leem dados. As anotações são dicas para o cliente
# (por exemplo, o Claude pode chamá-las sem pedir confirmação ao usuário).
SOMENTE_LEITURA = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

servidor = MCPServer("pedidos", instructions=INSTRUCOES)


# Tipos de retorno. Declarar o formato com TypedDict faz o SDK publicar um
# esquema de saída (outputSchema) e devolver o resultado também como dado
# estruturado, além do texto JSON.

class Tabela(TypedDict):
    nome: str
    descricao: str
    linhas: int


class ListaTabelas(TypedDict):
    tabelas: list[Tabela]


class Coluna(TypedDict):
    nome: str
    tipo: str
    descricao: str
    aceita_nulo: bool
    valores_distintos: int
    nulos: int
    chave_primaria: NotRequired[bool]
    referencia: NotRequired[str]
    valores_possiveis: NotRequired[list[Any]]
    minimo: NotRequired[Any]
    maximo: NotRequired[Any]
    exemplos: NotRequired[list[Any]]


class DescricaoTabela(TypedDict):
    nome: str
    descricao: str
    colunas: list[Coluna]


@servidor.tool(title="Listar tabelas", annotations=SOMENTE_LEITURA)
def listar_tabelas() -> ListaTabelas:
    """Lista as tabelas do banco de pedidos, com o que cada uma guarda e quantas linhas tem.

    Use primeiro, para se orientar, sempre que for responder uma pergunta sobre
    os dados e ainda não souber quais tabelas existem. Depois use
    descrever_tabela para ver as colunas das tabelas que interessam.
    """
    try:
        return {"tabelas": banco.listar_tabelas(CAMINHO_BANCO)}
    except banco.ErroConsulta as erro:
        raise ToolError(str(erro)) from erro


@servidor.tool(title="Descrever tabela", annotations=SOMENTE_LEITURA)
def descrever_tabela(
    nome: Annotated[NomeTabela, Field(description="Nome exato da tabela a descrever.")],
) -> DescricaoTabela:
    """Mostra as colunas de uma tabela: tipo, significado, nulos e exemplos de valores.

    Use antes de escrever uma consulta SQL, para acertar nomes de colunas,
    formatos e regras de negócio. Para colunas de texto com poucos valores
    (como status, bairro e categoria), devolve a lista completa de valores
    possíveis, útil para filtros WHERE. Para as demais, devolve mínimo,
    máximo e alguns exemplos (por exemplo, o período coberto por data_hora).
    Leia a descrição das colunas: ela traz regras importantes, como o fato de
    valor_total já incluir a taxa de entrega.
    """
    try:
        return banco.descrever_tabela(nome, CAMINHO_BANCO)
    except banco.ErroConsulta as erro:
        raise ToolError(str(erro)) from erro


if __name__ == "__main__":
    servidor.run()  # transporte padrão: stdio
