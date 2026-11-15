"""Servidor MCP de pedidos de delivery.

Expõe ao Claude, como ferramentas (tools), o acesso somente leitura ao
banco SQLite gerado por `gerar_dados.py`. O Claude inicia este arquivo
como um processo e conversa com ele pelo transporte stdio (entrada e
saída padrão); por isso nada aqui pode usar `print`, que corromperia as
mensagens do protocolo. Logs vão para a saída de erro (stderr).

Para rodar manualmente (fica esperando mensagens MCP na entrada padrão):
    uv run python src/servidor.py
"""

import inspect
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import banco
from validador import ConsultaInvalida

# Permite apontar para outro arquivo (útil em testes); o padrão é data/pedidos.db.
CAMINHO_BANCO = Path(os.environ.get("MCP_PEDIDOS_DB", banco.CAMINHO_PADRAO))

# Registro de cada chamada de ferramenta, uma linha JSON por chamada. É a
# fonte dos exemplos em exemplos/perguntas.md: mostra o que o Claude pediu
# de fato (inclusive o SQL exato e os erros), sem depender da memória do
# modelo. Fica fora do git. MCP_PEDIDOS_LOG vazio desliga o registro.
CAMINHO_LOG = os.environ.get(
    "MCP_PEDIDOS_LOG", str(Path(__file__).resolve().parent.parent / "logs" / "chamadas.jsonl")
)
_trava_log = threading.Lock()  # ferramentas síncronas rodam em threads
_logger = logging.getLogger("mcp_pedidos")

NomeTabela = Literal[tuple(banco.DESCRICOES)]

# Instruções gerais, enviadas ao Claude quando ele se conecta ao servidor.
# Valem para o servidor inteiro; cada ferramenta tem a sua descrição própria.
INSTRUCOES = """\
Banco de dados fictício de uma plataforma de delivery na cidade de Vila Aurora,
com pedidos de 01/08/2026 a 31/10/2026. Use estas ferramentas para responder
perguntas de negócio (volume de pedidos, faturamento, ticket médio, tempo de
entrega, notas, cancelamentos) com números calculados a partir dos dados, em vez
de estimar.

Fluxo sugerido:
- Para as métricas padrão de um período (pedidos, faturamento, ticket médio,
  tempo médio de entrega, nota média, taxa de cancelamento), use resumo_periodo.
- Para qualquer outra pergunta, confira as colunas com listar_tabelas e
  descrever_tabela e depois escreva a consulta SQL em consultar.

O acesso é somente leitura. Ao responder, diga em que período e com qual
critério o número foi calculado (por exemplo, se incluiu pedidos cancelados).
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


def _registrar(registro):
    if not CAMINHO_LOG:
        return
    try:
        caminho = Path(CAMINHO_LOG)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        linha = json.dumps(registro, ensure_ascii=False, default=str)
        with _trava_log, caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(linha + "\n")
    except OSError as erro:
        # Falha no log nunca derruba a ferramenta; avisa no stderr.
        _logger.warning("Não foi possível gravar o log de chamadas: %s", erro)


def _executar(ferramenta, argumentos, funcao):
    """Roda `funcao()`, registra a chamada e converte erros esperados em ToolError.

    ToolError é o jeito de devolver um erro que o modelo consegue ler: a
    chamada volta com is_error=True e a mensagem no conteúdo. Qualquer outra
    exceção chegaria ao Claude só como "Error executing tool".
    """
    inicio = time.monotonic()
    registro = {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "ferramenta": ferramenta,
        "argumentos": argumentos,
    }
    try:
        resultado = funcao()
    except (ConsultaInvalida, banco.ErroConsulta) as erro:
        registro.update(duracao_ms=round((time.monotonic() - inicio) * 1000), erro=str(erro))
        _registrar(registro)
        raise ToolError(str(erro)) from erro
    registro.update(duracao_ms=round((time.monotonic() - inicio) * 1000), resultado=resultado)
    _registrar(registro)
    return resultado


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
    return _executar("listar_tabelas", {},
                     lambda: {"tabelas": banco.listar_tabelas(CAMINHO_BANCO)})


@servidor.tool(title="Descrever tabela", annotations=SOMENTE_LEITURA)
def descrever_tabela(
    # O parâmetro se chamava `nome`, mas no primeiro teste o Claude o chamou
    # de `tabela` por conta própria; o nome mais óbvio para o modelo é o melhor.
    tabela: Annotated[NomeTabela, Field(description="Nome exato da tabela a descrever.")],
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
    return _executar("descrever_tabela", {"tabela": tabela},
                     lambda: banco.descrever_tabela(tabela, CAMINHO_BANCO))


class ResultadoConsulta(TypedDict):
    colunas: list[str]
    linhas: list[list[Any]]
    linhas_devolvidas: int
    truncado: bool
    aviso: NotRequired[str]


# A descrição é montada com f-string para citar os limites reais; por isso
# vai no parâmetro `description` do decorador (f-string não vira docstring).
DESCRICAO_CONSULTAR = f"""Executa uma consulta SQL de leitura no banco de pedidos e devolve as linhas.

    Use para qualquer pergunta que resumo_periodo não responda: rankings,
    comparações por bairro, restaurante, categoria, hora ou dia da semana,
    itens mais vendidos etc. Antes, confira nomes e regras das colunas com
    descrever_tabela.

    Regras:
    - Só SELECT (ou WITH ... SELECT), um comando por vez; o banco é somente leitura.
    - Dialeto SQLite: datas são texto, use strftime('%Y-%m', data_hora) para
      mês, strftime('%H', data_hora) para hora e strftime('%w', data_hora)
      para dia da semana (0 = domingo). Não existem EXTRACT nem DATE_TRUNC.
    - Devolve no máximo {banco.LIMITE_LINHAS} linhas e a consulta é interrompida após
      {banco.TEMPO_LIMITE_S:g} segundos. Agregue no próprio SQL (COUNT, SUM, AVG,
      GROUP BY) e use ORDER BY ... LIMIT em rankings, em vez de trazer
      linhas brutas.
    - valor_total já inclui a taxa de entrega; filtre status = 'entregue'
      quando a métrica não deve contar cancelados (faturamento, ticket médio).

    Se a consulta falhar, a mensagem de erro diz o motivo (inclusive o erro
    do SQLite, como coluna inexistente): corrija e tente de novo.
    """


@servidor.tool(title="Consultar com SQL", description=inspect.cleandoc(DESCRICAO_CONSULTAR),
               annotations=SOMENTE_LEITURA)
def consultar(
    sql: Annotated[str, Field(description=(
        "Um único comando SELECT (ou WITH ... SELECT) no dialeto do SQLite. "
        "Sem ponto e vírgula entre comandos e sem comandos de escrita."
    ))],
) -> ResultadoConsulta:
    def rodar():
        resultado = banco.executar_consulta(sql, CAMINHO_BANCO)
        resposta = {**resultado, "linhas_devolvidas": len(resultado["linhas"])}
        if resultado["truncado"]:
            resposta["aviso"] = (
                f"O resultado tinha mais de {banco.LIMITE_LINHAS} linhas e foi cortado. "
                "Agregue com GROUP BY ou use LIMIT para obter o número completo."
            )
        return resposta

    return _executar("consultar", {"sql": sql}, rodar)


class ResumoPeriodo(TypedDict):
    data_inicio: str
    data_fim: str
    pedidos: int
    entregues: int
    cancelados: int
    faturamento: float
    ticket_medio: float | None
    tempo_medio_entrega_min: float | None
    nota_media: float | None
    taxa_cancelamento_pct: float | None
    aviso: NotRequired[str]


@servidor.tool(title="Resumo de um período", annotations=SOMENTE_LEITURA)
def resumo_periodo(
    data_inicio: Annotated[str, Field(description="Primeiro dia do período, AAAA-MM-DD (incluído).")],
    data_fim: Annotated[str, Field(description="Último dia do período, AAAA-MM-DD (incluído).")],
) -> ResumoPeriodo:
    """Calcula as métricas padrão dos pedidos de um período, sem precisar de SQL.

    Use quando a pergunta for sobre os indicadores gerais de um intervalo de
    datas, como "como foi outubro?" ou "qual o ticket médio em setembro?".
    Para um mês inteiro, passe o primeiro e o último dia do mês. Para
    comparar períodos, chame uma vez para cada período. Para quebrar por
    bairro, restaurante, hora etc., use consultar.

    Definições das métricas:
    - pedidos: todos os pedidos feitos no período (entregues + cancelados);
    - faturamento: soma de valor_total dos pedidos entregues, em R$
      (inclui taxa de entrega; cancelados não faturam);
    - ticket_medio: faturamento dividido pelo número de pedidos entregues;
    - tempo_medio_entrega_min: média, em minutos, dos pedidos entregues;
    - nota_media: média das notas (1 a 5) dos pedidos entregues e avaliados;
    - taxa_cancelamento_pct: cancelados / pedidos, em porcentagem.

    Os dados cobrem de 2026-08-01 a 2026-10-31.
    """
    return _executar("resumo_periodo", {"data_inicio": data_inicio, "data_fim": data_fim},
                     lambda: banco.resumo_periodo(data_inicio, data_fim, CAMINHO_BANCO))


if __name__ == "__main__":
    servidor.run()  # transporte padrão: stdio
