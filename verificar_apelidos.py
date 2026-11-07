"""
Ouvidoria do Corrida | Verificação de apelidos

Conta quantos comentários citam cada forma de chamar as participantes,
para descobrir quais apelidos a torcida realmente usa (e quais não aparecem).

Uso:
    python verificar_apelidos.py
    python verificar_apelidos.py --buscar barb   (mostra exemplos de um termo)
"""

import argparse
import json
import os
import re
import sqlite3
import unicodedata

PASTA = os.path.dirname(os.path.abspath(__file__))
BANCO = os.path.join(PASTA, "dados", "corrida.db")
PARTICIPANTES = os.path.join(PASTA, "dados", "participantes.json")


def normalizar(texto):
    """Minúsculas e sem acento, para 'Bárbara' e 'barbara' contarem igual."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower()


def citou(termo, texto_normalizado):
    # \b garante palavra inteira: "barb" não conta dentro de "barbie" ou "barbaridade".
    return re.search(rf"\b{re.escape(normalizar(termo))}\b", texto_normalizado) is not None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--buscar", help="Mostra até 10 comentários que contêm este termo")
    args = parser.parse_args()

    with sqlite3.connect(BANCO) as conexao:
        linhas = conexao.execute("SELECT episodio, texto FROM comentarios").fetchall()
    comentarios = [(ep, normalizar(texto), texto) for ep, texto in linhas]
    print(f"{len(comentarios)} comentários no banco.\n")

    if args.buscar:
        achados = [original for _, norm, original in comentarios if citou(args.buscar, norm)]
        print(f'"{args.buscar}" aparece em {len(achados)} comentários. Exemplos:\n')
        for texto in achados[:10]:
            print(f"  - {texto[:200]}")
        return

    with open(PARTICIPANTES, encoding="utf-8") as arquivo:
        participantes = json.load(arquivo)

    for p in participantes:
        total = sum(1 for _, norm, _ in comentarios if any(citou(a, norm) for a in p["apelidos"]))
        print(f"{p['nome']}: {total} comentários")
        for apelido in p["apelidos"]:
            qtd = sum(1 for _, norm, _ in comentarios if citou(apelido, norm))
            aviso = "   <- não aparece, pode remover" if qtd == 0 else ""
            print(f"    {apelido}: {qtd}{aviso}")
        print()


if __name__ == "__main__":
    main()
