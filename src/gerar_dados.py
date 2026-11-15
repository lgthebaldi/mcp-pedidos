"""Gera o banco SQLite de pedidos de delivery com dados fictícios.

Uso:
    uv run python src/gerar_dados.py            # cria data/pedidos.db
    uv run python src/gerar_dados.py --saida x.db

O banco é apagado e recriado a cada execução. Como a semente é fixa,
a mesma semente gera sempre exatamente os mesmos dados.

Todos os nomes (cidade, bairros, restaurantes, pratos) são inventados.
Os clientes não têm nome nem qualquer dado pessoal, apenas bairro e
data de cadastro.
"""

import argparse
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "data" / "pedidos.db"
SEMENTE_PADRAO = 42

INICIO_PERIODO = date(2026, 8, 1)
FIM_PERIODO = date(2026, 10, 31)
TOTAL_CLIENTES = 500
TOTAL_PEDIDOS = 5000

# Bairros da cidade fictícia de Vila Aurora. O valor é o acréscimo, em
# minutos, no tempo de entrega: três bairros são mais distantes ou com
# trânsito pior, e por isso têm entrega mais lenta.
BAIRROS = {
    "Centro": 0,
    "Jardim das Flores": 0,
    "Vila Nova": 2,
    "Alto da Serra": 14,
    "Porto Velho": 3,
    "Bela Vista": 1,
    "Parque das Águas": 12,
    "São Bento": 2,
    "Morada do Sol": 4,
    "Recanto Verde": 16,
}

# Cardápio base por categoria: (nome do item, preço de referência).
CARDAPIOS = {
    "Pizzaria": [
        ("Pizza Margherita", 52.0), ("Pizza Calabresa", 54.0),
        ("Pizza Quatro Queijos", 62.0), ("Pizza Portuguesa", 58.0),
        ("Refrigerante 2L", 14.0), ("Borda Recheada", 10.0),
    ],
    "Japonesa": [
        ("Combinado 20 peças", 79.0), ("Temaki Salmão", 32.0),
        ("Hot Roll 10 peças", 34.0), ("Yakissoba", 42.0),
        ("Missoshiru", 12.0), ("Chá Gelado", 9.0),
    ],
    "Hambúrguer": [
        ("Burger Clássico", 32.0), ("Burger Duplo Bacon", 42.0),
        ("Burger Vegetariano", 34.0), ("Batata Frita", 18.0),
        ("Milkshake", 22.0), ("Refrigerante Lata", 7.0),
    ],
    "Brasileira": [
        ("Prato Feito", 28.0), ("Feijoada Individual", 39.0),
        ("Frango Grelhado com Salada", 32.0), ("Parmegiana", 44.0),
        ("Suco Natural", 10.0), ("Pudim", 12.0),
    ],
    "Saudável": [
        ("Bowl de Quinoa", 38.0), ("Salada Completa", 34.0),
        ("Wrap de Frango", 29.0), ("Poke de Salmão", 46.0),
        ("Suco Verde", 13.0), ("Iogurte com Granola", 15.0),
    ],
    "Árabe": [
        ("Esfiha de Carne", 7.0), ("Esfiha de Queijo", 7.0),
        ("Kibe Frito", 8.0), ("Shawarma", 31.0),
        ("Homus com Pão Sírio", 24.0), ("Refrigerante Lata", 7.0),
    ],
    "Doceria": [
        ("Bolo de Pote", 16.0), ("Brigadeiro Gourmet (6 un)", 24.0),
        ("Torta de Limão (fatia)", 15.0), ("Brownie", 12.0),
        ("Açaí 500 ml", 26.0), ("Café Gelado", 14.0),
    ],
    "Marmitaria": [
        ("Marmita Pequena", 19.0), ("Marmita Grande", 25.0),
        ("Marmita Fit", 27.0), ("Sobremesa do Dia", 8.0),
        ("Suco Natural", 9.0), ("Água", 4.0),
    ],
}

# 30 restaurantes: (nome, categoria, bairro). Os restaurantes ficam
# concentrados nos bairros centrais, como numa cidade real.
RESTAURANTES = [
    ("Forno da Praça", "Pizzaria", "Centro"),
    ("Pizzaria Bella Aurora", "Pizzaria", "Bela Vista"),
    ("Massa Fina", "Pizzaria", "Vila Nova"),
    ("Pizza do Porto", "Pizzaria", "Porto Velho"),
    ("Sakura Sushi", "Japonesa", "Centro"),
    ("Kaizen Temakeria", "Japonesa", "Jardim das Flores"),
    ("Hanami Delivery", "Japonesa", "Bela Vista"),
    ("Burger da Esquina", "Hambúrguer", "Centro"),
    ("Smash Aurora", "Hambúrguer", "Vila Nova"),
    ("Brasa Burger", "Hambúrguer", "São Bento"),
    ("Chapa Quente", "Hambúrguer", "Morada do Sol"),
    ("Cozinha da Vó Lia", "Brasileira", "Centro"),
    ("Sabor Caseiro", "Brasileira", "Jardim das Flores"),
    ("Panela de Barro", "Brasileira", "Porto Velho"),
    ("Tempero Mineiro", "Brasileira", "São Bento"),
    ("Verde Vida", "Saudável", "Jardim das Flores"),
    ("Bowl & Cia", "Saudável", "Bela Vista"),
    ("Leve Sabor", "Saudável", "Centro"),
    ("Casa Síria", "Árabe", "Centro"),
    ("Esfiharia Damasco", "Árabe", "Vila Nova"),
    ("Doce Encanto", "Doceria", "Bela Vista"),
    ("Açaí da Serra", "Doceria", "Alto da Serra"),
    ("Confeitaria Aurora", "Doceria", "Centro"),
    ("Marmita Express", "Marmitaria", "Centro"),
    ("Quentinha da Ana", "Marmitaria", "Porto Velho"),
    ("Marmitas do Parque", "Marmitaria", "Parque das Águas"),
    ("Fit Box", "Marmitaria", "Morada do Sol"),
    ("Bistrô do Recanto", "Brasileira", "Recanto Verde"),
    ("Pizzaria Recanto", "Pizzaria", "Recanto Verde"),
    ("Temaki Express", "Japonesa", "São Bento"),
]

# Peso relativo de pedidos por hora do dia (0 a 23). Picos no almoço
# (11h-13h) e no jantar (19h-21h); madrugada quase sem pedidos.
PESO_HORA = [
    1, 0.5, 0.2, 0.1, 0.1, 0.1, 0.3, 0.8, 1.5, 2, 3, 9,
    14, 10, 4, 3, 3, 4, 8, 14, 16, 12, 6, 2.5,
]
HORAS_PICO = {11, 12, 13, 19, 20, 21}

# Peso por dia da semana (segunda = 0 ... domingo = 6).
PESO_DIA_SEMANA = [0.85, 0.85, 0.9, 0.95, 1.15, 1.45, 1.4]

SQL_CRIACAO = """
CREATE TABLE restaurantes (
    id        INTEGER PRIMARY KEY,
    nome      TEXT NOT NULL,
    categoria TEXT NOT NULL,
    bairro    TEXT NOT NULL
);

CREATE TABLE clientes (
    id            INTEGER PRIMARY KEY,
    bairro        TEXT NOT NULL,
    data_cadastro TEXT NOT NULL              -- AAAA-MM-DD
);

CREATE TABLE pedidos (
    id                INTEGER PRIMARY KEY,
    cliente_id        INTEGER NOT NULL REFERENCES clientes(id),
    restaurante_id    INTEGER NOT NULL REFERENCES restaurantes(id),
    data_hora         TEXT NOT NULL,         -- AAAA-MM-DD HH:MM:SS
    valor_total       REAL NOT NULL,         -- soma dos itens + taxa_entrega, em R$
    taxa_entrega      REAL NOT NULL,         -- em R$
    status            TEXT NOT NULL CHECK (status IN ('entregue', 'cancelado')),
    tempo_entrega_min INTEGER,               -- NULL quando cancelado
    nota              INTEGER CHECK (nota BETWEEN 1 AND 5)  -- NULL se não avaliado
);

CREATE TABLE itens_pedido (
    id             INTEGER PRIMARY KEY,
    pedido_id      INTEGER NOT NULL REFERENCES pedidos(id),
    nome_item      TEXT NOT NULL,
    quantidade     INTEGER NOT NULL CHECK (quantidade > 0),
    preco_unitario REAL NOT NULL             -- em R$
);

CREATE INDEX idx_pedidos_data_hora ON pedidos(data_hora);
CREATE INDEX idx_pedidos_cliente ON pedidos(cliente_id);
CREATE INDEX idx_pedidos_restaurante ON pedidos(restaurante_id);
CREATE INDEX idx_itens_pedido ON itens_pedido(pedido_id);
"""


def gerar_restaurantes(rng):
    """Devolve a lista de restaurantes com um perfil interno de cada um.

    O perfil (popularidade, tempo de preparo e cardápio com preços) só é
    usado para gerar os pedidos; não vai para o banco.
    """
    restaurantes = []
    for id_rest, (nome, categoria, bairro) in enumerate(RESTAURANTES, start=1):
        fator_preco = rng.uniform(0.9, 1.15)
        cardapio = [
            (item, round(preco * fator_preco, 2))
            for item, preco in CARDAPIOS[categoria]
        ]
        restaurantes.append({
            "id": id_rest,
            "nome": nome,
            "categoria": categoria,
            "bairro": bairro,
            "popularidade": rng.uniform(0.4, 2.0),
            "preparo_min": rng.uniform(10, 24),
            "cardapio": cardapio,
        })
    return restaurantes


def gerar_clientes(rng):
    """Clientes com bairro e data de cadastro.

    Cerca de 80% já eram cadastrados antes do período; o restante se
    cadastra ao longo dele.
    """
    nomes_bairros = list(BAIRROS)
    pesos_bairros = [1.6, 1.3, 1.2, 0.7, 1.0, 1.2, 0.8, 1.0, 0.9, 0.6]
    dias_periodo = (FIM_PERIODO - INICIO_PERIODO).days
    clientes = []
    for id_cli in range(1, TOTAL_CLIENTES + 1):
        if rng.random() < 0.8:
            cadastro = INICIO_PERIODO - timedelta(days=rng.randint(1, 900))
        else:
            cadastro = INICIO_PERIODO + timedelta(days=rng.randint(0, dias_periodo - 5))
        clientes.append({
            "id": id_cli,
            "bairro": rng.choices(nomes_bairros, pesos_bairros)[0],
            "data_cadastro": cadastro,
            # Alguns clientes pedem muito mais que outros.
            "frequencia": rng.paretovariate(1.5),
        })
    return clientes


def sortear_data_hora(rng, dias, pesos_dias):
    dia = rng.choices(dias, pesos_dias)[0]
    hora = rng.choices(range(24), PESO_HORA)[0]
    return datetime(dia.year, dia.month, dia.day, hora,
                    rng.randint(0, 59), rng.randint(0, 59))


def gerar_pedidos(rng, restaurantes, clientes):
    """Gera pedidos e itens. Devolve (pedidos, itens) como listas de tuplas."""
    dias = [INICIO_PERIODO + timedelta(days=i)
            for i in range((FIM_PERIODO - INICIO_PERIODO).days + 1)]
    # Leve crescimento ao longo do período, além do efeito do dia da semana.
    pesos_dias = [PESO_DIA_SEMANA[d.weekday()] * (1 + 0.15 * i / len(dias))
                  for i, d in enumerate(dias)]
    pesos_clientes = [c["frequencia"] for c in clientes]
    pesos_restaurantes = [r["popularidade"] for r in restaurantes]

    momentos = sorted(sortear_data_hora(rng, dias, pesos_dias)
                      for _ in range(TOTAL_PEDIDOS))

    pedidos = []
    itens = []
    for id_ped, momento in enumerate(momentos, start=1):
        # Só pode pedir quem já estava cadastrado naquele dia.
        while True:
            cliente = rng.choices(clientes, pesos_clientes)[0]
            if cliente["data_cadastro"] <= momento.date():
                break

        # Clientes preferem restaurantes do próprio bairro.
        pesos = [p * (2.5 if r["bairro"] == cliente["bairro"] else 1)
                 for r, p in zip(restaurantes, pesos_restaurantes)]
        rest = rng.choices(restaurantes, pesos)[0]

        # Itens do pedido.
        subtotal = 0.0
        qtd_itens = rng.choices([1, 2, 3, 4], [35, 35, 20, 10])[0]
        for nome_item, preco in rng.sample(rest["cardapio"], qtd_itens):
            quantidade = rng.choices([1, 2, 3], [75, 20, 5])[0]
            itens.append((id_ped, nome_item, quantidade, preco))
            subtotal += quantidade * preco

        mesmo_bairro = rest["bairro"] == cliente["bairro"]
        if subtotal >= 90 and rng.random() < 0.5:
            taxa = 0.0  # frete grátis em pedidos grandes
        elif mesmo_bairro:
            taxa = rng.choice([2.99, 3.99, 4.99])
        else:
            taxa = rng.choice([5.99, 6.99, 7.99, 8.99, 9.99])
        valor_total = round(subtotal + taxa, 2)

        pico = momento.hour in HORAS_PICO
        atraso_bairro = BAIRROS[cliente["bairro"]]

        # Cancelamento: base de 3%, sobe no pico e nos bairros lentos.
        prob_cancelar = 0.03 + (0.035 if pico else 0) + (0.025 if atraso_bairro >= 10 else 0)
        if rng.random() < prob_cancelar:
            pedidos.append((id_ped, cliente["id"], rest["id"],
                            momento.strftime("%Y-%m-%d %H:%M:%S"),
                            valor_total, taxa, "cancelado", None, None))
            continue

        tempo = (rest["preparo_min"]
                 + (8 if mesmo_bairro else 16)
                 + atraso_bairro
                 + (rng.uniform(4, 10) if pico else 0)
                 + rng.gauss(0, 5))
        tempo = max(12, round(tempo))

        # ~70% dos pedidos entregues são avaliados; a nota cai com a demora.
        nota = None
        if rng.random() < 0.7:
            base = 4.8 - max(0, tempo - 35) * 0.06 + rng.gauss(0, 0.7)
            nota = min(5, max(1, round(base)))

        pedidos.append((id_ped, cliente["id"], rest["id"],
                        momento.strftime("%Y-%m-%d %H:%M:%S"),
                        valor_total, taxa, "entregue", tempo, nota))
    return pedidos, itens


def gerar_banco(caminho=CAMINHO_PADRAO, semente=SEMENTE_PADRAO):
    """Apaga (se existir) e recria o banco em `caminho`. Devolve o caminho."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.unlink(missing_ok=True)

    # Um gerador próprio, em vez do `random` global, garante que nada
    # externo interfira na sequência sorteada.
    rng = random.Random(semente)
    restaurantes = gerar_restaurantes(rng)
    clientes = gerar_clientes(rng)
    pedidos, itens = gerar_pedidos(rng, restaurantes, clientes)

    conexao = sqlite3.connect(caminho)
    try:
        conexao.executescript(SQL_CRIACAO)
        conexao.executemany(
            "INSERT INTO restaurantes VALUES (?, ?, ?, ?)",
            [(r["id"], r["nome"], r["categoria"], r["bairro"]) for r in restaurantes],
        )
        conexao.executemany(
            "INSERT INTO clientes VALUES (?, ?, ?)",
            [(c["id"], c["bairro"], c["data_cadastro"].isoformat()) for c in clientes],
        )
        conexao.executemany("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", pedidos)
        conexao.executemany(
            "INSERT INTO itens_pedido (pedido_id, nome_item, quantidade, preco_unitario) "
            "VALUES (?, ?, ?, ?)",
            itens,
        )
        conexao.commit()
    finally:
        conexao.close()
    return caminho


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path, default=CAMINHO_PADRAO,
                        help="caminho do arquivo .db (padrão: data/pedidos.db)")
    parser.add_argument("--semente", type=int, default=SEMENTE_PADRAO,
                        help="semente do gerador aleatório (padrão: 42)")
    args = parser.parse_args()
    caminho = gerar_banco(args.saida, args.semente)
    print(f"Banco gerado em {caminho}")


if __name__ == "__main__":
    main()
