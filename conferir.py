"""
Ouvidoria do Corrida | Conferência dos números

Recalcula as métricas do painel direto em SQL, por um caminho diferente
do gerar_dados.py (que usa pandas). Se os dois chegarem ao mesmo resultado,
os números do painel estão certos.

Uso:
    python conferir.py 1     (episódio 1)
    python conferir.py 2     (episódio 2)
"""

import sqlite3
import sys

from verificar_apelidos import BANCO

episodio = int(sys.argv[1]) if len(sys.argv) > 1 else 1

CONSULTA = """
SELECT
    k.participante,
    COUNT(*)                                        AS mencoes,
    SUM(k.sentimento = 'positivo')                  AS elogios,
    SUM(k.sentimento = 'negativo')                  AS criticas,
    SUM(k.sentimento = 'neutro')                    AS neutros,
    ROUND(100.0 * (SUM(k.sentimento = 'positivo') - SUM(k.sentimento = 'negativo')) / COUNT(*), 1) AS saldo
FROM classificacoes k
JOIN comentarios c ON c.id = k.comentario_id
WHERE c.episodio = ?
GROUP BY k.participante
ORDER BY mencoes DESC
"""

with sqlite3.connect(BANCO) as conexao:
    linhas = conexao.execute(CONSULTA, (episodio,)).fetchall()
    citam = conexao.execute("""
        SELECT COUNT(DISTINCT k.comentario_id)
        FROM classificacoes k JOIN comentarios c ON c.id = k.comentario_id
        WHERE c.episodio = ?
    """, (episodio,)).fetchone()[0]

print(f"Episódio {episodio}: {citam} comentários citam participantes\n")
print(f"{'Participante':22}{'Menções':>9}{'Elogios':>9}{'Críticas':>10}{'Neutros':>9}{'Saldo':>8}")
for nome, mencoes, elogios, criticas, neutros, saldo in linhas:
    print(f"{nome:22}{mencoes:>9}{elogios:>9}{criticas:>10}{neutros:>9}{saldo:>8}")