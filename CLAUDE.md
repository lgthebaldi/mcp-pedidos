# Servidor MCP de Pedidos

> Salve este arquivo como `CLAUDE.md` na raiz do repositório `mcp-pedidos`.

## Objetivo

Servidor MCP (Model Context Protocol) em Python que expõe um banco SQLite de pedidos de delivery (dados fictícios). Conectado ao Claude Desktop ou ao Claude Code, ele permite perguntar em português coisas como "qual o ticket médio por bairro em outubro?" e receber a resposta calculada a partir dos dados.

Projeto de portfólio para a vaga GEN IA do iFood (trilha AI Builder). O foco é mostrar domínio do ecossistema Claude e integração de IA com dados.

## Competências que o projeto precisa deixar visíveis

- MCP: criação de ferramentas (tools) com descrições claras
- SQL e modelagem de dados
- Segurança: acesso somente leitura e validação das consultas
- Integração com Claude Desktop e Claude Code

## Stack

- Python 3.11+
- SDK oficial de MCP para Python. **Antes de escrever o servidor, consultar a documentação atual do MCP e do SDK**, porque a API muda com frequência; não escrever de memória.
- `sqlite3` da biblioteca padrão
- `pytest` para testes
- Sem API paga: o servidor roda local e é usado pela minha assinatura do Claude

## Estrutura de pastas

```
mcp-pedidos/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .gitignore
├── data/
│   └── pedidos.db              # gerado pelo script, fora do git
├── src/
│   ├── gerar_dados.py          # cria e popula o SQLite
│   ├── banco.py                # conexão somente leitura e consultas
│   ├── validador.py            # garante que só SELECT é executado
│   └── servidor.py             # servidor MCP e ferramentas
├── exemplos/
│   └── perguntas.md            # perguntas de exemplo com a resposta obtida
└── tests/
```

## Dados fictícios

Banco com quatro tabelas:

- `restaurantes`: id, nome, categoria, bairro
- `clientes`: id, bairro, data_cadastro (sem nome nem dado pessoal)
- `pedidos`: id, cliente_id, restaurante_id, data_hora, valor_total, taxa_entrega, status, tempo_entrega_min, nota
- `itens_pedido`: id, pedido_id, nome_item, quantidade, preco_unitario

Orientações:

- Cerca de 30 restaurantes, 500 clientes e 5.000 pedidos em 3 meses.
- Padrões realistas: pico no almoço e no jantar, mais pedidos no fim de semana, alguns bairros com entrega mais lenta, alguns cancelamentos.
- Semente fixa no gerador, para os dados serem reproduzíveis.
- Bairros de uma cidade fictícia; nenhum dado real.

## Ferramentas do servidor

1. `listar_tabelas`: nomes das tabelas e descrição de cada uma
2. `descrever_tabela`: colunas, tipos e exemplos de valores de uma tabela
3. `consultar`: executa uma consulta SQL de leitura e devolve as linhas (com limite de linhas)
4. `resumo_periodo`: métricas prontas de um período (pedidos, faturamento, ticket médio, tempo médio de entrega, taxa de cancelamento)

Cada ferramenta precisa de uma descrição bem escrita, porque é ela que o Claude lê para decidir quando usar. Tratar as descrições como parte do trabalho de prompt.

## Segurança

- Abrir o SQLite em modo somente leitura.
- `validador.py` aceita apenas um comando `SELECT` por chamada e rejeita o resto (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `PRAGMA`, múltiplos comandos).
- Limite de linhas e de tempo por consulta.
- Mensagens de erro claras, para o Claude conseguir corrigir a consulta e tentar de novo.
- Testes cobrindo as tentativas de escrita.

## Conexão com o Claude

- Documentar no README como registrar o servidor no Claude Code e no Claude Desktop. **Confirmar o procedimento e o caminho do arquivo de configuração na documentação atual** (uso Linux), em vez de assumir.
- Testar primeiro no Claude Code, depois no Claude Desktop.

## Demonstração

`exemplos/perguntas.md` com 8 a 10 perguntas reais feitas ao Claude com o servidor conectado, da simples à difícil, por exemplo:

- Quantos pedidos tivemos em outubro?
- Qual o ticket médio por bairro?
- Quais restaurantes têm o maior tempo de entrega e a pior nota?
- A taxa de cancelamento piora em algum horário?

Para cada uma, registrar as ferramentas chamadas, a consulta gerada e a resposta. Incluir um caso em que o Claude errou a primeira consulta e corrigiu.

## Ordem de construção

1. Estrutura do repositório, `.gitignore`, `pyproject.toml`
2. `gerar_dados.py` e conferência dos dados com algumas consultas manuais
3. `banco.py` e `validador.py`, com testes
4. `servidor.py` com `listar_tabelas` e `descrever_tabela`
5. Conexão ao Claude Code e primeiro teste
6. `consultar` e `resumo_periodo`
7. Conexão ao Claude Desktop e gravação dos exemplos
8. README

## Roteiro do README

1. O problema, em duas frases: quem é de negócio depende de alguém que saiba SQL para responder perguntas simples
2. Demonstração (GIF ou capturas do Claude respondendo com o servidor conectado)
3. O que é MCP, em um parágrafo, e o diagrama Claude ↔ servidor ↔ SQLite
4. Ferramentas disponíveis
5. Segurança (somente leitura, validação, limites)
6. Exemplos de perguntas e respostas
7. Limitações e próximos passos
8. Como instalar e conectar
9. Como foi construído: o que eu decidi e o que deleguei ao Claude Code

## Regras para o Claude Code

- Código, comentários e README em português; nomes de variáveis e funções em português sem acento.
- Commits pequenos, um por etapa, com mensagem descritiva.
- Antes de cada etapa, explicar o plano em poucas linhas e esperar minha confirmação.
- Consultar a documentação atual do MCP antes de usar qualquer função do SDK.
- Não commitar o arquivo `.db`; ele é recriado com `gerar_dados.py`.
- Os exemplos do README e de `exemplos/perguntas.md` vêm de execuções reais, não inventadas.
- Explicar cada conceito novo de MCP quando ele aparecer, porque preciso saber defender o projeto em entrevista.
