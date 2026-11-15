"""Acesso somente leitura ao banco de pedidos.

Toda consulta passa por três camadas de proteção:

1. `validador.validar_consulta`: checa o texto e recusa o que não for um
   único SELECT, com uma mensagem clara.
2. Conexão aberta com `mode=ro`: o próprio SQLite recusa qualquer escrita
   no arquivo, mesmo que algo escape do validador.
3. Authorizer: uma função que o SQLite chama para cada operação ao
   preparar o comando. Só libera leitura de tabelas e chamada de funções;
   ATTACH, PRAGMA, escrita etc. são negados dentro do motor.

Além disso, cada consulta tem limite de linhas devolvidas e de tempo.
"""

import sqlite3
import time
from pathlib import Path

from validador import validar_consulta

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "data" / "pedidos.db"
LIMITE_LINHAS = 200
TEMPO_LIMITE_S = 5.0

# Operações que o authorizer libera. Todo o resto é negado.
_ACOES_PERMITIDAS = {
    sqlite3.SQLITE_SELECT,     # o comando SELECT em si
    sqlite3.SQLITE_READ,       # ler uma coluna de uma tabela
    sqlite3.SQLITE_FUNCTION,   # chamar funções (count, strftime, round...)
    sqlite3.SQLITE_RECURSIVE,  # CTE recursiva (WITH RECURSIVE)
}
# Funções que não fazem sentido numa consulta de análise e podem ser
# usadas para abuso.
_FUNCOES_BLOQUEADAS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class ErroConsulta(Exception):
    """A consulta chegou ao banco, mas falhou (erro de SQL, tempo, permissão)."""


def _authorizer(acao, arg1, arg2, nome_banco, gatilho):
    if acao not in _ACOES_PERMITIDAS:
        return sqlite3.SQLITE_DENY
    if acao == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _FUNCOES_BLOQUEADAS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def abrir_conexao(caminho=CAMINHO_PADRAO):
    """Abre o banco em modo somente leitura, com o authorizer ativo."""
    caminho = Path(caminho).resolve()
    if not caminho.exists():
        raise ErroConsulta(
            f"Banco não encontrado em {caminho}. Gere-o com: "
            "uv run python src/gerar_dados.py"
        )
    # `mode=ro` só funciona com a conexão no formato URI.
    conexao = sqlite3.connect(f"{caminho.as_uri()}?mode=ro", uri=True)
    conexao.set_authorizer(_authorizer)
    return conexao


def executar_consulta(sql, caminho=CAMINHO_PADRAO, limite=LIMITE_LINHAS,
                      tempo_limite=TEMPO_LIMITE_S):
    """Valida e executa uma consulta de leitura.

    Devolve um dicionário com:
    - `colunas`: nomes das colunas;
    - `linhas`: lista de linhas (cada linha é uma lista de valores);
    - `truncado`: True se havia mais linhas que o limite.

    Levanta `validador.ConsultaInvalida` se a consulta for recusada antes
    de executar, ou `ErroConsulta` se ela falhar no banco.
    """
    sql_limpo = validar_consulta(sql)
    conexao = abrir_conexao(caminho)
    try:
        # O progress_handler é chamado a cada N instruções da máquina
        # virtual do SQLite; devolver um valor verdadeiro interrompe a
        # consulta. É assim que se impõe um limite de tempo.
        prazo = time.monotonic() + tempo_limite
        conexao.set_progress_handler(lambda: time.monotonic() > prazo, 10_000)
        try:
            cursor = conexao.execute(sql_limpo)
            linhas = cursor.fetchmany(limite + 1)
        except sqlite3.OperationalError as erro:
            mensagem = str(erro)
            if "interrupted" in mensagem:
                raise ErroConsulta(
                    f"A consulta passou do limite de {tempo_limite:g} s e foi "
                    "interrompida. Simplifique-a ou filtre um período menor."
                ) from erro
            if "not authorized" in mensagem:
                raise ErroConsulta(
                    "A consulta tentou uma operação não permitida (o acesso é "
                    "somente leitura). Use apenas SELECT sobre as tabelas."
                ) from erro
            raise ErroConsulta(f"Erro do SQLite: {mensagem}. Corrija a consulta e tente de novo.") from erro
        except sqlite3.Error as erro:
            raise ErroConsulta(f"Erro do SQLite: {erro}. Corrija a consulta e tente de novo.") from erro

        colunas = [descricao[0] for descricao in cursor.description or []]
        truncado = len(linhas) > limite
        return {
            "colunas": colunas,
            "linhas": [list(linha) for linha in linhas[:limite]],
            "truncado": truncado,
        }
    finally:
        conexao.close()
