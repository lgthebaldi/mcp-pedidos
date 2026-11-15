"""Testes do servidor MCP, chamando as ferramentas como um cliente MCP faria.

A maioria usa o `Client` do SDK em memória (o objeto do servidor é passado
direto, sem processo nem transporte). Um teste sobe o servidor de verdade
como subprocesso via stdio, do mesmo jeito que o Claude Code faz.
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from mcp import Client, StdioServerParameters

import banco
import servidor

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def caminho_log(tmp_path, monkeypatch):
    caminho = tmp_path / "chamadas.jsonl"
    monkeypatch.setattr(servidor, "CAMINHO_LOG", str(caminho))
    return caminho


@pytest.fixture
def cliente_em_memoria(caminho_banco, caminho_log, monkeypatch):
    monkeypatch.setattr(servidor, "CAMINHO_BANCO", caminho_banco)

    def chamar(funcao):
        async def rodar():
            async with Client(servidor.servidor) as cliente:
                return await funcao(cliente)
        return asyncio.run(rodar())

    return chamar


def test_ferramentas_publicadas(cliente_em_memoria):
    resposta = cliente_em_memoria(lambda c: c.list_tools())
    ferramentas = {f.name: f for f in resposta.tools}
    assert set(ferramentas) == {"listar_tabelas", "descrever_tabela", "consultar", "resumo_periodo"}
    for ferramenta in ferramentas.values():
        assert len(ferramenta.description) > 80, "a descrição é o que o Claude lê"
        assert ferramenta.annotations.read_only_hint is True
        assert ferramenta.output_schema is not None

    esquema_tabela = ferramentas["descrever_tabela"].input_schema["properties"]["tabela"]
    assert esquema_tabela["enum"] == ["restaurantes", "clientes", "pedidos", "itens_pedido"]

    descricao_consultar = ferramentas["consultar"].description
    assert "200 linhas" in descricao_consultar and "5 segundos" in descricao_consultar
    assert not descricao_consultar.startswith(" ")


def test_listar_tabelas(cliente_em_memoria):
    resultado = cliente_em_memoria(lambda c: c.call_tool("listar_tabelas", {}))
    assert resultado.is_error is False
    tabelas = {t["nome"]: t for t in resultado.structured_content["tabelas"]}
    assert {nome: t["linhas"] for nome, t in tabelas.items()} == {
        "restaurantes": 30, "clientes": 500, "pedidos": 5000, "itens_pedido": 10323,
    }
    assert all(t["descricao"] for t in tabelas.values())


def test_descrever_tabela(cliente_em_memoria):
    resultado = cliente_em_memoria(
        lambda c: c.call_tool("descrever_tabela", {"tabela": "pedidos"})
    )
    assert resultado.is_error is False
    colunas = {c["nome"]: c for c in resultado.structured_content["colunas"]}
    assert colunas["status"]["valores_possiveis"] == ["cancelado", "entregue"]
    assert colunas["cliente_id"]["referencia"] == "clientes.id"
    assert colunas["id"]["chave_primaria"] is True
    assert colunas["data_hora"]["minimo"].startswith("2026-08-01")
    assert colunas["data_hora"]["maximo"].startswith("2026-10-31")
    assert colunas["nota"]["aceita_nulo"] is True
    assert colunas["nota"]["nulos"] > 0
    assert "taxa de entrega" in colunas["valor_total"]["descricao"]


def test_descrever_tabela_inexistente_e_recusada(cliente_em_memoria):
    resultado = cliente_em_memoria(
        lambda c: c.call_tool("descrever_tabela", {"tabela": "sqlite_master"})
    )
    assert resultado.is_error is True
    assert "itens_pedido" in resultado.content[0].text  # mostra as opções válidas


def test_banco_ausente_vira_erro_legivel(cliente_em_memoria, monkeypatch, tmp_path):
    monkeypatch.setattr(servidor, "CAMINHO_BANCO", tmp_path / "nao_existe.db")
    resultado = cliente_em_memoria(lambda c: c.call_tool("listar_tabelas", {}))
    assert resultado.is_error is True
    assert "gerar_dados.py" in resultado.content[0].text


def test_toda_coluna_tem_descricao(caminho_banco):
    """Se uma coluna nova for criada no gerador, a documentação precisa acompanhar."""
    conexao = sqlite3.connect(caminho_banco)
    try:
        for tabela in banco.DESCRICOES:
            colunas = {linha[1] for linha in conexao.execute(f'PRAGMA table_info("{tabela}")')}
            assert colunas == set(banco.DESCRICOES[tabela]["colunas"]), tabela
    finally:
        conexao.close()


def test_servidor_via_stdio(caminho_banco, tmp_path):
    """Sobe `servidor.py` como subprocesso e conversa por stdio, como o Claude Code."""
    parametros = StdioServerParameters(
        command=sys.executable,
        args=[str(RAIZ / "src" / "servidor.py")],
        env={**os.environ, "MCP_PEDIDOS_DB": str(caminho_banco),
             "MCP_PEDIDOS_LOG": str(tmp_path / "chamadas.jsonl")},
    )

    async def rodar():
        async with Client(parametros) as cliente:
            ferramentas = await cliente.list_tools()
            resultado = await cliente.call_tool("listar_tabelas", {})
            return ferramentas, resultado

    ferramentas, resultado = asyncio.run(rodar())
    assert len(ferramentas.tools) == 4
    assert resultado.is_error is False
    assert len(resultado.structured_content["tabelas"]) == 4


# --- consultar -------------------------------------------------------------

def test_consultar_agregacao(cliente_em_memoria):
    sql = ("SELECT strftime('%Y-%m', data_hora) AS mes, COUNT(*) AS pedidos "
           "FROM pedidos GROUP BY mes ORDER BY mes")
    resultado = cliente_em_memoria(lambda c: c.call_tool("consultar", {"sql": sql}))
    assert resultado.is_error is False
    dados = resultado.structured_content
    assert dados["colunas"] == ["mes", "pedidos"]
    assert [linha[0] for linha in dados["linhas"]] == ["2026-08", "2026-09", "2026-10"]
    assert sum(linha[1] for linha in dados["linhas"]) == 5000
    assert dados["linhas_devolvidas"] == 3
    assert dados["truncado"] is False
    assert "aviso" not in dados


def test_consultar_truncado_traz_aviso(cliente_em_memoria):
    resultado = cliente_em_memoria(
        lambda c: c.call_tool("consultar", {"sql": "SELECT id FROM pedidos"})
    )
    dados = resultado.structured_content
    assert dados["truncado"] is True
    assert dados["linhas_devolvidas"] == 200
    assert "GROUP BY" in dados["aviso"]


@pytest.mark.parametrize("sql, trecho", [
    ("DELETE FROM pedidos", "consultas de leitura"),
    ("SELECT 1; DROP TABLE pedidos", "apenas um comando"),
    ("SELECT valor FROM pedidos", "no such column: valor"),
    ("SELECT EXTRACT(MONTH FROM data_hora) FROM pedidos", "Erro do SQLite"),
])
def test_consultar_erros_chegam_legiveis_ao_modelo(cliente_em_memoria, caminho_banco, sql, trecho):
    resultado = cliente_em_memoria(lambda c: c.call_tool("consultar", {"sql": sql}))
    assert resultado.is_error is True
    assert trecho in resultado.content[0].text
    conexao = sqlite3.connect(caminho_banco)
    try:
        assert conexao.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0] == 5000
    finally:
        conexao.close()


# --- resumo_periodo --------------------------------------------------------

def resumo_esperado(caminho, inicio, fim):
    """Mesmas métricas calculadas com um SQL independente, escrito à mão."""
    conexao = sqlite3.connect(caminho)
    try:
        return conexao.execute(
            """
            SELECT COUNT(*),
                   SUM(status = 'cancelado'),
                   ROUND(SUM(IIF(status = 'entregue', valor_total, 0)), 2),
                   ROUND(SUM(IIF(status = 'entregue', valor_total, 0))
                         / SUM(status = 'entregue'), 2),
                   ROUND(AVG(tempo_entrega_min), 1),
                   ROUND(AVG(nota), 2),
                   ROUND(100.0 * SUM(status = 'cancelado') / COUNT(*), 1)
            FROM pedidos WHERE date(data_hora) BETWEEN ? AND ?
            """,
            (inicio, fim),
        ).fetchone()
    finally:
        conexao.close()


@pytest.mark.parametrize("inicio, fim", [
    ("2026-10-01", "2026-10-31"),
    ("2026-08-01", "2026-10-31"),
    ("2026-09-15", "2026-09-15"),  # um único dia: o dia final precisa entrar inteiro
])
def test_resumo_periodo_bate_com_sql_manual(cliente_em_memoria, caminho_banco, inicio, fim):
    resultado = cliente_em_memoria(lambda c: c.call_tool(
        "resumo_periodo", {"data_inicio": inicio, "data_fim": fim}
    ))
    assert resultado.is_error is False
    r = resultado.structured_content
    assert (r["pedidos"], r["cancelados"], r["faturamento"], r["ticket_medio"],
            r["tempo_medio_entrega_min"], r["nota_media"], r["taxa_cancelamento_pct"]) \
        == resumo_esperado(caminho_banco, inicio, fim)
    assert r["entregues"] + r["cancelados"] == r["pedidos"]
    assert "aviso" not in r


def test_resumo_periodo_fora_dos_dados(cliente_em_memoria):
    resultado = cliente_em_memoria(lambda c: c.call_tool(
        "resumo_periodo", {"data_inicio": "2026-01-01", "data_fim": "2026-01-31"}
    ))
    r = resultado.structured_content
    assert r["pedidos"] == 0
    assert r["ticket_medio"] is None
    assert "2026-08-01" in r["aviso"]


@pytest.mark.parametrize("inicio, fim, trecho", [
    ("01/10/2026", "2026-10-31", "AAAA-MM-DD"),
    ("2026-10-01", "2026-10-32", "data_fim inválida"),
    ("2026-10-31", "2026-10-01", "Inverta"),
])
def test_resumo_periodo_datas_invalidas(cliente_em_memoria, inicio, fim, trecho):
    resultado = cliente_em_memoria(lambda c: c.call_tool(
        "resumo_periodo", {"data_inicio": inicio, "data_fim": fim}
    ))
    assert resultado.is_error is True
    assert trecho in resultado.content[0].text


# --- log de chamadas -------------------------------------------------------

def ler_log(caminho):
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]


def test_log_registra_sql_e_resultado(cliente_em_memoria, caminho_log):
    sql = "SELECT COUNT(*) AS total FROM pedidos"
    cliente_em_memoria(lambda c: c.call_tool("consultar", {"sql": sql}))
    [registro] = ler_log(caminho_log)
    assert registro["ferramenta"] == "consultar"
    assert registro["argumentos"] == {"sql": sql}
    assert registro["resultado"]["linhas"] == [[5000]]
    assert "erro" not in registro
    assert registro["duracao_ms"] >= 0
    assert registro["momento"]


def test_log_registra_erros(cliente_em_memoria, caminho_log):
    cliente_em_memoria(lambda c: c.call_tool("consultar", {"sql": "SELECT valor FROM pedidos"}))
    cliente_em_memoria(lambda c: c.call_tool(
        "resumo_periodo", {"data_inicio": "2026-10-31", "data_fim": "2026-10-01"}
    ))
    primeiro, segundo = ler_log(caminho_log)
    assert "no such column: valor" in primeiro["erro"]
    assert "resultado" not in primeiro
    assert segundo["ferramenta"] == "resumo_periodo"
    assert "Inverta" in segundo["erro"]


def test_log_desligado(cliente_em_memoria, caminho_log, monkeypatch):
    monkeypatch.setattr(servidor, "CAMINHO_LOG", "")
    cliente_em_memoria(lambda c: c.call_tool("listar_tabelas", {}))
    assert not caminho_log.exists()


def test_falha_no_log_nao_derruba_a_ferramenta(cliente_em_memoria, monkeypatch, tmp_path):
    bloqueio = tmp_path / "arquivo"
    bloqueio.write_text("")
    # O "diretório" do log é um arquivo: gravar falha com OSError.
    monkeypatch.setattr(servidor, "CAMINHO_LOG", str(bloqueio / "chamadas.jsonl"))
    resultado = cliente_em_memoria(lambda c: c.call_tool("listar_tabelas", {}))
    assert resultado.is_error is False
