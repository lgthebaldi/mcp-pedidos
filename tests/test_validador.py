import pytest

from validador import ConsultaInvalida, validar_consulta


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select count(*) from pedidos",
    "  SELECT * FROM pedidos WHERE status = 'cancelado';  ",
    "SELECT p.id, r.nome FROM pedidos p JOIN restaurantes r ON r.id = p.restaurante_id",
    "WITH mensal AS (SELECT strftime('%m', data_hora) m, COUNT(*) n FROM pedidos GROUP BY 1) "
    "SELECT * FROM mensal",
    "SELECT replace(nome, 'a', 'b') FROM restaurantes",
    # Palavras proibidas dentro de textos não são comandos.
    "SELECT 'DROP TABLE pedidos; DELETE' AS texto",
    "SELECT * FROM pedidos -- comentário com DELETE\n",
    "SELECT /* INSERT */ 1",
    # Nomes de colunas que contêm palavras proibidas como parte da palavra.
    "SELECT data_hora AS updated_at, 1 AS created FROM pedidos",
])
def test_aceita_consultas_de_leitura(sql):
    assert validar_consulta(sql)


def test_remove_comentarios_e_ponto_e_virgula_final():
    assert validar_consulta("SELECT 1; -- fim") == "SELECT 1"
    assert validar_consulta("/* topo */ SELECT 'a;b';") == "SELECT 'a;b'"


@pytest.mark.parametrize("sql, trecho_mensagem", [
    ("INSERT INTO clientes VALUES (999, 'Centro', '2026-01-01')", "INSERT"),
    ("UPDATE pedidos SET valor_total = 0", "UPDATE"),
    ("DELETE FROM pedidos", "DELETE"),
    ("DROP TABLE pedidos", "DROP"),
    ("CREATE TABLE x (a)", "CREATE"),
    ("ALTER TABLE pedidos ADD COLUMN x", "ALTER"),
    ("ATTACH DATABASE '/tmp/x.db' AS x", "ATTACH"),
    ("PRAGMA table_info(pedidos)", "PRAGMA"),
    ("REPLACE INTO clientes VALUES (1, 'Centro', '2026-01-01')", "REPLACE"),
    ("VACUUM", "VACUUM"),
    # CTE seguida de escrita (válido no SQLite, mas não é leitura).
    ("WITH x AS (SELECT 1) DELETE FROM pedidos", "DELETE"),
    ("WITH x AS (SELECT 1) INSERT INTO clientes SELECT * FROM x", "INSERT"),
    # Escrita escondida dentro de um SELECT.
    ("SELECT * FROM pedidos WHERE id IN (SELECT 1); DROP TABLE pedidos", "vários"),
])
def test_recusa_comandos_de_escrita(sql, trecho_mensagem):
    with pytest.raises(ConsultaInvalida, match=trecho_mensagem):
        validar_consulta(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; SELECT 2",
    "SELECT 1; DROP TABLE pedidos",
    "SELECT 1;\n-- comentário\nDELETE FROM pedidos",
    "SELECT 1 /* ; */ ; UPDATE pedidos SET nota = 1",
])
def test_recusa_multiplos_comandos(sql):
    with pytest.raises(ConsultaInvalida, match="apenas um comando"):
        validar_consulta(sql)


@pytest.mark.parametrize("sql", [
    "-- DROP\nDROP TABLE pedidos",
    "/* SELECT */ DELETE FROM pedidos",
])
def test_comentario_nao_disfarca_o_comando(sql):
    with pytest.raises(ConsultaInvalida):
        validar_consulta(sql)


@pytest.mark.parametrize("sql, trecho_mensagem", [
    ("", "vazia"),
    ("   ", "vazia"),
    (";", "vazia"),
    ("-- só comentário", "vazia"),
    (None, "vazia"),
    ("SELECT 'sem fechar", "não fechado"),
    ("SELECT 1 /* sem fechar", "não fechado"),
    ("SELECT " + "1," * 20_000 + "1", "máximo"),
])
def test_recusa_entradas_malformadas(sql, trecho_mensagem):
    with pytest.raises(ConsultaInvalida, match=trecho_mensagem):
        validar_consulta(sql)
