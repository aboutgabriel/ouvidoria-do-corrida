"""
Ouvidoria do Corrida | Etapa 3a: amostra para avaliação

Sorteia menções classificadas pelo modelo e gera uma planilha para revisão
humana. A planilha NÃO mostra o sentimento que o modelo escolheu, para que
a revisão não seja influenciada por ele (avaliação às cegas). A resposta do
modelo fica guardada em um arquivo separado.

Uso:
    python gerar_amostra.py              (100 menções, metade de cada episódio)
    python gerar_amostra.py --tamanho 150
"""

import argparse
import os
import sqlite3

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from verificar_apelidos import BANCO, PASTA

PLANILHA = os.path.join(PASTA, "dados", "avaliacao_revisar.xlsx")
GABARITO = os.path.join(PASTA, "dados", "avaliacao_modelo.csv")
SEMENTE = 42  # sorteio reproduzível: rodar de novo gera a mesma amostra


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tamanho", type=int, default=100)
    args = parser.parse_args()

    with sqlite3.connect(BANCO) as conexao:
        mencoes = pd.read_sql("""
            SELECT k.comentario_id, c.episodio, c.texto, k.participante, k.sentimento
            FROM classificacoes k JOIN comentarios c ON c.id = k.comentario_id
        """, conexao)

    # Mesma quantidade de cada episódio, para nenhum dominar a avaliação.
    por_episodio = args.tamanho // mencoes["episodio"].nunique()
    partes = [grupo.sample(n=min(por_episodio, len(grupo)), random_state=SEMENTE)
              for _, grupo in mencoes.groupby("episodio")]
    amostra = (
        pd.concat(partes)
        .sample(frac=1, random_state=SEMENTE)  # embaralha a ordem
        .reset_index(drop=True)
    )
    amostra.insert(0, "n", range(1, len(amostra) + 1))
    amostra[["n", "comentario_id", "participante", "sentimento"]].to_csv(GABARITO, index=False, encoding="utf-8")

    wb = Workbook()
    ws = wb.active
    ws.title = "Revisar"
    ws.append(["n", "Episódio", "Comentário", "Participante", "Ela é citada?", "Sentimento para ela"])
    for linha in amostra.itertuples():
        ws.append([linha.n, linha.episodio, linha.texto, linha.participante, None, None])

    cabecalho = PatternFill("solid", fgColor="34182A")
    for celula in ws[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = cabecalho
    for coluna, largura in zip("ABCDEF", (5, 9, 80, 20, 14, 20)):
        ws.column_dimensions[coluna].width = largura
    for linha in ws.iter_rows(min_row=2):
        linha[2].alignment = Alignment(wrap_text=True, vertical="top")
        for celula in (linha[0], linha[1], linha[3]):
            celula.alignment = Alignment(vertical="top")
    ws.freeze_panes = "A2"

    # Listas suspensas: evitam erros de digitação na revisão.
    ultima = len(amostra) + 1
    citada = DataValidation(type="list", formula1='"sim,não"', allow_blank=True)
    sentimento = DataValidation(type="list", formula1='"positivo,negativo,neutro"', allow_blank=True)
    ws.add_data_validation(citada)
    ws.add_data_validation(sentimento)
    citada.add(f"E2:E{ultima}")
    sentimento.add(f"F2:F{ultima}")

    instrucoes = wb.create_sheet("Como revisar")
    for texto in [
        "Para cada linha da aba Revisar:",
        "1. Leia o comentário.",
        "2. Na coluna 'Ela é citada?', marque 'sim' se o comentário realmente fala da participante indicada, ou 'não' se foi um engano.",
        "3. Se for 'sim', escolha o sentimento do comentário PARA ESSA PARTICIPANTE: positivo, negativo ou neutro.",
        "Classifique pelo que você entende do comentário, sem tentar adivinhar o que o modelo respondeu.",
        "Salve o arquivo com o mesmo nome e no mesmo lugar quando terminar.",
    ]:
        instrucoes.append([texto])
    instrucoes.column_dimensions["A"].width = 110

    wb.save(PLANILHA)
    print(f"{len(amostra)} menções sorteadas.")
    print(f"Planilha para revisar: {PLANILHA}")
    print("Não abra o arquivo avaliacao_modelo.csv antes de terminar a revisão.")


if __name__ == "__main__":
    main()
