"""Testes do servidor MCP, chamando as ferramentas como um cliente MCP faria.

A maioria usa o `Client` do SDK em memória (o objeto do servidor é passado
direto, sem processo nem transporte). Um teste sobe o servidor de verdade
como subprocesso via stdio, do mesmo jeito que o Claude Code faz.
"""

import asyncio
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
def cliente_em_memoria(caminho_banco, monkeypatch):
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
    assert set(ferramentas) == {"listar_tabelas", "descrever_tabela"}
    for ferramenta in ferramentas.values():
        assert len(ferramenta.description) > 80, "a descrição é o que o Claude lê"
        assert ferramenta.annotations.read_only_hint is True
        assert ferramenta.output_schema is not None

    esquema_nome = ferramentas["descrever_tabela"].input_schema["properties"]["nome"]
    assert esquema_nome["enum"] == ["restaurantes", "clientes", "pedidos", "itens_pedido"]


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
        lambda c: c.call_tool("descrever_tabela", {"nome": "pedidos"})
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
        lambda c: c.call_tool("descrever_tabela", {"nome": "sqlite_master"})
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


def test_servidor_via_stdio(caminho_banco):
    """Sobe `servidor.py` como subprocesso e conversa por stdio, como o Claude Code."""
    parametros = StdioServerParameters(
        command=sys.executable,
        args=[str(RAIZ / "src" / "servidor.py")],
        env={**os.environ, "MCP_PEDIDOS_DB": str(caminho_banco)},
    )

    async def rodar():
        async with Client(parametros) as cliente:
            ferramentas = await cliente.list_tools()
            resultado = await cliente.call_tool("listar_tabelas", {})
            return ferramentas, resultado

    ferramentas, resultado = asyncio.run(rodar())
    assert {f.name for f in ferramentas.tools} == {"listar_tabelas", "descrever_tabela"}
    assert resultado.is_error is False
    assert len(resultado.structured_content["tabelas"]) == 4
