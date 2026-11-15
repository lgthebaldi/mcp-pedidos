import sqlite3

import pytest

from banco import ErroConsulta, abrir_conexao, executar_consulta
from validador import ConsultaInvalida


def contar_pedidos(caminho):
    conexao = sqlite3.connect(caminho)
    try:
        return conexao.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
    finally:
        conexao.close()


def test_consulta_simples(caminho_banco):
    resultado = executar_consulta("SELECT COUNT(*) AS total FROM pedidos", caminho_banco)
    assert resultado == {"colunas": ["total"], "linhas": [[5000]], "truncado": False}


def test_consulta_com_join_e_cte(caminho_banco):
    sql = """
        WITH por_bairro AS (
            SELECT c.bairro, AVG(p.valor_total) AS ticket
            FROM pedidos p JOIN clientes c ON c.id = p.cliente_id
            GROUP BY c.bairro
        )
        SELECT bairro, ROUND(ticket, 2) FROM por_bairro ORDER BY bairro
    """
    resultado = executar_consulta(sql, caminho_banco)
    assert resultado["colunas"][0] == "bairro"
    assert len(resultado["linhas"]) == 10


def test_limite_de_linhas(caminho_banco):
    resultado = executar_consulta("SELECT id FROM pedidos", caminho_banco, limite=50)
    assert len(resultado["linhas"]) == 50
    assert resultado["truncado"] is True

    resultado = executar_consulta("SELECT id FROM restaurantes", caminho_banco, limite=50)
    assert len(resultado["linhas"]) == 30
    assert resultado["truncado"] is False


def test_limite_de_tempo(caminho_banco):
    # CTE recursiva infinita: só para por causa do limite de tempo.
    sql = ("WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) "
           "SELECT COUNT(*) FROM r")
    with pytest.raises(ErroConsulta, match="limite de 0.3 s"):
        executar_consulta(sql, caminho_banco, tempo_limite=0.3)


def test_erro_de_sql_traz_mensagem_util(caminho_banco):
    with pytest.raises(ErroConsulta, match="no such column: valor"):
        executar_consulta("SELECT valor FROM pedidos", caminho_banco)


def test_escrita_e_recusada_pelo_validador(caminho_banco):
    with pytest.raises(ConsultaInvalida):
        executar_consulta("DELETE FROM pedidos", caminho_banco)
    assert contar_pedidos(caminho_banco) == 5000


def test_banco_inexistente(tmp_path):
    with pytest.raises(ErroConsulta, match="gerar_dados"):
        executar_consulta("SELECT 1", tmp_path / "nao_existe.db")


# As camadas do banco são testadas sem o validador, executando direto na
# conexão, para provar que seguram sozinhas caso o validador falhe.

@pytest.mark.parametrize("sql", [
    "DELETE FROM pedidos",
    "UPDATE pedidos SET valor_total = 0",
    "INSERT INTO clientes VALUES (999, 'Centro', '2026-01-01')",
    "DROP TABLE pedidos",
    "CREATE TABLE x (a)",
    "ATTACH DATABASE ':memory:' AS x",
    "PRAGMA table_info(pedidos)",
    "SELECT load_extension('x')",
])
def test_conexao_recusa_operacoes_sem_o_validador(caminho_banco, sql):
    conexao = abrir_conexao(caminho_banco)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conexao.execute(sql)
    finally:
        conexao.close()
    assert contar_pedidos(caminho_banco) == 5000


def test_modo_somente_leitura_sem_authorizer(caminho_banco):
    """Mesmo sem o authorizer, o modo `ro` impede a escrita no arquivo."""
    conexao = abrir_conexao(caminho_banco)
    conexao.set_authorizer(None)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conexao.execute("DELETE FROM pedidos")
    finally:
        conexao.close()
    assert contar_pedidos(caminho_banco) == 5000
