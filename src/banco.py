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


# Documentação de negócio do banco. É o que o Claude lê para entender o
# significado de cada tabela e coluna, então faz parte do "prompt" do
# servidor. Um teste garante que toda coluna real tenha descrição aqui.
DESCRICOES = {
    "restaurantes": {
        "descricao": "Restaurantes parceiros cadastrados na plataforma (30 no total).",
        "colunas": {
            "id": "Identificador do restaurante.",
            "nome": "Nome fantasia do restaurante.",
            "categoria": "Tipo de cozinha (Pizzaria, Japonesa, Hambúrguer etc.).",
            "bairro": "Bairro onde o restaurante fica.",
        },
    },
    "clientes": {
        "descricao": (
            "Clientes da plataforma. Não há nome nem dado pessoal, apenas o "
            "bairro de entrega e a data de cadastro."
        ),
        "colunas": {
            "id": "Identificador do cliente.",
            "bairro": "Bairro onde o cliente recebe os pedidos.",
            "data_cadastro": "Data de cadastro no formato AAAA-MM-DD.",
        },
    },
    "pedidos": {
        "descricao": (
            "Um registro por pedido feito entre 01/08/2026 e 31/10/2026. "
            "Liga-se a clientes (cliente_id) e a restaurantes (restaurante_id)."
        ),
        "colunas": {
            "id": "Identificador do pedido.",
            "cliente_id": "Cliente que fez o pedido (clientes.id).",
            "restaurante_id": "Restaurante que recebeu o pedido (restaurantes.id).",
            "data_hora": (
                "Momento do pedido, texto no formato 'AAAA-MM-DD HH:MM:SS' (hora local). "
                "Use strftime('%Y-%m', data_hora) para mês, strftime('%H', ...) para hora "
                "e strftime('%w', ...) para dia da semana (0 = domingo)."
            ),
            "valor_total": (
                "Valor pago em R$, JÁ INCLUINDO a taxa de entrega "
                "(soma dos itens + taxa_entrega). Para o valor só da comida, "
                "use valor_total - taxa_entrega."
            ),
            "taxa_entrega": "Taxa de entrega em R$ (0 quando o frete foi grátis).",
            "status": (
                "'entregue' ou 'cancelado'. Pedidos cancelados não têm "
                "tempo_entrega_min nem nota; decida se devem entrar em médias de valor."
            ),
            "tempo_entrega_min": "Minutos entre o pedido e a entrega. NULL se cancelado.",
            "nota": "Avaliação do cliente, de 1 a 5. NULL se não avaliou ou se cancelado.",
        },
    },
    "itens_pedido": {
        "descricao": "Itens de cada pedido (um pedido tem de 1 a 4 itens diferentes).",
        "colunas": {
            "id": "Identificador do item.",
            "pedido_id": "Pedido ao qual o item pertence (pedidos.id).",
            "nome_item": "Nome do prato ou produto.",
            "quantidade": "Quantidade pedida desse item.",
            "preco_unitario": "Preço de uma unidade em R$.",
        },
    },
}

# Colunas de texto com até este número de valores distintos têm todos os
# valores listados em descrever_tabela (ex.: status, bairro, categoria).
MAXIMO_VALORES_LISTADOS = 15


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


def _abrir_conexao_interna(caminho):
    """Conexão somente leitura SEM o authorizer, para consultas fixas do servidor.

    O authorizer bloqueia PRAGMA, que é necessário para ler a estrutura das
    tabelas. Esta conexão só executa consultas escritas neste arquivo, nunca
    texto vindo do Claude, e continua em `mode=ro`.
    """
    conexao = abrir_conexao(caminho)
    conexao.set_authorizer(None)
    return conexao


def listar_tabelas(caminho=CAMINHO_PADRAO):
    """Devolve as tabelas do banco com descrição e número de linhas."""
    conexao = _abrir_conexao_interna(caminho)
    try:
        nomes = [linha[0] for linha in conexao.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY rowid"
        )]
        return [
            {
                "nome": nome,
                "descricao": DESCRICOES.get(nome, {}).get("descricao", ""),
                # Seguro: `nome` veio do próprio sqlite_master, não do usuário.
                "linhas": conexao.execute(f'SELECT COUNT(*) FROM "{nome}"').fetchone()[0],
            }
            for nome in nomes
        ]
    finally:
        conexao.close()


def descrever_tabela(nome, caminho=CAMINHO_PADRAO):
    """Devolve colunas, tipos, descrições e exemplos de valores de uma tabela."""
    conexao = _abrir_conexao_interna(caminho)
    try:
        existentes = {linha[0] for linha in conexao.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        # O nome só é interpolado no SQL depois de conferido contra a lista
        # real de tabelas, o que impede injeção por esse parâmetro.
        if nome not in existentes:
            raise ErroConsulta(
                f"Tabela '{nome}' não existe. Tabelas disponíveis: "
                f"{', '.join(sorted(existentes))}."
            )

        descricoes = DESCRICOES.get(nome, {}).get("colunas", {})
        chaves_estrangeiras = {
            linha[3]: f"{linha[2]}.{linha[4]}"
            for linha in conexao.execute(f'PRAGMA foreign_key_list("{nome}")')
        }
        colunas = []
        for _, coluna, tipo, nao_nulo, _, chave_primaria in conexao.execute(
            f'PRAGMA table_info("{nome}")'
        ):
            distintos, nulos, minimo, maximo = conexao.execute(
                f'SELECT COUNT(DISTINCT "{coluna}"), SUM("{coluna}" IS NULL), '
                f'MIN("{coluna}"), MAX("{coluna}") FROM "{nome}"'
            ).fetchone()
            info = {
                "nome": coluna,
                "tipo": tipo,
                "descricao": descricoes.get(coluna, ""),
                "aceita_nulo": not nao_nulo and not chave_primaria,
                "valores_distintos": distintos,
                "nulos": nulos or 0,
            }
            if chave_primaria:
                info["chave_primaria"] = True
            if coluna in chaves_estrangeiras:
                info["referencia"] = chaves_estrangeiras[coluna]

            if tipo == "TEXT" and distintos <= MAXIMO_VALORES_LISTADOS:
                info["valores_possiveis"] = [linha[0] for linha in conexao.execute(
                    f'SELECT DISTINCT "{coluna}" FROM "{nome}" '
                    f'WHERE "{coluna}" IS NOT NULL ORDER BY 1'
                )]
            else:
                info["minimo"] = minimo
                info["maximo"] = maximo
                info["exemplos"] = [linha[0] for linha in conexao.execute(
                    f'SELECT DISTINCT "{coluna}" FROM "{nome}" '
                    f'WHERE "{coluna}" IS NOT NULL LIMIT 3'
                )]
            colunas.append(info)

        return {
            "nome": nome,
            "descricao": DESCRICOES.get(nome, {}).get("descricao", ""),
            "colunas": colunas,
        }
    finally:
        conexao.close()


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
