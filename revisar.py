"""
Ouvidoria do Corrida | Revisão das classificações

Mostra comentários já classificados ao lado do que o modelo decidiu,
para conferir a qualidade antes de rodar tudo.

Uso:
    python revisar.py          (mostra 15 comentários)
    python revisar.py 30       (mostra 30)
"""

import sqlite3
import sys

from verificar_apelidos import BANCO

quantidade = int(sys.argv[1]) if len(sys.argv) > 1 else 15

with sqlite3.connect(BANCO) as conexao:
    ids = conexao.execute(
        "SELECT comentario_id FROM processados ORDER BY RANDOM() LIMIT ?", (quantidade,)
    ).fetchall()
    for (cid,) in ids:
        texto = conexao.execute("SELECT texto FROM comentarios WHERE id = ?", (cid,)).fetchone()[0]
        mencoes = conexao.execute(
            "SELECT participante, sentimento FROM classificacoes WHERE comentario_id = ?", (cid,)
        ).fetchall()
        print(f"\n{texto[:300]}")
        if mencoes:
            for participante, sentimento in mencoes:
                print(f"   -> {participante}: {sentimento}")
        else:
            print("   -> nenhuma participante identificada")
