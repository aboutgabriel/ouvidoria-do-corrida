# Ouvidoria do Corrida

O que a torcida do **Corrida das Blogueiras 8** diz quando ninguém está perguntando.

**[Ver o painel ao vivo](https://aboutgabriel.github.io/ouvidoria-do-corrida/)**

[![Ouvidoria do Corrida](docs/og.png)](https://aboutgabriel.github.io/ouvidoria-do-corrida/)

Projeto de dados e IA que acompanha, episódio a episódio, como a torcida reage às participantes, a partir dos comentários públicos no YouTube. Em vez de enquetes, a Ouvidoria escuta a conversa espontânea: o que milhares de pessoas escrevem sem que ninguém pergunte.

A pergunta central: **a torcida consegue prever quem sai?**

> Projeto em andamento, atualizado a cada episódio da temporada (outubro de 2026 a janeiro de 2027).

## O que os dados mostram até agora

Depois de 2 episódios e 15.007 comentários lidos:

- **A torcida acertou a primeira eliminação.** Peter Poc saiu no episódio 1 com o pior saldo da torcida (−78).
- **A maior virada foi de Bárbara Freitas**, que saiu de −35 no episódio 1 para +79 no episódio 2, depois de vencer a prova.
- **Paizinho dos Looks liderou a conversa do episódio 2** (892 menções), e 70% dos comentários foram críticas, principalmente pela desistência no meio da prova do flop.
- **Latyffa Romayale é quase unanimidade:** 207 elogios e só 6 críticas no episódio 2.

O **saldo da torcida** vai de −100 (só críticas) a +100 (só elogios) e é calculado como (elogios − críticas) ÷ menções × 100.

## Etapas

1. **Coleta** (`coletar.py`): baixa os comentários de cada episódio pela API oficial do YouTube e salva em SQLite.
2. **Verificação de apelidos** (`verificar_apelidos.py`): mede quais formas de chamar cada participante a torcida realmente usa.
3. **Classificação com IA** (`classificar.py`): o Gemini identifica quais participantes cada comentário cita e o sentimento **para cada uma delas** (análise de sentimento por aspecto), já que um mesmo comentário pode elogiar uma e criticar outra. A saída é validada antes de ir para o banco.
4. **Avaliação** (`gerar_amostra.py` e `avaliar.py`): uma amostra sorteada de menções é revisada à mão, às cegas (a planilha não mostra a resposta do modelo), e comparada com a classificação do Gemini. Os critérios da revisão estão no [guia de anotação](GUIA_DE_ANOTACAO.md). Os números também são conferidos por um segundo caminho, em SQL puro (`conferir.py`).
5. **Resumos da percepção** (`resumir.py`): o Gemini escreve um resumo curto de como a torcida viu cada participante, a partir dos saldos e dos comentários mais curtidos, e outro de como a torcida recebeu cada episódio, a partir dos números, das cenas mais comentadas e dos 30 comentários mais curtidos do episódio. As regras do prompt proíbem opinião própria, temas citados em um comentário só e qualquer menção a corpo, saúde ou vida pessoal. **Todo resumo passa por revisão humana antes de ir ao ar**, e os corrigidos à mão ficam em `dados/resumos.json`.
6. **Painel** (`gerar_dados.py` e `docs/`): calcula, com pandas, menções e saldo da torcida por participante e episódio, e alimenta um painel em HTML, CSS e JavaScript puros, publicado no GitHub Pages.

## Resultado da avaliação

Em 100 menções revisadas à mão:

| Métrica | Resultado |
|---|---|
| Participante identificada corretamente | 100% |
| Sentimento igual ao da revisão humana | 82% (margem de erro de cerca de 8 pontos) |

As divergências se concentram em ironia e em elogios indiretos, como defender uma participante criticando outra.

## Dados

- `dados/participantes.json`: as 12 participantes e as formas como são citadas.
- `dados/resultados.csv`: resultados oficiais por episódio (Venceu, Salvo, Flop, Eliminado, Desistiu).
- `dados/resumos.json`: resumos da percepção da torcida sobre cada participante, revisados à mão.
- `dados/resumos_episodios.json`: resumos de como a torcida recebeu cada episódio, revisados à mão.
- `dados/cenas.json`: o que acontece em cada cena mais comentada, escrito à mão a partir da transcrição do episódio.
- `docs/fotos/`: fotos oficiais das participantes (DiaTV/divulgação). O painel encontra cada foto pelo nome do arquivo (ex.: `talitah-sampaio.jpg`) e mostra as iniciais quando não há foto.
- O banco `dados/corrida.db` é gerado localmente e não vai para o repositório.

**Privacidade:** o projeto não guarda nomes de usuários. As citações publicadas aparecem sem autor, sem @menções e sem links.

## Como rodar

```bash
python -m venv .venv
.\.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e coloque suas chaves da YouTube Data API v3 e do Gemini. Depois:

```bash
python coletar.py --episodio 1 --video LINK_DO_EPISODIO_1
python verificar_apelidos.py
python classificar.py --limite 40   # teste
python classificar.py               # todos
python gerar_amostra.py             # planilha para revisão humana
python avaliar.py                   # depois de revisar a planilha
python conferir.py                  # confere os números em SQL
python resumir.py                   # resumos de quem tem episódio novo
python gerar_dados.py               # atualiza o painel em docs/
```

## A cada episódio novo

1. Coletar e classificar os comentários do episódio.
2. Atualizar `dados/resultados.csv` com o resultado oficial.
3. Ler a transcrição em volta das cenas mais comentadas e descrever cada uma em `dados/cenas.json`.
4. Rodar `resumir.py` (ele usa as descrições das cenas) e revisar os resumos novos antes de publicar.
5. Rodar `gerar_dados.py` e publicar.

## Limitações conhecidas

- **Só YouTube.** Os números mostram a torcida que comenta no YouTube, não o público inteiro. O que se diz no X, no Instagram e no TikTok fica de fora.
- A API do YouTube devolve no máximo 5 respostas por comentário, então conversas longas ficam incompletas.
- Só vão para o modelo os comentários que citam alguma participante pelo nome ou apelido. Comentários como "ela foi injustiçada", sem nome, ficam de fora.
- A torcida erra muito a grafia dos nomes. A lista de apelidos foi construída a partir dos próprios dados (ex.: "Talita" aparece mais que o oficial "Talitah").
- Participantes com poucas menções têm saldo menos estável, porque cada comentário pesa mais.

## Tecnologias

Python, SQLite, YouTube Data API v3, API do Gemini (saída em JSON estruturado), pandas e HTML/CSS/JavaScript para o painel.

## Autor

**Gabriel Ramiro Martins**
[LinkedIn](https://linkedin.com/in/gabriel-ramiro-martins) · [GitHub](https://github.com/aboutgabriel)

Projeto independente, sem vínculo com a DiaTV ou com a produção do programa.
