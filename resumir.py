"""
Ouvidoria do Corrida | Etapa 5: a percepção da torcida em texto

Faz dois tipos de resumo com o Gemini:

1. Por participante: junta os números de cada episódio, os comentários mais
   curtidos (elogios e críticas) e o que aconteceu com ela no programa
   (dados/contexto.json, escrito à mão a partir da transcrição) e resume como
   a torcida a enxergou ao longo da temporada. O contexto serve para o resumo
   dizer a que momento cada tema se refere. Vai para dados/resumos.json e aparece na ficha do painel.
2. Por episódio: junta os números do episódio, as cenas mais comentadas e os
   comentários mais curtidos (sobre qualquer assunto) e resume como a torcida
   recebeu o episódio. Vai para dados/resumos_episodios.json e aparece no topo
   da página de cada episódio.

Todo resumo deve ser revisado por uma pessoa antes de ir ao ar.

Uso:
    python resumir.py                   (resume só o que é novo)
    python resumir.py --participantes   (refaz só os resumos das participantes;
                                         guarda os antigos em dados/resumos_antes.json)
    python resumir.py --recalcular      (refaz os resumos das participantes e dos episódios;
                                         guarda os antigos em dados/resumos_antes.json e
                                         dados/resumos_episodios_antes.json)
    python resumir.py --todos           (refaz todos os resumos e apaga correções manuais)
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

from corrigir import aplicar_correcoes
from temas import contar_temas
from relacoes import calcular as calcular_relacoes, linhas_para_prompt
from janela import janelas, na_janela
from verificar_apelidos import BANCO, PASTA

RESULTADOS = os.path.join(PASTA, "dados", "resultados.csv")
SAIDA = os.path.join(PASTA, "dados", "resumos.json")
SAIDA_EPISODIOS = os.path.join(PASTA, "dados", "resumos_episodios.json")
CENAS = os.path.join(PASTA, "dados", "cenas.json")
CONTEXTO = os.path.join(PASTA, "dados", "contexto.json")
BACKUP = os.path.join(PASTA, "dados", "resumos_antes.json")
COMENTARIOS_POR_TIPO = 10  # elogios e críticas mais curtidos, por episódio
COMENTARIOS_DO_EPISODIO = 30   # comentários mais curtidos do episódio, sobre qualquer assunto

INSTRUCOES = """Você escreve para a Ouvidoria do Corrida, um projeto que analisa os comentários do YouTube sobre o reality show Corrida das Blogueiras 8.

Você recebe, para cada episódio, os números da participante, o que aconteceu com ela no programa (escrito à mão a partir do episódio), TODAS as menções separadas por tema, com a contagem de elogios e críticas de cada tema, e alguns dos comentários mais curtidos. Com base APENAS nisso, escreva um resumo de 4 a 6 frases (até 120 palavras) sobre como a torcida enxergou a participante ao longo dos episódios.

Regras:
1. Descreva a percepção da TORCIDA, nunca a sua opinião. Use construções como "a torcida elogiou", "os comentários criticaram".
2. Conte a trajetória na ordem dos episódios e cite os saldos exatamente como aparecem nos dados ("de −26 para +52"). Cada tema deve ser atribuído ao episódio em que aparece nos comentários.
3. Os temas são a base do resumo, porque contam todas as menções, e não só as mais curtidas. Explique cada saldo pelos temas que concentram mais críticas ou elogios e use os números ("62 das 159 críticas falam da discussão com Talitah", "quase metade das menções"). Não cite um tema com menos de 10% das menções do episódio, a não ser que ele seja o principal motivo de elogio ou de crítica.
3b. Não diga que um único fato fez o saldo subir ou cair se as críticas ou os elogios estão espalhados por vários temas. Nesse caso, diga que foi uma soma de fatores e cite os dois ou três principais, com números. Use os comentários mais curtidos só como exemplo, nunca como prova de que um assunto foi o mais falado.
3c. O tema "Opinião geral, sem citar um momento" mostra quanta gente só declarou torcida ou rejeição. Ele pode ser citado ("boa parte dos elogios é só torcida"), mas não explica por que o saldo mudou: para isso, use os temas específicos.
4. Seja concreto: diga a que momento do programa cada tema se refere, usando o contexto (qual prova, o que a participante fez, com quem). Escreva "criticaram o nervosismo na apresentação do gloss, quando a dupla estourou o tempo", e não "criticaram a comunicação durante as apresentações". Não use palavras vagas como "postura", "comportamento", "desempenho", "atitude" ou "dinâmicas" sem dizer o que aconteceu.
5. O contexto só explica os fatos. A reação da torcida tem que vir dos comentários: não diga que a torcida elogiou ou criticou algo que não aparece neles. Se um fato do contexto não aparece nos comentários, não o cite.
6. Quando a torcida estiver dividida, diga que está dividida e sobre o quê, em vez de escolher um lado.
7. Não reproduza ofensas nem palavrões. Não fale de corpo, aparência física, vida pessoal, saúde, saúde mental ou estado emocional, mesmo que os comentários falem disso.
8. Comece pelo ponto mais marcante da trajetória, e não por "A trajetória de...". Evite advérbios genéricos como "drasticamente" e "significativamente".
9. Refira-se à pessoa pelo nome. Se não souber o gênero, evite artigos e adjetivos com gênero.
10. Tom leve e natural, como um fã que escreve bem contando o episódio para um amigo, em português do Brasil, sem travessões. Frases curtas e diretas. Não repita "a torcida" em toda frase: varie com "os comentários", "muita gente", "alguns". Evite fórmulas prontas como "virou o jogo", "dominou a conversa", "no calor do momento", "conquistou o público" e frases que anunciam algo com dois-pontos. Confira a concordância de gênero e de tempo verbal ("pediu que contratasse", não "pediu que contrate").
11. O saldo vai de −100 (só críticas) a +100 (só elogios)."""


INSTRUCOES_EPISODIO = """Você escreve para a Ouvidoria do Corrida, um projeto que analisa os comentários do YouTube sobre o reality show Corrida das Blogueiras 8.

Com base APENAS nos números, no que aconteceu no episódio (escrito à mão), nos temas das menções de cada participante (que contam TODAS as menções), nas cenas e nos comentários fornecidos, escreva um resumo de 5 a 7 frases (até 150 palavras) sobre como a torcida recebeu o episódio, com contexto suficiente para quem não assistiu entender o que aconteceu.

Regras:
1. Descreva a reação da TORCIDA, nunca a sua opinião. Use construções como "a torcida comentou", "os comentários se dividiram".
2. Diga quais assuntos e momentos dominaram a conversa e qual foi o clima geral (empolgação, revolta, divisão, humor).
3. Pode citar participantes e números, sempre exatamente como aparecem nos dados. Não liste todas as participantes: fale só de quem marcou o episódio.
4. Só cite um assunto se ele aparecer nos temas, nas cenas mais comentadas ou em vários comentários. Não invente acontecimentos e não generalize a partir de um comentário isolado. Quando disser que algo foi muito comentado, apoie com os números dos temas. Não diga que um único fato explica o saldo de alguém se as críticas estão espalhadas por vários temas.
4b. Seja concreto: diga a que momento do programa cada assunto se refere, usando o que aconteceu no episódio (qual prova, quem fez o quê). Não use palavras vagas como "postura", "desempenho" ou "comportamento" sem dizer o que aconteceu. O que aconteceu no episódio só explica os fatos: a reação da torcida tem que vir dos comentários.
5. Quando a torcida estiver dividida, diga que está dividida.
6. Não reproduza ofensas nem palavrões. Não fale de corpo, aparência física, vida pessoal, saúde, saúde mental ou estado emocional de ninguém, mesmo que os comentários falem disso. Fatos do programa, como uma desistência, podem ser citados.
7. Não comece com "O episódio" nem com "A torcida". Evite advérbios genéricos como "drasticamente" e "significativamente".
8. Tom leve e natural, como um fã que escreve bem contando o episódio para um amigo, em português do Brasil, sem travessões. Frases curtas e diretas. Não repita "a torcida" em toda frase: varie com "os comentários", "muita gente", "alguns". Evite fórmulas prontas como "virou o jogo", "dominou a conversa", "no calor do momento", "conquistou o público" e frases que anunciam algo com dois-pontos. Confira a concordância de gênero e de tempo verbal ("pediu que contratasse", não "pediu que contrate").
9. O saldo vai de −100 (só críticas) a +100 (só elogios)."""


def limpar(texto, limite=300):
    """Tira @menções e links: o resumo não deve citar nem expor quem comentou."""
    texto = re.sub(r"\s+", " ", re.sub(r"https?://\S+|@\S+", "", texto)).strip()
    return texto[:limite]


def saldo_texto(valor):
    """Arredonda como o painel: ",5" vai para longe do zero (52,5 vira +53)."""
    inteiro = int(abs(valor) + 0.5) * (1 if valor >= 0 else -1)
    return f"+{inteiro}" if inteiro > 0 else f"−{abs(inteiro)}" if inteiro < 0 else "0"


def linhas_de_temas(lista, recuo="  "):
    """Os temas de uma participante num episódio, com as contagens, em texto para o prompt."""
    saida = []
    for t in lista:
        linha = (f"{recuo}- {t['nome']}: {t['mencoes']} menções ({t['pct']}% do episódio), "
                 f"{t['negativo']} críticas, {t['positivo']} elogios, {t['neutro']} neutros. {t['descricao']}")
        if t.get("exemplo") and t["id"] != 0:
            linha += f" Exemplo: \"{limpar(t['exemplo']['texto'], 200)}\" ({t['exemplo']['curtidas']} curtidas)"
        saida.append(linha)
    return saida


def montar_entrada(nome, linhas, comentarios, contexto=None, temas_por=None):
    contexto = contexto or {}
    temas_por = temas_por or {}
    partes = [f"Participante: {nome}", ""]
    for linha in linhas.itertuples():
        resultado = linha.resultado if isinstance(linha.resultado, str) else "já estava fora"
        partes.append(
            f"Episódio {linha.episodio}: resultado oficial {resultado}; {linha.mencoes} menções; "
            f"{linha.positivo} elogios, {linha.negativo} críticas, {linha.neutro} neutros; saldo {saldo_texto(linha.saldo)}."
        )
        do_ep = contexto.get(str(int(linha.episodio)), {})
        if do_ep.get("geral"):
            partes.append(f"  O episódio: {do_ep['geral']}")
        if do_ep.get("participantes", {}).get(nome):
            partes.append(f"  O que aconteceu com {nome}: {do_ep['participantes'][nome]}")
        lista = temas_por.get((int(linha.episodio), nome), [])
        if lista:
            partes.append(f"  Do que falam as {linha.mencoes} menções, separadas por tema:")
            partes += linhas_de_temas(lista, "  ")
        por_tipo = 5 if lista else COMENTARIOS_POR_TIPO
        for sentimento, rotulo in (("positivo", "Elogios mais curtidos"), ("negativo", "Críticas mais curtidas")):
            selecao = comentarios[(comentarios["episodio"] == linha.episodio) & (comentarios["sentimento"] == sentimento)]
            selecao = selecao.sort_values("curtidas", ascending=False).head(por_tipo)
            if len(selecao):
                partes.append(f"  {rotulo}:")
                partes += [f"  - \"{limpar(t)}\" ({c} curtidas)" for t, c in zip(selecao["texto"], selecao["curtidas"])]
        partes.append("")
    return "\n".join(partes)


def montar_entrada_episodio(ep, linhas, todos, cenas, contexto=None, temas_por=None, relacoes=None):
    """Números do episódio, o que aconteceu (escrito à mão), cenas descritas à mão e os comentários mais curtidos."""
    do_ep = todos[todos["episodio"] == ep]
    partes = [f"Episódio {ep}: {len(do_ep)} comentários lidos."]
    ctx = (contexto or {}).get(str(int(ep)), {})
    if ctx.get("geral"):
        partes += ["", f"O que aconteceu no episódio: {ctx['geral']}"]
    for nome, texto in ctx.get("participantes", {}).items():
        partes.append(f"- {nome}: {texto}")
    partes += ["", "Participantes (menções, elogios, críticas, saldo, resultado oficial):"]
    for linha in linhas.sort_values("mencoes", ascending=False).itertuples():
        resultado = linha.resultado if isinstance(linha.resultado, str) else "já estava fora"
        partes.append(f"- {linha.participante}: {linha.mencoes} menções, {linha.positivo} elogios, "
                      f"{linha.negativo} críticas, saldo {saldo_texto(linha.saldo)}, {resultado}")
        lista = [t for t in (temas_por or {}).get((int(ep), linha.participante), []) if t["id"] != 0][:3]
        if lista:
            partes.append("  Principais temas:")
            partes += linhas_de_temas(lista, "    ")
    descritas = [c["descricao"] for c in cenas.values() if c.get("descricao")]
    if descritas:
        partes += ["", "Cenas mais comentadas (em ordem de minutagem):"] + [f"- {d}" for d in descritas]
    extras = linhas_para_prompt((relacoes or {}).get(str(ep)))
    if extras:
        partes += [""] + extras
    partes += ["", "Comentários mais curtidos do episódio:"]
    for linha in do_ep.sort_values("curtidas", ascending=False).head(COMENTARIOS_DO_EPISODIO).itertuples():
        partes.append(f"- \"{limpar(linha.texto)}\" ({linha.curtidas} curtidas)")
    return "\n".join(partes)


def resumir(cliente, modelo, entrada, instrucoes=INSTRUCOES):
    espera = 5
    for tentativa in range(5):
        try:
            resposta = cliente.models.generate_content(
                model=modelo,
                contents=entrada,
                config=types.GenerateContentConfig(system_instruction=instrucoes, temperature=0.4),
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
    parser.add_argument("--recalcular", action="store_true",
                        help="Refaz os resumos de participantes e episódios, guardando uma cópia dos antigos")
    parser.add_argument("--participantes", action="store_true",
                        help="Refaz só os resumos das participantes (os de episódio ficam como estão)")
    args = parser.parse_args()

    aplicar_correcoes()  # correções da revisão humana (dados/correcoes.csv)
    load_dotenv()
    chave = os.getenv("GEMINI_API_KEY")
    if not chave or chave == "cole_sua_chave_aqui":
        sys.exit("Configure a GEMINI_API_KEY no arquivo .env antes de rodar.")
    modelo = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    cliente = genai.Client(api_key=chave)

    with sqlite3.connect(BANCO) as conexao:
        todos = pd.read_sql("SELECT episodio, texto, curtidas, publicado_em, coletado_em FROM comentarios", conexao)
        comentarios = pd.read_sql("""
            SELECT k.comentario_id, k.participante, k.sentimento, c.episodio, c.texto, c.curtidas, c.publicado_em
            FROM classificacoes k JOIN comentarios c ON c.id = k.comentario_id
        """, conexao)
    # Só as primeiras 48 horas de cada episódio, como no painel (ver janela.py).
    tabela_janelas = janelas(todos)
    todos = na_janela(todos, tabela_janelas)
    comentarios = na_janela(comentarios, tabela_janelas)
    with sqlite3.connect(BANCO) as conexao:
        temas_por = contar_temas(conexao, comentarios)
        relacoes = calcular_relacoes(conexao)  # duplas e curtidas por tema, sem IA
    if not temas_por:
        print("  Aviso: ainda não há temas. Rode python temas.py antes, para os resumos usarem todas as menções.")

    tabela = (
        comentarios.pivot_table(index=["participante", "episodio"], columns="sentimento",
                                values="texto", aggfunc="count", fill_value=0)
        .reindex(columns=["positivo", "negativo", "neutro"], fill_value=0)
        .reset_index()
    )
    tabela["mencoes"] = tabela[["positivo", "negativo", "neutro"]].sum(axis=1)
    tabela["saldo"] = (tabela["positivo"] - tabela["negativo"]) / tabela["mencoes"] * 100
    tabela = tabela.merge(pd.read_csv(RESULTADOS), on=["episodio", "participante"], how="left")

    contexto = {}
    if os.path.exists(CONTEXTO):
        with open(CONTEXTO, encoding="utf-8") as arquivo:
            contexto = json.load(arquivo)
    for ep in sorted(int(e) for e in tabela["episodio"].unique()):
        if str(ep) not in contexto:
            print(f"  Aviso: o episódio {ep} não tem contexto em dados/contexto.json; o resumo vai sair mais genérico.")

    refazer = args.todos or args.participantes or args.recalcular
    resumos = {}
    if os.path.exists(SAIDA):
        with open(SAIDA, encoding="utf-8") as arquivo:
            resumos = json.load(arquivo)
        if refazer:
            with open(BACKUP, "w", encoding="utf-8") as arquivo:  # guarda os revisados à mão
                json.dump(resumos, arquivo, ensure_ascii=False, indent=2)
            print(f"Resumos antigos guardados em {BACKUP}.")
            resumos = {}

    for nome, linhas in tabela.groupby("participante"):
        episodios = sorted(int(e) for e in linhas["episodio"])
        if not refazer and resumos.get(nome, {}).get("episodios") == episodios:
            continue  # já resumido com estes mesmos episódios
        print(f"Resumindo {nome} (episódios {episodios})...")
        entrada = montar_entrada(nome, linhas.sort_values("episodio"),
                                 comentarios[comentarios["participante"] == nome], contexto, temas_por)
        resumos[nome] = {"episodios": episodios, "modelo": modelo, "texto": resumir(cliente, modelo, entrada)}
        with open(SAIDA, "w", encoding="utf-8") as arquivo:  # salva a cada participante
            json.dump(resumos, arquivo, ensure_ascii=False, indent=2)
        time.sleep(4)

    print(f"{len(resumos)} resumos de participantes em {SAIDA}.")
    if args.participantes:
        print("Revise os textos novos antes de publicar. Depois rode gerar_dados.py para levar ao painel.")
        return

    # ---------- resumos por episódio ----------
    cenas = {}
    if os.path.exists(CENAS):
        with open(CENAS, encoding="utf-8") as arquivo:
            cenas = json.load(arquivo)
    resumos_ep = {}
    if os.path.exists(SAIDA_EPISODIOS) and not args.todos:
        with open(SAIDA_EPISODIOS, encoding="utf-8") as arquivo:
            resumos_ep = json.load(arquivo)
        if args.recalcular:
            with open(SAIDA_EPISODIOS.replace(".json", "_antes.json"), "w", encoding="utf-8") as arquivo:
                json.dump(resumos_ep, arquivo, ensure_ascii=False, indent=2)
            resumos_ep = {}

    for ep, linhas in tabela.groupby("episodio"):
        chave_ep = str(int(ep))
        if chave_ep in resumos_ep:
            continue  # já resumido; para refazer um só, apague a entrada dele no arquivo
        print(f"Resumindo o episódio {chave_ep}...")
        entrada = montar_entrada_episodio(ep, linhas, todos, cenas.get(chave_ep, {}), contexto, temas_por, relacoes)
        resumos_ep[chave_ep] = {"modelo": modelo, "texto": resumir(cliente, modelo, entrada, INSTRUCOES_EPISODIO)}
        with open(SAIDA_EPISODIOS, "w", encoding="utf-8") as arquivo:
            json.dump(resumos_ep, arquivo, ensure_ascii=False, indent=2)
        time.sleep(4)

    print(f"{len(resumos_ep)} resumos de episódios em {SAIDA_EPISODIOS}.")
    print("Revise os textos novos antes de publicar. Depois rode gerar_dados.py para levar ao painel.")


if __name__ == "__main__":
    main()
