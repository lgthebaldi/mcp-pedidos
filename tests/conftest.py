import pytest

from gerar_dados import gerar_banco


@pytest.fixture(scope="session")
def caminho_banco(tmp_path_factory):
    """Banco gerado uma vez por sessão de testes, numa pasta temporária."""
    return gerar_banco(tmp_path_factory.mktemp("dados") / "pedidos.db")
