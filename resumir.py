"""
Ouvidoria do Corrida | Etapa 5: a percepção da torcida em texto

Para cada participante, junta os números de cada episódio e os comentários
mais curtidos (elogios e críticas) e pede ao Gemini um resumo curto de como
a torcida a enxergou ao longo da temporada. Os resumos vão para
dados/resumos.json e aparecem na ficha de cada participante no painel.

Uso:
    python resumir.py             (resume só quem tem episódios novos)
    python resumir.py --todos     (refaz todos os resumos)
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

from verificar_apelidos import BANCO, PASTA

RESULTADOS = os.path.join(PASTA, "dados", "resultados.csv")
SAIDA = os.path.join(PASTA, "dados", "resumos.json")
COMENTARIOS_POR_TIPO = 8   # elogios e críticas mais curtidos, por episódio

INSTRUCOES = """Você escreve para a Ouvidoria do Corrida, um projeto que analisa os comentários do YouTube sobre o reality show Corrida das Blogueiras 8.

Com base APENAS nos números e nos comentários fornecidos, escreva um resumo de no máximo 3 frases (até 75 palavras) sobre como a torcida enxergou a participante ao longo dos episódios.

Regras:
1. Descreva a percepção da TORCIDA, nunca a sua opinião. Use construções como "a torcida elogiou", "os comentários criticaram".
2. Conte a trajetória na ordem dos episódios e cite os saldos exatamente como aparecem nos dados ("de −26 para +53"). Cada tema deve ser atribuído ao episódio em que aparece nos comentários.
3. Só cite um tema (liderança, maquiagem, atitude, carisma etc.) se ele aparecer em mais de um comentário. Não generalize a partir de um comentário isolado e não invente temas.
4. Quando a torcida estiver dividida, diga que está dividida, em vez de escolher um lado.
5. Não reproduza ofensas nem palavrões. Não fale de corpo, aparência física, vida pessoal, saúde, saúde mental ou estado emocional, mesmo que os comentários falem disso.
6. Comece pelo ponto mais marcante da trajetória, e não por "A trajetória de...". Evite advérbios genéricos como "drasticamente" e "significativamente".
7. Refira-se à pessoa pelo nome. Se não souber o gênero, evite artigos e adjetivos com gênero.
8. Tom editorial, leve e respeitoso, em português do Brasil, sem travessões.
9. O saldo vai de −100 (só críticas) a +100 (só elogios)."""


def saldo_texto(valor):
    """Arredonda como o painel: ",5" vai para longe do zero (52,5 vira +53)."""
    inteiro = int(abs(valor) + 0.5) * (1 if valor >= 0 else -1)
    return f"+{inteiro}" if inteiro > 0 else f"−{abs(inteiro)}" if inteiro < 0 else "0"


def montar_entrada(nome, linhas, comentarios):
    partes = [f"Participante: {nome}", ""]
    for linha in linhas.itertuples():
        resultado = linha.resultado if isinstance(linha.resultado, str) else "já estava fora"
        partes.append(
            f"Episódio {linha.episodio}: resultado oficial {resultado}; {linha.mencoes} menções; "
            f"{linha.positivo} elogios, {linha.negativo} críticas, {linha.neutro} neutros; saldo {saldo_texto(linha.saldo)}."
        )
        for sentimento, rotulo in (("positivo", "Elogios mais curtidos"), ("negativo", "Críticas mais curtidas")):
            selecao = comentarios[(comentarios["episodio"] == linha.episodio) & (comentarios["sentimento"] == sentimento)]
            selecao = selecao.sort_values("curtidas", ascending=False).head(COMENTARIOS_POR_TIPO)
            if len(selecao):
                partes.append(f"  {rotulo}:")
                # Tira @menções e links: o resumo não deve citar nem expor quem comentou.
                limpos = [re.sub(r"\s+", " ", re.sub(r"https?://\S+|@\S+", "", t)).strip() for t in selecao["texto"]]
                partes += [f"  - \"{t[:220]}\" ({c} curtidas)" for t, c in zip(limpos, selecao["curtidas"])]
        partes.append("")
    return "\n".join(partes)


def resumir(cliente, modelo, entrada):
    espera = 5
    for tentativa in range(5):
        try:
            resposta = cliente.models.generate_content(
                model=modelo,
                contents=entrada,
                config=types.GenerateContentConfig(system_instruction=INSTRUCOES, temperature=0.4),
            )
            return resposta.text.strip()
        except Exception as erro:
            texto = str(erro)
            if not any(c in texto for c in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")) or tentativa == 4:
                raise
            print(f"  Limite ou instabilidade da API. Nova tentativa em {espera}s...")
            time.sleep(espera)
            espera *= 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--todos", action="store_true", help="Refaz todos os resumos")
    args = parser.parse_args()

    load_dotenv()
    chave = os.getenv("GEMINI_API_KEY")
    if not chave or chave == "cole_sua_chave_aqui":
        sys.exit("Configure a GEMINI_API_KEY no arquivo .env antes de rodar.")
    modelo = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    cliente = genai.Client(api_key=chave)

    with sqlite3.connect(BANCO) as conexao:
        comentarios = pd.read_sql("""
            SELECT k.participante, k.sentimento, c.episodio, c.texto, c.curtidas
            FROM classificacoes k JOIN comentarios c ON c.id = k.comentario_id
        """, conexao)

    tabela = (
        comentarios.pivot_table(index=["participante", "episodio"], columns="sentimento",
                                values="texto", aggfunc="count", fill_value=0)
        .reindex(columns=["positivo", "negativo", "neutro"], fill_value=0)
        .reset_index()
    )
    tabela["mencoes"] = tabela[["positivo", "negativo", "neutro"]].sum(axis=1)
    tabela["saldo"] = (tabela["positivo"] - tabela["negativo"]) / tabela["mencoes"] * 100
    tabela = tabela.merge(pd.read_csv(RESULTADOS), on=["episodio", "participante"], how="left")

    resumos = {}
    if os.path.exists(SAIDA) and not args.todos:
        with open(SAIDA, encoding="utf-8") as arquivo:
            resumos = json.load(arquivo)

    for nome, linhas in tabela.groupby("participante"):
        episodios = sorted(int(e) for e in linhas["episodio"])
        if not args.todos and resumos.get(nome, {}).get("episodios") == episodios:
            continue  # já resumido com estes mesmos episódios
        print(f"Resumindo {nome} (episódios {episodios})...")
        entrada = montar_entrada(nome, linhas.sort_values("episodio"), comentarios[comentarios["participante"] == nome])
        resumos[nome] = {"episodios": episodios, "modelo": modelo, "texto": resumir(cliente, modelo, entrada)}
        with open(SAIDA, "w", encoding="utf-8") as arquivo:  # salva a cada participante
            json.dump(resumos, arquivo, ensure_ascii=False, indent=2)
        time.sleep(4)

    print(f"Pronto! {len(resumos)} resumos em {SAIDA}. Rode gerar_dados.py para levar ao painel.")


if __name__ == "__main__":
    main()
