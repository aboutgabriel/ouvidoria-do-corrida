# Ouvidoria do Corrida

O que a torcida do **Corrida das Blogueiras 8** diz quando ninguém está perguntando.

Projeto de dados e IA que acompanha, episódio a episódio, como a torcida reage às participantes, a partir dos comentários públicos no YouTube. Em vez de enquetes, a Ouvidoria escuta a conversa espontânea: o que milhares de pessoas escrevem sem que ninguém pergunte.

A pergunta central: **a torcida consegue prever quem sai?**

> Projeto em andamento, atualizado a cada episódio da temporada (outubro de 2026 a janeiro de 2027).

## Etapas

1. **Coleta** (`coletar.py`): baixa os comentários de cada episódio pela API oficial do YouTube e salva em SQLite.
2. **Verificação de apelidos** (`verificar_apelidos.py`): mede quais formas de chamar cada participante a torcida realmente usa.
3. **Classificação com IA** (`classificar.py`): o Gemini identifica quais participantes cada comentário cita e o sentimento **para cada uma delas** (análise de sentimento por aspecto), já que um mesmo comentário pode elogiar uma e criticar outra. A saída é validada antes de ir para o banco.
4. **Avaliação** (`gerar_amostra.py` e `avaliar.py`): uma amostra sorteada de menções é revisada à mão, às cegas (a planilha não mostra a resposta do modelo), e comparada com a classificação do Gemini. Os critérios da revisão estão no [guia de anotação](GUIA_DE_ANOTACAO.md).
5. **Painel** (`gerar_dados.py` e `docs/`): calcula, com pandas, menções e saldo da torcida por participante e episódio, e alimenta um painel publicado no GitHub Pages.

## Dados

- `dados/participantes.json`: as 12 participantes e as formas como são citadas.
- `dados/resultados.csv`: resultados oficiais por episódio (Venceu, Salvo, Flop, Eliminado, Desistiu).
- O banco `dados/corrida.db` é gerado localmente e não vai para o repositório.

**Privacidade:** o projeto não guarda nomes de usuários e só publica números agregados.

## Como rodar

```bash
python -m venv .venv
.\.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e coloque suas chaves da YouTube Data API v3 e do Gemini. Depois:

```bash
python coletar.py --episodio 1 --video LINK_DO_EPISODIO_1
python coletar.py --episodio 2 --video LINK_DO_EPISODIO_2
python verificar_apelidos.py
python classificar.py --limite 40   # teste
python classificar.py               # todos
python gerar_amostra.py             # planilha para revisão humana
python avaliar.py                   # depois de revisar a planilha
python gerar_dados.py               # atualiza o painel em docs/
```

## Limitações conhecidas

- A API do YouTube devolve no máximo 5 respostas por comentário, então conversas longas ficam incompletas.
- Só vão para o modelo os comentários que citam alguma participante pelo nome ou apelido. Comentários como "ela foi injustiçada", sem nome, ficam de fora.
- A torcida erra muito a grafia dos nomes. A lista de apelidos foi construída a partir dos próprios dados (ex.: "Talita" aparece mais que o oficial "Talitah").

## Tecnologias

Python, SQLite, YouTube Data API v3, API do Gemini (saída em JSON estruturado), pandas e HTML/CSS/JavaScript para o painel.

## Autor

**Gabriel Ramiro Martins**
[LinkedIn](https://linkedin.com/in/gabriel-ramiro-martins) · [GitHub](https://github.com/aboutgabriel)
