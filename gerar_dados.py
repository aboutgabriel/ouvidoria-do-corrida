"""
Ouvidoria do Corrida | Etapa 4: números para o painel

Junta comentários, classificações e resultados oficiais, calcula as métricas
de cada participante por episódio e gera o arquivo docs/dados.js, que o
painel (docs/index.html) lê.

Uso:
    python gerar_dados.py
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from verificar_apelidos import BANCO, PASTA

RESULTADOS = os.path.join(PASTA, "dados", "resultados.csv")
AVALIACAO = os.path.join(PASTA, "dados", "avaliacao.json")
SAIDA = os.path.join(PASTA, "docs", "dados.js")


def main():
    with sqlite3.connect(BANCO) as conexao:
        comentarios = pd.read_sql("SELECT id, episodio FROM comentarios", conexao)
        processados = pd.read_sql("SELECT comentario_id, modelo FROM processados", conexao)
        classificacoes = pd.read_sql("SELECT * FROM classificacoes", conexao)

    resultados = pd.read_csv(RESULTADOS)

    # Cada menção ganha o episódio do comentário de onde veio.
    mencoes = classificacoes.merge(comentarios, left_on="comentario_id", right_on="id")

    # Uma linha por (episódio, participante) com a contagem de cada sentimento.
    tabela = (
        mencoes.pivot_table(index=["episodio", "participante"], columns="sentimento",
                            values="comentario_id", aggfunc="count", fill_value=0)
        .reindex(columns=["positivo", "negativo", "neutro"], fill_value=0)
        .reset_index()
    )
    tabela["mencoes"] = tabela[["positivo", "negativo", "neutro"]].sum(axis=1)
    # Saldo da torcida: de -100 (só críticas) a +100 (só elogios).
    tabela["saldo"] = ((tabela["positivo"] - tabela["negativo"]) / tabela["mencoes"] * 100).round(1)

    tabela = tabela.merge(resultados, on=["episodio", "participante"], how="left")

    episodios = []
    for ep, grupo in tabela.groupby("episodio"):
        total = int((comentarios["episodio"] == ep).sum())
        com_citacao = int(mencoes.loc[mencoes["episodio"] == ep, "comentario_id"].nunique())
        episodios.append({
            "numero": int(ep),
            "comentarios": total,
            "comentarios_com_citacao": com_citacao,
            "participantes": [
                {
                    "nome": linha.participante,
                    "resultado": linha.resultado if isinstance(linha.resultado, str) else None,
                    "mencoes": int(linha.mencoes),
                    "positivo": int(linha.positivo),
                    "negativo": int(linha.negativo),
                    "neutro": int(linha.neutro),
                    "saldo": float(linha.saldo),
                }
                for linha in grupo.sort_values("mencoes", ascending=False).itertuples()
            ],
        })

    avaliacao = None
    if os.path.exists(AVALIACAO):
        with open(AVALIACAO, encoding="utf-8") as arquivo:
            avaliacao = json.load(arquivo)

    dados = {
        "exemplo": False,
        "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "modelo": processados["modelo"].mode().iat[0] if len(processados) else None,
        "total_comentarios": int(len(comentarios)),
        "episodios": episodios,
        "avaliacao": avaliacao,
    }

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        arquivo.write("window.DADOS = ")
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.write(";\n")

    print(f"Painel atualizado com {len(episodios)} episódio(s): {SAIDA}")
    for ep in episodios:
        print(f"  Episódio {ep['numero']}: {ep['comentarios_com_citacao']} comentários citam participantes")


if __name__ == "__main__":
    main()
