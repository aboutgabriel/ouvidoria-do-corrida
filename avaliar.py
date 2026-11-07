"""
Ouvidoria do Corrida | Etapa 3b: avaliação do modelo

Compara a revisão humana (planilha preenchida) com as respostas do modelo e
calcula as taxas de acerto. O resultado vai para dados/avaliacao.json, que o
painel mostra na seção de método.

Uso:
    python avaliar.py
"""

import json
import os

import pandas as pd

from verificar_apelidos import PASTA

PLANILHA = os.path.join(PASTA, "dados", "avaliacao_revisar.xlsx")
GABARITO = os.path.join(PASTA, "dados", "avaliacao_modelo.csv")
SAIDA = os.path.join(PASTA, "dados", "avaliacao.json")


def main():
    humano = pd.read_excel(PLANILHA, sheet_name="Revisar")
    humano = humano.rename(columns={"Ela é citada?": "citada", "Sentimento para ela": "sentimento_humano"})
    modelo = pd.read_csv(GABARITO).rename(columns={"sentimento": "sentimento_modelo"})
    dados = humano[["n", "citada", "sentimento_humano"]].merge(modelo, on="n")

    revisadas = dados[dados["citada"].isin(["sim", "não"])]
    if len(revisadas) < len(dados):
        print(f"Atenção: {len(dados) - len(revisadas)} linhas ainda sem revisão foram ignoradas.")

    # 1. A participante identificada pelo modelo é mesmo citada?
    identificacao = (revisadas["citada"] == "sim").mean() * 100

    # 2. Entre as citações corretas, o sentimento bate com o humano?
    validas = revisadas[(revisadas["citada"] == "sim") & revisadas["sentimento_humano"].notna()]
    acerto = (validas["sentimento_humano"] == validas["sentimento_modelo"]).mean() * 100

    # Onde o modelo erra: linhas = revisão humana, colunas = modelo.
    confusao = pd.crosstab(validas["sentimento_humano"], validas["sentimento_modelo"],
                           rownames=["humano"], colnames=["modelo"])

    resultado = {
        "amostra": int(len(revisadas)),
        "identificacao": round(identificacao, 1),
        "acerto": round(acerto, 1),
        "confusao": {h: {m: int(v) for m, v in linha.items()} for h, linha in confusao.iterrows()},
    }
    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        json.dump(resultado, arquivo, ensure_ascii=False, indent=2)

    print(f"Menções revisadas: {resultado['amostra']}")
    print(f"Participante identificada corretamente: {resultado['identificacao']}%")
    print(f"Sentimento igual ao da revisão humana: {resultado['acerto']}%")
    print("\nOnde estão as divergências (linhas = você, colunas = modelo):")
    print(confusao.to_string())
    print(f"\nResultado salvo em {SAIDA}. Rode gerar_dados.py para levar ao painel.")


if __name__ == "__main__":
    main()
