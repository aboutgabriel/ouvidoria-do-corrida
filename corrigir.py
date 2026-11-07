"""
Ouvidoria do Corrida | Correções da revisão humana

Quando a revisão encontra um erro claro do modelo num comentário que aparece
no painel, a correção é registrada em dados/correcoes.csv, com o motivo. Este
script aplica as correções no banco. O gerar_dados.py e o resumir.py chamam
ele automaticamente, então não é preciso rodar à parte.

As correções não mudam a taxa de acerto publicada (82%), que vem só da
amostra sorteada e revisada às cegas.

Uso (opcional, para conferir):
    python corrigir.py
"""

import csv
import os
import sqlite3

from verificar_apelidos import BANCO, PASTA

CORRECOES = os.path.join(PASTA, "dados", "correcoes.csv")
SENTIMENTOS = {"positivo", "negativo", "neutro"}


def aplicar_correcoes(verbose=False):
    if not os.path.exists(CORRECOES):
        return 0
    with open(CORRECOES, encoding="utf-8", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    aplicadas = 0
    with sqlite3.connect(BANCO) as conexao:
        for linha in linhas:
            if linha["sentimento"] not in SENTIMENTOS:
                print(f"  Aviso: sentimento inválido na correção de {linha['comentario_id']}: {linha['sentimento']}")
                continue
            cursor = conexao.execute(
                "UPDATE classificacoes SET sentimento = ? WHERE comentario_id = ? AND participante = ?",
                (linha["sentimento"], linha["comentario_id"], linha["participante"]),
            )
            if cursor.rowcount == 0:
                print(f"  Aviso: não achei {linha['participante']} no comentário {linha['comentario_id']}")
            else:
                aplicadas += 1
                if verbose:
                    print(f"  {linha['participante']}: {linha['comentario_id']} → {linha['sentimento']} ({linha['motivo']})")
    return aplicadas


if __name__ == "__main__":
    n = aplicar_correcoes(verbose=True)
    print(f"{n} correções aplicadas.")
