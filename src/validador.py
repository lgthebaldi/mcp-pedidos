"""Validação de consultas SQL: só deixa passar um único comando de leitura.

Esta é a primeira de três camadas de proteção (as outras duas ficam em
`banco.py`: conexão somente leitura e authorizer do SQLite). Ela trabalha
sobre o texto da consulta e existe principalmente para devolver mensagens
de erro claras, que o Claude consiga ler para corrigir a consulta e tentar
de novo. A garantia final de que nada é escrito vem das camadas do banco.
"""

import re


class ConsultaInvalida(ValueError):
    """A consulta foi recusada antes de chegar ao banco."""


# Comandos que nunca devem aparecer numa consulta de leitura. A busca é
# feita só sobre o código (fora de textos entre aspas e de comentários),
# então `WHERE status = 'DELETE'` não é recusado por engano.
# REPLACE fica de fora porque também é uma função de texto legítima
# (`replace(x, 'a', 'b')`); `REPLACE INTO` já é barrado por não começar
# com SELECT/WITH, e `INSERT OR REPLACE` é barrado pelo INSERT.
PALAVRAS_PROIBIDAS = (
    "INSERT", "UPDATE", "DELETE", "UPSERT", "DROP", "CREATE", "ALTER",
    "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "ANALYZE",
    "TRUNCATE", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE",
)
_REGEX_PROIBIDAS = re.compile(r"\b(" + "|".join(PALAVRAS_PROIBIDAS) + r")\b", re.IGNORECASE)
_REGEX_INICIO = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

TAMANHO_MAXIMO = 20_000  # caracteres


def _separar_codigo(sql):
    """Percorre o SQL respeitando aspas e comentários.

    Devolve duas versões do texto, com o mesmo comprimento do original:
    - `sem_comentarios`: comentários trocados por espaços (textos mantidos);
    - `so_codigo`: além disso, o conteúdo de textos e identificadores entre
      aspas trocado por espaços, para buscar palavras-chave com segurança.
    """
    sem_comentarios = []
    so_codigo = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            fim = sql.find("\n", i)
            fim = n if fim == -1 else fim
            espacos = " " * (fim - i)
            sem_comentarios.append(espacos)
            so_codigo.append(espacos)
            i = fim
        elif c == "/" and sql.startswith("/*", i):
            fim = sql.find("*/", i + 2)
            if fim == -1:
                raise ConsultaInvalida("Comentário '/*' aberto e não fechado com '*/'.")
            espacos = " " * (fim + 2 - i)
            sem_comentarios.append(espacos)
            so_codigo.append(espacos)
            i = fim + 2
        elif c in "'\"`[":
            fechamento = "]" if c == "[" else c
            j = i + 1
            while True:
                j = sql.find(fechamento, j)
                if j == -1:
                    raise ConsultaInvalida(f"Texto ou identificador iniciado com {c} e não fechado.")
                # Aspas duplicadas ('' ou "") são escape dentro do texto.
                if fechamento != "]" and sql.startswith(fechamento * 2, j):
                    j += 2
                    continue
                break
            trecho = sql[i:j + 1]
            sem_comentarios.append(trecho)
            so_codigo.append(c + " " * (len(trecho) - 2) + fechamento)
            i = j + 1
        else:
            sem_comentarios.append(c)
            so_codigo.append(c)
            i += 1
    return "".join(sem_comentarios), "".join(so_codigo)


def validar_consulta(sql):
    """Confere se `sql` é um único comando de leitura (SELECT ou WITH ... SELECT).

    Devolve a consulta limpa (sem comentários e sem `;` final), pronta para
    executar. Levanta `ConsultaInvalida` com uma explicação caso contrário.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ConsultaInvalida("A consulta está vazia. Envie um comando SELECT.")
    if len(sql) > TAMANHO_MAXIMO:
        raise ConsultaInvalida(
            f"A consulta tem {len(sql)} caracteres; o máximo é {TAMANHO_MAXIMO}."
        )

    sem_comentarios, so_codigo = _separar_codigo(sql)

    # Um único comando: o `;` só é aceito no final.
    partes = [p for p in so_codigo.split(";") if p.strip()]
    if len(partes) > 1:
        raise ConsultaInvalida(
            "Envie apenas um comando por vez; foram encontrados vários "
            "separados por ';'."
        )
    if not partes:
        raise ConsultaInvalida("A consulta está vazia. Envie um comando SELECT.")

    if not _REGEX_INICIO.match(so_codigo):
        primeira = so_codigo.split()[0].upper()
        raise ConsultaInvalida(
            f"Só são permitidas consultas de leitura, começando com SELECT ou WITH. "
            f"A consulta começa com '{primeira}'."
        )

    proibida = _REGEX_PROIBIDAS.search(so_codigo)
    if proibida:
        raise ConsultaInvalida(
            f"O comando '{proibida.group(1).upper()}' não é permitido: o acesso ao "
            "banco é somente leitura. Use apenas SELECT."
        )

    # Remove o `;` final (se houver) e espaços, mantendo os textos intactos.
    fim = so_codigo.rstrip("; \t\r\n")
    return sem_comentarios[:len(fim)].strip()
