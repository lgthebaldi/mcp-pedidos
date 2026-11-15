# Perguntas de exemplo

Perguntas reais feitas ao Claude com o servidor `pedidos` conectado. As
ferramentas chamadas e o SQL vêm do log do servidor (`logs/chamadas.jsonl`;
uma cópia desta sessão está em [`sessao_desktop.jsonl`](sessao_desktop.jsonl)).
As respostas são o texto que o Claude devolveu, sem edição.

## Como foi feito

- **Cliente:** Claude Desktop no Linux, em 14/11/2026.
- **Mesma conversa:** as 10 perguntas foram feitas numa única conversa, em
  sequência. Por isso a descoberta do banco aparece só no começo: o Claude
  chamou `listar_tabelas` e `descrever_tabela` para as quatro tabelas uma vez
  e reaproveitou esse conhecimento nas perguntas seguintes.
- **Volume:** 17 chamadas de ferramenta no total, nenhuma com erro, cada uma
  levando de 2 a 35 ms.
- **Conferência:** cada número das respostas foi comparado com o resultado
  devolvido pelas ferramentas (registrado no log). A única imprecisão
  encontrada está anotada na pergunta 4.

Descoberta do banco, antes da primeira resposta:

| # | Ferramenta | Argumentos |
|---|---|---|
| 1 | `listar_tabelas` | — |
| 2–5 | `descrever_tabela` | `pedidos`, `restaurantes`, `clientes`, `itens_pedido` |

---

## 1. Quantos pedidos tivemos em outubro?

**Ferramenta:** `resumo_periodo(data_inicio="2026-10-01", data_fim="2026-10-31")`

Pergunta de métrica padrão: o Claude usou a ferramenta pronta, sem SQL.

> 1.763 pedidos: 1.677 entregues e 86 cancelados (4,9%).

## 2. Como outubro se compara com setembro?

**Ferramentas:** `resumo_periodo` para outubro (a mesma chamada da pergunta 1) e
`resumo_periodo(data_inicio="2026-09-01", data_fim="2026-09-30")`.

Fez uma chamada por período, como sugere a descrição da ferramenta ("para
comparar períodos, chame uma vez para cada período"), e calculou sozinho a
variação por dia, notando que outubro tem um dia a mais.

> Outubro foi maior em volume e praticamente igual em qualidade. Por dia, o
> crescimento foi de 52,3 para 56,9 pedidos (+8,7%), já que outubro tem um dia a mais.
>
> | Métrica | Setembro | Outubro | Variação |
> |---|---|---|---|
> | Pedidos | 1.569 | 1.763 | +12,4% |
> | Faturamento | R$ 115.673,32 | R$ 129.437,36 | +11,9% |
> | Ticket médio | R$ 77,89 | R$ 77,18 | −0,9% |
> | Tempo médio de entrega | 40,3 min | 40,6 min | +0,3 min |
> | Nota média | 4,26 | 4,28 | +0,02 |
> | Taxa de cancelamento | 5,4% | 4,9% | −0,5 p.p. |

## 3. Qual o ticket médio por bairro?

**Ferramenta:** `consultar`, duas vezes. "Bairro" é ambíguo (do cliente ou do
restaurante?), e o Claude calculou os dois:

```sql
SELECT c.bairro, COUNT(*) AS entregues, ROUND(AVG(p.valor_total),2) AS ticket_medio,
       ROUND(AVG(p.tempo_entrega_min),1) AS tempo_medio, ROUND(AVG(p.nota),2) AS nota_media,
       COUNT(p.nota) AS avaliados
FROM pedidos p JOIN clientes c ON c.id=p.cliente_id
WHERE p.status='entregue'
GROUP BY c.bairro ORDER BY ticket_medio DESC
```

```sql
SELECT r.bairro, COUNT(*) AS entregues, ROUND(AVG(p.valor_total),2) AS ticket_medio,
       ROUND(AVG(p.tempo_entrega_min),1) AS tempo_medio, ROUND(AVG(p.nota),2) AS nota_media
FROM pedidos p JOIN restaurantes r ON r.id=p.restaurante_id
WHERE p.status='entregue'
GROUP BY r.bairro ORDER BY tempo_medio DESC
```

O filtro `status='entregue'` não foi pedido na pergunta. É o critério que as
descrições da coluna `status` e da ferramenta `consultar` recomendam para
ticket médio.

> Considerando o bairro do cliente e só pedidos entregues, a diferença entre o
> maior e o menor é de cerca de R$ 8.
>
> | Bairro | Ticket médio |
> |---|---|
> | Bela Vista | R$ 80,77 |
> | Jardim das Flores | R$ 80,59 |
> | Vila Nova | R$ 79,06 |
> | Recanto Verde | R$ 78,81 |
> | Morada do Sol | R$ 78,64 |
> | Porto Velho | R$ 76,42 |
> | Alto da Serra | R$ 76,27 |
> | São Bento | R$ 75,16 |
> | Centro | R$ 73,06 |
> | Parque das Águas | R$ 72,43 |
>
> Pelo bairro do restaurante o resultado muda bastante: vai de R$ 95,61
> (Recanto Verde) a R$ 48,45 (Parque das Águas).

## 4. Quais restaurantes têm o maior tempo de entrega e a pior nota?

**Ferramenta:** `consultar`

```sql
SELECT r.nome, r.categoria, r.bairro, COUNT(*) AS entregues,
       ROUND(AVG(p.tempo_entrega_min),1) AS tempo_medio, ROUND(AVG(p.nota),2) AS nota_media,
       COUNT(p.nota) AS avaliados
FROM pedidos p JOIN restaurantes r ON r.id=p.restaurante_id
WHERE p.status='entregue'
GROUP BY r.id ORDER BY tempo_medio DESC
```

A consulta trouxe os 30 restaurantes, e o Claude cruzou os dois rankings.

> Quatro restaurantes aparecem entre os cinco piores nos dois critérios:
>
> | Restaurante | Categoria | Bairro | Tempo médio | Nota média |
> |---|---|---|---|---|
> | Pizzaria Recanto | Pizzaria | Recanto Verde | 48,3 min | 4,02 |
> | Bistrô do Recanto | Brasileira | Recanto Verde | 47,6 min | 3,99 |
> | Açaí da Serra | Doceria | Alto da Serra | 46,4 min | 4,08 |
> | Marmita Express | Marmitaria | Centro | 46,3 min | 4,02 |
>
> O quinto mais lento é o Hanami Delivery (45,3 min, nota 4,12) e a quinta pior
> nota é do Leve Sabor (4,03, 44,7 min). Para comparação, os melhores ficam em
> torno de 32 a 34 min com nota acima de 4,5.

**Conferência:** o cruzamento está certo. A última frase tem uma pequena
imprecisão: entre os três mais rápidos, o Smash Aurora (32,9 min) tem nota 4,49,
não acima de 4,5.

## 5. A taxa de cancelamento piora em algum horário?

**Ferramenta:** `consultar`

```sql
SELECT strftime('%H', data_hora) AS hora, COUNT(*) AS pedidos,
       SUM(status='cancelado') AS cancelados,
       ROUND(100.0*SUM(status='cancelado')/COUNT(*),1) AS taxa_pct
FROM pedidos GROUP BY hora ORDER BY hora
```

> Sim, no pico do jantar. Das 19h às 21h a taxa fica entre 7,0% e 7,6%, contra
> 5,5% no geral. Às 13h também sobe (7,1%), enquanto 11h e 12h ficam na média
> (5,4%). Logo antes e depois do jantar ela é bem menor: 2,8% às 18h e 1,9% às
> 22h. De madrugada e de manhã cedo o volume é pequeno demais para concluir algo.

A ressalva da última frase partiu do próprio Claude: as horas da madrugada têm
de 2 a 43 pedidos nos três meses.

## 6. Fim de semana vende mais que dia útil? E o ticket muda?

**Ferramenta:** `consultar`, duas vezes: uma separando fim de semana e dia útil, outra
por dia da semana, para detalhar.

```sql
WITH dias AS (
  SELECT date(data_hora) AS dia,
         CASE WHEN strftime('%w', data_hora) IN ('0','6') THEN 'fim de semana'
              ELSE 'dia útil' END AS tipo,
         COUNT(*) AS pedidos,
         SUM(CASE WHEN status='entregue' THEN valor_total ELSE 0 END) AS fat,
         SUM(status='entregue') AS entregues
  FROM pedidos GROUP BY dia
)
SELECT tipo, COUNT(*) AS dias, SUM(pedidos) AS pedidos,
       ROUND(1.0*SUM(pedidos)/COUNT(*),1) AS pedidos_por_dia,
       ROUND(SUM(fat)/COUNT(*),2) AS faturamento_por_dia,
       ROUND(SUM(fat)/SUM(entregues),2) AS ticket_medio
FROM dias GROUP BY tipo
```

```sql
SELECT strftime('%w', data_hora) AS dow, COUNT(DISTINCT date(data_hora)) AS dias,
       COUNT(*) AS pedidos,
       ROUND(1.0*COUNT(*)/COUNT(DISTINCT date(data_hora)),1) AS por_dia,
       ROUND(AVG(CASE WHEN status='entregue' THEN valor_total END),2) AS ticket
FROM pedidos GROUP BY dow ORDER BY dow
```

Comparou por **média diária**, não pelo total, porque há 65 dias úteis e só 27
dias de fim de semana no período.

> Vende mais: 70,1 pedidos por dia no fim de semana contra 47,8 em dia útil
> (+47%). O ticket não muda: R$ 77,45 contra R$ 77,18. A sexta já fica acima dos
> outros dias úteis, com 58 pedidos por dia.

## 7. Quais são os 5 itens mais vendidos e de que categoria são?

**Ferramenta:** `consultar`, duas vezes: com o filtro de entregues e, para conferir se
o ranking mudava, sem ele.

```sql
SELECT i.nome_item, SUM(i.quantidade) AS unidades, COUNT(DISTINCT i.pedido_id) AS pedidos,
       GROUP_CONCAT(DISTINCT r.categoria) AS categorias
FROM itens_pedido i
JOIN pedidos p ON p.id=i.pedido_id
JOIN restaurantes r ON r.id=p.restaurante_id
WHERE p.status='entregue'
GROUP BY i.nome_item ORDER BY unidades DESC LIMIT 10
```

> Em unidades, nos pedidos entregues:
>
> | # | Item | Unidades | Categoria do restaurante |
> |---|---|---|---|
> | 1 | Suco Natural | 685 | Brasileira e Marmitaria |
> | 2 | Refrigerante Lata | 511 | Árabe e Hambúrguer |
> | 3 | Parmegiana | 452 | Brasileira |
> | 4 | Feijoada Individual | 447 | Brasileira |
> | 5 | Pudim | 443 | Brasileira |
>
> O item não tem categoria própria no banco; a categoria é a do restaurante que
> o vendeu.

## 8. Qual foi a semana com mais pedidos?

**Ferramenta:** `consultar`

O SQLite não tem `DATE_TRUNC`, como avisa a descrição de `consultar`. O Claude
calculou a segunda-feira de cada semana com aritmética de datas:

```sql
SELECT date(data_hora, '-' || ((CAST(strftime('%w', data_hora) AS INTEGER)+6)%7) || ' days') AS segunda,
       COUNT(*) AS pedidos, COUNT(DISTINCT date(data_hora)) AS dias,
       SUM(status='entregue') AS entregues
FROM pedidos GROUP BY segunda ORDER BY pedidos DESC
```

A coluna `dias` permite ver se a semana está completa: as semanas das pontas
do período têm menos de 7 dias.

> Há um empate com 416 pedidos: a semana de 10 a 16/08 e a de 12 a 18/10
> (semanas de segunda a domingo). Em pedidos entregues, a de outubro ganha: 395
> contra 383.

## 9. Os bairros com entrega mais lenta também têm as piores notas?

**Ferramenta:** nenhuma chamada nova. O Claude reaproveitou o resultado da
primeira consulta da pergunta 3, que já trazia tempo e nota por bairro do
cliente. É um efeito de fazer as perguntas na mesma conversa.

> Sim, e de forma bem clara. Os três bairros de cliente mais lentos são
> exatamente os três com pior nota:
>
> | Bairro | Tempo médio | Nota média |
> |---|---|---|
> | Recanto Verde | 52,7 min | 3,80 |
> | Alto da Serra | 50,8 min | 3,78 |
> | Parque das Águas | 49,2 min | 3,83 |
> | Demais sete bairros | 34,4 a 40,4 min | 4,34 a 4,47 |

## 10. Clientes que se cadastraram durante o período pedem mais ou menos que os antigos?

**Ferramenta:** `consultar`

A pergunta mais difícil do roteiro. O Claude separou os grupos pela data de
cadastro, conferiu a integridade dos dados (`pedidos_antes_cadastro`) e
calculou os dias de cada cliente na plataforma. Assim pôde comparar a
frequência dos novos, que tiveram menos tempo para pedir, de forma justa:

```sql
WITH cl AS (
  SELECT c.id,
         CASE WHEN c.data_cadastro >= '2026-08-01' THEN 'novo' ELSE 'antigo' END AS grupo,
         c.data_cadastro
  FROM clientes c
),
agg AS (
  SELECT cl.id, cl.grupo, cl.data_cadastro, COUNT(p.id) AS pedidos,
         SUM(CASE WHEN p.status='entregue' THEN p.valor_total ELSE 0 END) AS fat,
         SUM(p.status='entregue') AS entregues,
         SUM(CASE WHEN p.data_hora < cl.data_cadastro THEN 1 ELSE 0 END) AS antes_cadastro
  FROM cl LEFT JOIN pedidos p ON p.cliente_id=cl.id
  GROUP BY cl.id
)
SELECT grupo, COUNT(*) AS clientes, SUM(pedidos>0) AS com_pedido, SUM(pedidos) AS pedidos,
       ROUND(1.0*SUM(pedidos)/COUNT(*),2) AS pedidos_por_cliente,
       ROUND(SUM(fat)/SUM(entregues),2) AS ticket_medio,
       SUM(antes_cadastro) AS pedidos_antes_cadastro,
       ROUND(SUM(CASE WHEN grupo='novo' THEN julianday('2026-10-31')-julianday(data_cadastro)+1
                      ELSE 92 END),0) AS dias_ativos
FROM agg GROUP BY grupo
```

> Pedem menos, mesmo descontando o tempo menor de casa.
>
> | Grupo | Clientes | Pedidos | Pedidos por cliente | Pedidos por cliente a cada 30 dias | Ticket médio |
> |---|---|---|---|---|---|
> | Antigos (cadastro antes de 01/08) | 412 | 4.586 | 11,1 | 3,6 | R$ 77,45 |
> | Novos (cadastro a partir de 01/08) | 88 | 414 | 4,7 | 2,7 | R$ 75,40 |
>
> Na taxa ajustada pelos dias desde o cadastro, os novos pedem cerca de 25%
> menos. Dez dos 88 novos ainda não fizeram nenhum pedido.

**Conferência:** a coluna "a cada 30 dias" foi calculada pelo Claude a partir
de `pedidos` e `dias_ativos` (4.586 / 37.904 × 30 = 3,63 e 414 / 4.552 × 30 = 2,73),
e as contas estão certas.

---

## Caso de erro e correção

Na sessão do Desktop acima nenhuma chamada falhou. O caso real de erro e
correção aconteceu no primeiro teste com o Claude Code, antes de o log existir.
O próprio Claude relatou o episódio ao final da resposta:

> Na primeira chamada de descrever_tabela usei tabela como nome do parâmetro, e
> o correto é nome. A chamada seguinte já foi feita com o nome certo.

O que aconteceu:

1. **O erro:** na época, o parâmetro de `descrever_tabela` se chamava `nome`.
   O Claude o chamou de `tabela`, e o SDK recusou a chamada antes de executar a
   função, por não bater com o esquema de entrada (`inputSchema`).
2. **A correção:** a mensagem de erro de validação voltou ao modelo como
   resultado com `is_error=True`, e ele refez a chamada com o nome certo.
3. **A melhoria no servidor:** o nome que o modelo usa por conta própria
   costuma ser o mais claro, então o parâmetro foi renomeado para `tabela`.
   Desde então, nenhuma chamada usou o nome errado.

O mesmo mecanismo vale para erros de SQL: a mensagem do SQLite (por exemplo,
`no such column: valor`) volta ao Claude com a orientação de corrigir a consulta
e tentar de novo. Os testes em `tests/test_servidor.py` cobrem esses casos.
