"""
Ouvidoria do Corrida | Teste do dicionário do fandom

Classifica de novo as 100 menções revisadas à mão (dados/avaliacao_revisar.xlsx)
de duas formas, com as instruções atuais e com o dicionário do fandom
(dados/dicionario.csv), e compara as duas com a revisão humana. Rodar as duas
versões agora, no mesmo dia, garante que a diferença vem do dicionário e não de
alguma mudança no modelo.

Não altera o banco nem o painel: só mostra o resultado e salva
dados/teste_dicionario.json.

Uso:
    python testar_dicionario.py
"""

import json
import os
import sqlite3
import sys
import time

import pandas as pd
from dotenv import load_dotenv
from google import genai

from classificar import TAMANHO_LOTE, PAUSA_ENTRE_LOTES, carregar_participantes, classificar_lote, montar_instrucoes
from verificar_apelidos import BANCO, PASTA

PLANILHA = os.path.join(PASTA, "dados", "avaliacao_revisar.xlsx")
GABARITO = os.path.join(PASTA, "dados", "avaliacao_modelo.csv")
SAIDA = os.path.join(PASTA, "dados", "teste_dicionario.json")


def classificar_amostra(cliente, modelo, instrucoes, comentarios):
    """Devolve {(comentario_id, participante): sentimento}."""
    respostas = {}
    for inicio in range(0, len(comentarios), TAMANHO_LOTE):
        lote = comentarios[inicio:inicio + TAMANHO_LOTE]
        resultado = classificar_lote(cliente, modelo, instrucoes, lote)
        for item in resultado:
            i = item.get("n")
            if isinstance(i, int) and 1 <= i <= len(lote):
                for m in item.get("mencoes", []):
                    respostas[(lote[i - 1][0], m.get("participante"))] = m.get("sentimento")
        time.sleep(PAUSA_ENTRE_LOTES)
    return respostas


def main():
    load_dotenv()
    chave = os.getenv("GEMINI_API_KEY")
    if not chave or chave == "cole_sua_chave_aqui":
        sys.exit("Configure a GEMINI_API_KEY no arquivo .env antes de rodar.")
    modelo = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    cliente = genai.Client(api_key=chave)

    humano = pd.read_excel(PLANILHA, sheet_name="Revisar").rename(
        columns={"Ela é citada?": "citada", "Sentimento para ela": "humano"})
    amostra = humano[["n", "citada", "humano"]].merge(
        pd.read_csv(GABARITO).rename(columns={"sentimento": "original"}), on="n")
    amostra = amostra[(amostra["citada"] == "sim") & amostra["humano"].notna()]

    ids = list(dict.fromkeys(amostra["comentario_id"]))
    with sqlite3.connect(BANCO) as conexao:
        textos = dict(conexao.execute(
            f"SELECT id, texto FROM comentarios WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall())
    comentarios = [(i, textos[i]) for i in ids]

    participantes = carregar_participantes()
    print(f"{len(amostra)} menções revisadas, em {len(comentarios)} comentários.")
    print("Classificando com as instruções atuais...")
    sem = classificar_amostra(cliente, modelo, montar_instrucoes(participantes), comentarios)
    print("Classificando com o dicionário do fandom...")
    com = classificar_amostra(cliente, modelo, montar_instrucoes(participantes, dicionario=True), comentarios)

    chave_de = lambda r: (r.comentario_id, r.participante)
    amostra["atual"] = [sem.get(chave_de(r), "não citou") for r in amostra.itertuples()]
    amostra["dicionario"] = [com.get(chave_de(r), "não citou") for r in amostra.itertuples()]

    acerto = {col: round((amostra[col] == amostra["humano"]).mean() * 100, 1)
              for col in ("original", "atual", "dicionario")}
    print("\nAcerto em relação à sua revisão:")
    print(f"  Classificação original (a que está no painel): {acerto['original']}%")
    print(f"  Instruções atuais, rodadas hoje:              {acerto['atual']}%")
    print(f"  Com o dicionário do fandom:                   {acerto['dicionario']}%")

    mudou = amostra[amostra["atual"] != amostra["dicionario"]]
    print(f"\n{len(mudou)} menções mudaram com o dicionário:")
    for r in mudou.itertuples():
        marca = "melhorou" if r.dicionario == r.humano else ("piorou" if r.atual == r.humano else "continua errado")
        print(f"  [{marca}] n={r.n} {r.participante}: {r.atual} -> {r.dicionario} (você: {r.humano})")

    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        json.dump({"modelo": modelo, "mencoes": int(len(amostra)), "acerto": acerto,
                   "mudancas": [{"n": int(r.n), "participante": r.participante, "atual": r.atual,
                                 "dicionario": r.dicionario, "humano": r.humano} for r in mudou.itertuples()]},
                  arquivo, ensure_ascii=False, indent=2)
    print(f"\nResultado salvo em {SAIDA}.")


if __name__ == "__main__":
    main()
