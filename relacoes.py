"""
Ouvidoria do Corrida | Relações entre participantes e alcance dos temas

Duas contas simples, sem IA, em cima das menções já classificadas (primeiras 48 horas):

1. Duplas: em quantos comentários uma participante é criticada e outra é elogiada
   ao mesmo tempo ("a Aysha não merecia, a Latyffa sim"), e quem é elogiada junto.
   Mostra as comparações que a torcida faz, que não aparecem olhando uma pessoa por vez.
2. Curtidas por tema: a soma das curtidas dos comentários de cada tema. Um tema com
   poucos comentários pode ter sido endossado por muito mais gente.

O resultado vai para dados/relacoes.json e entra nos resumos como informação extra.

Uso:
    python relacoes.py
"""

import json
import os
import sqlite3
from collections import Counter
from itertools import combinations

import pandas as pd

from corrigir import aplicar_correcoes
from temas import mencoes_na_janela
from verificar_apelidos import BANCO, PASTA

SAIDA = os.path.join(PASTA, "dados", "relacoes.json")
MINIMO = 10   # duplas com menos comentários que isso ficam de fora
MAXIMO = 8    # quantas duplas guardar por episódio


def duplas(mencoes):
    """Por episódio: (criticada, elogiada) e (elogiada, elogiada) no mesmo comentário."""
    saida = {}
    for episodio, do_ep in mencoes.groupby("episodio"):
        contra, juntas = Counter(), Counter()
        for _, grupo in do_ep.groupby("comentario_id"):
            sentimento = dict(zip(grupo["participante"], grupo["sentimento"]))
            elogiadas = sorted(p for p, s in sentimento.items() if s == "positivo")
            criticadas = [p for p, s in sentimento.items() if s == "negativo"]
            for criticada in criticadas:
                for elogiada in elogiadas:
                    contra[(criticada, elogiada)] += 1
            for par in combinations(elogiadas, 2):
                juntas[par] += 1
        saida[str(episodio)] = {
            "critica_e_elogio": [{"criticada": a, "elogiada": b, "comentarios": n}
                                 for (a, b), n in contra.most_common(MAXIMO) if n >= MINIMO],
            "elogiadas_juntas": [{"participantes": list(par), "comentarios": n}
                                 for par, n in juntas.most_common(MAXIMO) if n >= MINIMO],
        }
    return saida


def curtidas_por_tema(conexao, mencoes):
    """Por episódio: os temas com mais curtidas somadas (sem os temas fixos 'geral' e 'outros')."""
    temas = pd.read_sql("SELECT * FROM temas", conexao)
    atribuicoes = pd.read_sql("SELECT * FROM temas_mencoes", conexao)
    base = (atribuicoes.merge(mencoes[["comentario_id", "participante", "curtidas"]], on=["comentario_id", "participante"])
                       .merge(temas, on=["episodio", "participante", "tema_id"]))
    fixo = base["tema_id"].isin([0, 98]) | base["nome"].str.startswith(("Opinião geral", "Outros"))
    base = base[~fixo]
    soma = (base.groupby(["episodio", "participante", "nome"])
                .agg(comentarios=("comentario_id", "count"), curtidas=("curtidas", "sum")).reset_index())
    saida = {}
    for episodio, do_ep in soma.groupby("episodio"):
        topo = do_ep.sort_values("curtidas", ascending=False).head(MAXIMO)
        saida[str(episodio)] = [{"participante": l.participante, "tema": l.nome, "comentarios": int(l.comentarios),
                                 "curtidas": int(l.curtidas)} for l in topo.itertuples()]
    return saida


def calcular(conexao):
    mencoes = mencoes_na_janela(conexao)
    pares, alcance = duplas(mencoes), curtidas_por_tema(conexao, mencoes)
    return {ep: {**pares.get(ep, {}), "temas_mais_curtidos": alcance.get(ep, [])} for ep in sorted(set(pares) | set(alcance))}


def linhas_para_prompt(relacoes_do_episodio):
    """As relações de um episódio em texto, para entrar no prompt dos resumos."""
    r, linhas = relacoes_do_episodio or {}, []
    if r.get("critica_e_elogio"):
        linhas.append("Comparações da torcida (comentários que criticam uma pessoa e elogiam outra):")
        linhas += [f"- critica {d['criticada']} e elogia {d['elogiada']}: {d['comentarios']} comentários" for d in r["critica_e_elogio"]]
    if r.get("elogiadas_juntas"):
        linhas.append("Elogiadas no mesmo comentário:")
        linhas += [f"- {' e '.join(d['participantes'])}: {d['comentarios']} comentários" for d in r["elogiadas_juntas"]]
    if r.get("temas_mais_curtidos"):
        linhas.append("Temas com mais curtidas somadas (alcance, não só quantidade):")
        linhas += [f"- {d['participante']}, \"{d['tema']}\": {d['comentarios']} comentários, {d['curtidas']} curtidas" for d in r["temas_mais_curtidos"]]
    return linhas


def main():
    aplicar_correcoes()
    conexao = sqlite3.connect(BANCO)
    relacoes = calcular(conexao)
    conexao.close()
    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        json.dump(relacoes, arquivo, ensure_ascii=False, indent=2)
    for ep, dados in relacoes.items():
        print(f"\nEpisódio {ep}")
        print("\n".join("  " + linha for linha in linhas_para_prompt(dados)))
    print(f"\nSalvo em {SAIDA}")


if __name__ == "__main__":
    main()
