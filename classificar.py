"""
Ouvidoria do Corrida | Etapa 2: classificação com IA

Para cada comentário que cita pelo menos uma participante, o Gemini identifica
QUEM é citada e o sentimento do comentário PARA CADA UMA delas
(análise de sentimento por aspecto).

Uso:
    python classificar.py --limite 50     (teste com poucos comentários)
    python classificar.py                 (classifica tudo que falta)
    python classificar.py --refazer       (guarda uma cópia e reclassifica tudo)

Desde 07/11/2026 as instruções incluem o dicionário do fandom
(dados/dicionario.csv), que subiu o acerto no teste (testar_dicionario.py).

Pode ser interrompido e rodado de novo: os comentários já classificados
são pulados.
"""

import argparse
import json
import os
import sqlite3
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from verificar_apelidos import BANCO, PARTICIPANTES, PASTA, citou, normalizar

DICIONARIO = os.path.join(PASTA, "dados", "dicionario.csv")

TAMANHO_LOTE = 40           # comentários por chamada ao Gemini
PAUSA_ENTRE_LOTES = 4       # segundos, para respeitar o limite gratuito
SENTIMENTOS = {"positivo", "negativo", "neutro"}


def carregar_participantes():
    with open(PARTICIPANTES, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def criar_tabelas(conexao):
    # Uma linha por (comentário, participante): o mesmo comentário pode
    # elogiar uma e criticar outra.
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS classificacoes (
            comentario_id TEXT NOT NULL,
            participante  TEXT NOT NULL,
            sentimento    TEXT NOT NULL,
            PRIMARY KEY (comentario_id, participante)
        )
    """)
    # Marca o que já passou pelo modelo, inclusive quando ele não achou ninguém.
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS processados (
            comentario_id TEXT PRIMARY KEY,
            modelo        TEXT NOT NULL,
            processado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


def comentarios_pendentes(conexao, participantes, limite):
    """Pré-filtro barato: só manda ao modelo quem cita algum apelido."""
    todos_apelidos = [a for p in participantes for a in p["apelidos"]]
    linhas = conexao.execute("""
        SELECT c.id, c.texto FROM comentarios c
        LEFT JOIN processados p ON p.comentario_id = c.id
        WHERE p.comentario_id IS NULL
        ORDER BY c.episodio, c.publicado_em
    """).fetchall()
    pendentes = []
    for cid, texto in linhas:
        norm = normalizar(texto)
        if any(citou(a, norm) for a in todos_apelidos):
            pendentes.append((cid, texto))
            if limite and len(pendentes) >= limite:
                break
    return pendentes


def montar_dicionario():
    """Gírias do fandom, revisadas por quem acompanha o programa (dados/dicionario.csv)."""
    import csv
    with open(DICIONARIO, encoding="utf-8", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    itens = "\n".join(f"- {l['termo']}: {l['significado']}. {l['sentimento']}" for l in linhas)
    return f"""

Dicionário do fandom (gírias e expressões que a torcida usa):
{itens}

Regras usadas na revisão humana (siga as mesmas):
- Defender uma participante, inclusive criticando quem votou nela, quem a mandou para o flop ou quem falou mal dela, é positivo para ela.
- Comentário misto (crítica e elogio para a mesma participante): vale a ideia principal. Se os dois pesam igual, é neutro.
- Achar o flop ou a eliminação injusta é positivo para ela; achar justa é negativo.
- Pena ou compaixão é positivo: a pessoa está do lado da participante.
- O nome sozinho, gritado, sem sinal de opinião, é neutro. Com sinal claro de carinho ou empolgação, é positivo.
- Comparar a participante com outra pessoa, sem opinião clara, é neutro. Se a pessoa da comparação é querida pelo fandom, é positivo; se é rejeitada ou polêmica, é negativo.
- Na dúvida entre duas opções, escolha a que alguém do fandom entenderia primeiro; se ainda estiver dividido, é neutro."""


def montar_instrucoes(participantes, dicionario=False):
    lista = "\n".join(f"- {p['nome']} (também chamada de: {', '.join(p['apelidos'])})" for p in participantes)
    return f"""Você analisa comentários do YouTube sobre o reality show brasileiro Corrida das Blogueiras (8ª temporada).

Participantes da temporada:
{lista}

Para cada comentário, identifique quais dessas participantes são citadas e o sentimento do comentário em relação a CADA UMA delas.

Regras:
1. Use exatamente o nome oficial da lista acima no campo "participante".
2. Sentimento: "positivo" (elogio, torcida, defesa), "negativo" (crítica, deboche, desejo de eliminação) ou "neutro" (citação sem opinião clara).
3. Um mesmo comentário pode ter sentimentos diferentes para participantes diferentes.
4. A torcida usa gírias, ironia e muitas vezes trata todos no feminino ("a Poc", "a mona", "diva"). Interprete pelo contexto: "chatérrima" é negativo; "arrasou", "divou" e "injustiçada" são positivos.
5. Ignore pessoas que não estão na lista (jurados, apresentadores, celebridades citadas em comparações).
6. Se nenhuma participante for realmente citada, devolva a lista de menções vazia.
7. Responda apenas com o JSON pedido.""" + (montar_dicionario() if dicionario else "")


ESQUEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "n": types.Schema(type=types.Type.INTEGER, description="Número do comentário no lote"),
            "mencoes": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "participante": types.Schema(type=types.Type.STRING),
                        "sentimento": types.Schema(type=types.Type.STRING, enum=sorted(SENTIMENTOS)),
                    },
                    required=["participante", "sentimento"],
                ),
            ),
        },
        required=["n", "mencoes"],
    ),
)


# Os comentários podem ter xingamentos e ofensas. O modelo só classifica, não gera
# esse conteúdo, então os filtros de segurança ficam no mínimo para não barrar lotes.
SEGURANCA = [
    types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE)
    for c in (types.HarmCategory.HARM_CATEGORY_HARASSMENT, types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
              types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT)
]


class RespostaVazia(Exception):
    """O modelo não devolveu texto (bloqueio de segurança ou resposta cortada)."""


def _chamar_modelo(cliente, modelo, instrucoes, lote):
    # Números curtos (1, 2, 3...) no lugar dos IDs do YouTube: menos texto e
    # menos chance de o modelo errar o identificador.
    entrada = "\n".join(f"[{i}] {texto}" for i, (_, texto) in enumerate(lote, start=1))
    espera = 5
    for tentativa in range(5):
        try:
            resposta = cliente.models.generate_content(
                model=modelo,
                contents=entrada,
                config=types.GenerateContentConfig(
                    system_instruction=instrucoes,
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=ESQUEMA,
                    safety_settings=SEGURANCA,
                ),
            )
            if not resposta.text:
                motivo = resposta.candidates[0].finish_reason if resposta.candidates else resposta.prompt_feedback
                raise RespostaVazia(str(motivo))
            return json.loads(resposta.text)
        except RespostaVazia:
            raise
        except Exception as erro:
            texto_erro = str(erro)
            temporario = any(c in texto_erro for c in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))
            if not temporario or tentativa == 4:
                raise
            print(f"  Limite ou instabilidade da API. Nova tentativa em {espera}s...")
            time.sleep(espera)
            espera *= 2  # backoff exponencial


def classificar_lote(cliente, modelo, instrucoes, lote):
    """Classifica um lote. Se o modelo devolver vazio, divide o lote ao meio até
    isolar o comentário problemático, que fica sem classificação."""
    try:
        return _chamar_modelo(cliente, modelo, instrucoes, lote)
    except RespostaVazia as erro:
        if len(lote) == 1:
            print(f"  Aviso: o modelo não classificou um comentário ({erro}). Ele fica de fora.")
            return []
        meio = len(lote) // 2
        primeira = classificar_lote(cliente, modelo, instrucoes, lote[:meio])
        segunda = classificar_lote(cliente, modelo, instrucoes, lote[meio:])
        for item in segunda:
            if isinstance(item, dict) and isinstance(item.get("n"), int):
                item["n"] += meio  # volta para a numeração do lote inteiro
        return primeira + segunda


def salvar_resultado(conexao, lote, resultado, nomes_validos, modelo):
    """Valida o que o modelo devolveu antes de gravar."""
    por_numero = {item.get("n"): item.get("mencoes", []) for item in resultado if isinstance(item, dict)}
    descartadas = 0
    for i, (cid, _) in enumerate(lote, start=1):
        if i not in por_numero:
            continue  # o modelo pulou este comentário: fica pendente para a próxima rodada
        for mencao in por_numero[i]:
            nome, sentimento = mencao.get("participante"), mencao.get("sentimento")
            if nome in nomes_validos and sentimento in SENTIMENTOS:
                conexao.execute("INSERT OR REPLACE INTO classificacoes VALUES (?, ?, ?)", (cid, nome, sentimento))
            else:
                descartadas += 1
        conexao.execute("INSERT OR REPLACE INTO processados (comentario_id, modelo) VALUES (?, ?)", (cid, modelo))
    conexao.commit()
    return len(por_numero), descartadas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite", type=int, help="Classifica no máximo N comentários (bom para testar)")
    parser.add_argument("--refazer", action="store_true",
                        help="Guarda uma cópia da classificação atual e reclassifica tudo do zero")
    args = parser.parse_args()

    load_dotenv()
    chave = os.getenv("GEMINI_API_KEY")
    if not chave or chave == "cole_sua_chave_aqui":
        sys.exit("Configure a GEMINI_API_KEY no arquivo .env antes de rodar.")
    modelo = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    participantes = carregar_participantes()
    nomes_validos = {p["nome"] for p in participantes}
    instrucoes = montar_instrucoes(participantes, dicionario=True)
    cliente = genai.Client(api_key=chave)

    with sqlite3.connect(BANCO) as conexao:
        criar_tabelas(conexao)
        if args.refazer:
            # Cópia de segurança, feita uma vez só: rodar --refazer de novo não apaga a cópia original.
            existe = conexao.execute("SELECT name FROM sqlite_master WHERE name = 'classificacoes_antes_dicionario'").fetchone()
            if not existe:
                conexao.execute("CREATE TABLE classificacoes_antes_dicionario AS SELECT * FROM classificacoes")
                conexao.execute("CREATE TABLE processados_antes_dicionario AS SELECT * FROM processados")
                print("Cópia da classificação anterior guardada em classificacoes_antes_dicionario.")
            conexao.execute("DELETE FROM classificacoes")
            conexao.execute("DELETE FROM processados")
            conexao.commit()
        pendentes = comentarios_pendentes(conexao, participantes, args.limite)
        total_lotes = (len(pendentes) + TAMANHO_LOTE - 1) // TAMANHO_LOTE
        print(f"{len(pendentes)} comentários para classificar em {total_lotes} lotes (modelo {modelo}).")

        feitos = descartes = 0
        for numero, inicio in enumerate(range(0, len(pendentes), TAMANHO_LOTE), start=1):
            lote = pendentes[inicio:inicio + TAMANHO_LOTE]
            resultado = classificar_lote(cliente, modelo, instrucoes, lote)
            ok, desc = salvar_resultado(conexao, lote, resultado, nomes_validos, modelo)
            feitos += ok
            descartes += desc
            print(f"  Lote {numero}/{total_lotes}: {ok} de {len(lote)} classificados")
            if numero < total_lotes:
                time.sleep(PAUSA_ENTRE_LOTES)

    print(f"Pronto! {feitos} comentários classificados.")
    if descartes:
        print(f"{descartes} menções descartadas por nome ou sentimento fora da lista.")


if __name__ == "__main__":
    main()
