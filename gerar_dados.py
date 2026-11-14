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
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

import pandas as pd

from corrigir import aplicar_correcoes
from temas import contar_temas
from janela import JANELA_HORAS, janelas, na_janela
from verificar_apelidos import BANCO, PASTA

RESULTADOS = os.path.join(PASTA, "dados", "resultados.csv")
# Se o flop de cada episódio teve eliminação (sim/nao). Episódio sem linha = resultado ainda não revelado.
ELIMINACOES = os.path.join(PASTA, "dados", "eliminacoes.csv")
AVALIACAO = os.path.join(PASTA, "dados", "avaliacao.json")
RESUMOS = os.path.join(PASTA, "dados", "resumos.json")
RESUMOS_EPISODIOS = os.path.join(PASTA, "dados", "resumos_episodios.json")
CENAS = os.path.join(PASTA, "dados", "cenas.json")  # descrições das cenas, escritas à mão
CONTEXTO = os.path.join(PASTA, "dados", "contexto.json")  # o que aconteceu com cada participante, escrito à mão
# Comentários que não devem aparecer em destaque no painel (continuam contando nos números).
OCULTAS = os.path.join(PASTA, "dados", "citacoes_ocultas.csv")
IDS_OCULTOS = set(pd.read_csv(OCULTAS)["comentario_id"]) if os.path.exists(OCULTAS) else set()
SAIDA = os.path.join(PASTA, "docs", "dados.js")
FOTOS = os.path.join(PASTA, "docs", "fotos")
CREDITO_FOTOS = "Foto: DiaTV/divulgação"
EXTENSOES_FOTO = (".jpg", ".jpeg", ".png", ".webp")

# Anfitriões: só aparecem como decoração no topo do painel, com foto e nome.
APRESENTADORES = []

# Minutagens que a torcida escreve: 14:32 ou 1:02:15
MINUTAGEM = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?![\d:])")
DURACAO_MAXIMA = 130 * 60  # descarta horários que não cabem num episódio


def limpar_citacao(texto, limite=320):
    """Tira @menções e links antes de publicar um comentário como citação."""
    texto = re.sub(r"https?://\S+|@\S+", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if texto[:1] in "\"“" and texto[-1:] in "\"”" and texto.count('"') + texto.count("“") + texto.count("”") == 2:
        texto = texto[1:-1].strip()  # tira aspas que envolvem o comentário inteiro, para não ficar ““…””
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0] + "…"


PROXIMO = os.path.join(PASTA, "dados", "proximo_episodio.json")  # data do próximo relatório, escrita à mão
# Temas escolhidos à mão para comprovar, com comentários reais, os fatos citados no resumo de cada episódio.
COMENTARIOS_RESUMO = os.path.join(PASTA, "dados", "comentarios_resumo.json")
MAX_COMENTARIOS_RESUMO = 6
MIN_CURTIDAS_DESTAQUE = 10  # o mesmo corte das citações em destaque no painel


def comentarios_do_resumo(episodios):
    """Para cada episódio, o comentário mais curtido de cada tema escolhido em comentarios_resumo.json."""
    if not os.path.exists(COMENTARIOS_RESUMO):
        return {}
    with open(COMENTARIOS_RESUMO, encoding="utf-8") as arquivo:
        escolhas = {ep: lista for ep, lista in json.load(arquivo).items() if not ep.startswith("_")}
    saida = {}
    for ep in episodios:
        lista = escolhas.get(str(ep["numero"]), [])
        if len(lista) > MAX_COMENTARIOS_RESUMO:
            print(f"  Aviso: episódio {ep['numero']} tem {len(lista)} temas em comentarios_resumo.json; só os {MAX_COMENTARIOS_RESUMO} primeiros entram.")
        itens = []
        for nome, tema in lista[:MAX_COMENTARIOS_RESUMO]:
            participante = next((p for p in ep["participantes"] if p["nome"] == nome), None)
            achado = next((t for t in (participante or {}).get("temas", []) if t["nome"] == tema), None)
            exemplo = (achado or {}).get("exemplo")
            if not achado:
                print(f"  Aviso: tema \"{tema}\" de {nome} não existe no episódio {ep['numero']} (confira o nome na ficha).")
            elif not exemplo or exemplo["curtidas"] < MIN_CURTIDAS_DESTAQUE:
                print(f"  Aviso: o tema \"{tema}\" de {nome} não tem comentário com {MIN_CURTIDAS_DESTAQUE}+ curtidas e ficou de fora.")
            else:
                itens.append({"nome": nome, "tema": tema, "mencoes": achado["mencoes"], **exemplo})
        if itens:
            saida[str(ep["numero"])] = itens
    return saida


def proximo_episodio(episodios):
    """O próximo episódio, se ele ainda não tiver dados no painel (vira a aba "em breve")."""
    if not os.path.exists(PROXIMO):
        return None
    with open(PROXIMO, encoding="utf-8") as arquivo:
        proximo = json.load(arquivo)
    ja_tem = {int(e["numero"]) for e in episodios}
    if int(proximo.get("numero", 0)) in ja_tem:
        print(f"  Aviso: o episódio {proximo['numero']} já está no painel. Atualize dados/proximo_episodio.json para o seguinte.")
        return None
    return {k: v for k, v in proximo.items() if not k.startswith("_")}


def nome_de_arquivo(nome):
    """'Bárbara Freitas' vira 'barbara-freitas': sem acentos, minúsculas e com hífens."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def achar_fotos(nomes):
    """Procura em docs/fotos um arquivo para cada participante, como talitah-sampaio.jpg."""
    if not os.path.isdir(FOTOS):
        return {}
    arquivos = {os.path.splitext(a)[0].lower(): a for a in os.listdir(FOTOS) if a.lower().endswith(EXTENSOES_FOTO)}
    fotos = {}
    for nome in nomes:
        arquivo = arquivos.pop(nome_de_arquivo(nome), None)
        if arquivo:
            fotos[nome] = f"fotos/{arquivo}"
    for sobra in arquivos.values():
        print(f"  Aviso: a foto {sobra} não corresponde a nenhuma participante e ficou de fora.")
    return fotos


def mais_curtido(df):
    """Comentário com mais curtidas de um grupo, sem links nem textos longos demais."""
    df = df[~df["texto"].str.contains("http", na=False) & ~df["id"].isin(IDS_OCULTOS)]
    if df.empty:
        return None
    linha = df.sort_values("curtidas", ascending=False).iloc[0]
    return {"texto": limpar_citacao(linha["texto"]), "curtidas": int(linha["curtidas"])}


def cenas_do_episodio(comentarios, revisao=None):
    """Conta as minutagens citadas, minuto a minuto, e acha os três maiores picos.

    comentarios: tuplas (id, texto, curtidas).
    revisao: dados/cenas.json daquele episódio, {minuto: {"descricao": ..., "comentario_id": ...}}.
    A descrição conta o que acontece na cena; o comentario_id troca a citação
    automática (a mais curtida) por outro comentário do mesmo trecho.
    """
    revisao = revisao or {}
    marcas = []  # (segundos, curtidas, texto, id)
    for id_, texto, curtidas in comentarios:
        for h, m, seg in MINUTAGEM.findall(texto):
            h, m, seg = int(h or 0), int(m), int(seg)
            total = h * 3600 + m * 60 + seg
            if m < 60 and seg < 60 and total <= DURACAO_MAXIMA:
                marcas.append((total, curtidas, texto, id_))
    if not marcas:
        return {"por_minuto": [], "picos": []}
    ultimo = max(t for t, _, _, _ in marcas) // 60
    por_minuto = [0] * (ultimo + 1)
    for t, _, _, _ in marcas:
        por_minuto[t // 60] += 1

    # Picos: minutos com mais citações, separados por pelo menos 3 minutos.
    picos = []
    for minuto in sorted(range(len(por_minuto)), key=lambda i: -por_minuto[i]):
        if por_minuto[minuto] < 3 or len(picos) == 3:
            break
        if all(abs(minuto - p) >= 3 for p in picos):
            picos.append(minuto)
    resultado = []
    for minuto in picos:
        janela = [x for x in marcas if minuto - 1 <= x[0] // 60 <= minuto + 1]
        segundos = sorted(t for t, _, _, _ in janela)[len(janela) // 2]
        nota = revisao.get(str(minuto), {})
        escolhido = next((x for x in janela if x[3] == nota.get("comentario_id")), None)
        _, curtidas, texto, _ = escolhido or max(janela, key=lambda x: x[1])
        resultado.append({
            "minuto": minuto,
            "segundos": segundos,
            "citacoes": len(janela),
            "descricao": nota.get("descricao"),
            "comentario": limpar_citacao(texto),
            "curtidas": int(curtidas),
        })
    return {"por_minuto": por_minuto, "picos": resultado}


def main():
    aplicar_correcoes()  # correções da revisão humana (dados/correcoes.csv)
    with sqlite3.connect(BANCO) as conexao:
        todos = pd.read_sql("SELECT id, episodio, video_id, texto, curtidas, publicado_em, coletado_em FROM comentarios", conexao)
        processados = pd.read_sql("SELECT comentario_id, modelo FROM processados", conexao)
        classificacoes = pd.read_sql("SELECT * FROM classificacoes", conexao)

    resultados = pd.read_csv(RESULTADOS)
    eliminacoes = {}
    if os.path.exists(ELIMINACOES):
        for linha in pd.read_csv(ELIMINACOES, dtype=str).fillna("").itertuples():
            eliminacoes[int(linha.episodio)] = {"houve": linha.houve_eliminacao.strip().lower() == "sim", "motivo": linha.motivo}

    # Quem venceu a prova do flop de cada episódio: já está salvo e não entra na previsão.
    vencedores_flop = {}
    caminho_vencedores = os.path.join(PASTA, "dados", "vencedores_flop.csv")
    if os.path.exists(caminho_vencedores):
        for linha in pd.read_csv(caminho_vencedores, dtype=str).fillna("").itertuples():
            vencedores_flop[int(linha.episodio)] = linha.participante.strip()

    # Só entram os comentários das primeiras 48 horas de cada episódio (ver janela.py).
    tabela_janelas = janelas(todos)
    comentarios = na_janela(todos, tabela_janelas)

    revisao_cenas = {}
    if os.path.exists(CENAS):
        with open(CENAS, encoding="utf-8") as arquivo:
            revisao_cenas = json.load(arquivo)

    # Cada menção ganha o episódio do comentário de onde veio.
    mencoes = classificacoes.merge(comentarios, left_on="comentario_id", right_on="id")

    # Do que a torcida fala sobre cada participante (temas.py), com contagens reais.
    with sqlite3.connect(BANCO) as conexao:
        temas_por = contar_temas(conexao, mencoes, IDS_OCULTOS)
    for lista in temas_por.values():
        for tema in lista:
            if tema["exemplo"]:
                tema["exemplo"]["texto"] = limpar_citacao(tema["exemplo"]["texto"], 220)

    # Para cada participante e episódio: o elogio e a crítica mais curtidos.
    destaques = {}
    for (ep, nome), grupo in mencoes.groupby(["episodio", "participante"]):
        destaques[(ep, nome)] = {
            "elogio": mais_curtido(grupo[grupo["sentimento"] == "positivo"]),
            "critica": mais_curtido(grupo[grupo["sentimento"] == "negativo"]),
        }

    # Uma linha por (episódio, participante) com a contagem de cada sentimento.
    tabela = (
        mencoes.pivot_table(index=["episodio", "participante"], columns="sentimento",
                            values="comentario_id", aggfunc="count", fill_value=0)
        .reindex(columns=["positivo", "negativo", "neutro"], fill_value=0)
        .reset_index()
    )
    tabela["mencoes"] = tabela[["positivo", "negativo", "neutro"]].sum(axis=1)
    # Saldo da torcida: de -100 (só críticas) a +100 (só elogios).
    # Guarda o saldo com 4 casas: arredondar antes da hora causa erro duplo
    # (52,48 viraria 52,5 e depois 53 no painel, quando o certo é 52).
    tabela["saldo"] = ((tabela["positivo"] - tabela["negativo"]) / tabela["mencoes"] * 100).round(4)

    tabela = tabela.merge(resultados, on=["episodio", "participante"], how="left")

    episodios = []
    for ep, grupo in tabela.groupby("episodio"):
        do_episodio = comentarios[comentarios["episodio"] == ep]
        com_citacao = int(mencoes.loc[mencoes["episodio"] == ep, "comentario_id"].nunique())
        episodios.append({
            "numero": int(ep),
            "video_id": do_episodio["video_id"].iat[0],
            "comentarios": int(len(do_episodio)),
            "eliminacao": eliminacoes.get(int(ep)),
            "venceu_flop": vencedores_flop.get(int(ep)),
            "janela": {
                "horas": JANELA_HORAS,
                "inicio": tabela_janelas.at[ep, "inicio"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fim": tabela_janelas.at[ep, "fim"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "aberta": bool(tabela_janelas.at[ep, "aberta"]),
                "fora_da_janela": int((todos["episodio"] == ep).sum() - len(do_episodio)),
            },
            "comentarios_com_citacao": com_citacao,
            "cenas": cenas_do_episodio(zip(do_episodio["id"], do_episodio["texto"], do_episodio["curtidas"]),
                                       revisao_cenas.get(str(int(ep)))),
            "participantes": [
                {
                    "nome": linha.participante,
                    "resultado": linha.resultado if isinstance(linha.resultado, str) else None,
                    "mencoes": int(linha.mencoes),
                    "positivo": int(linha.positivo),
                    "negativo": int(linha.negativo),
                    "neutro": int(linha.neutro),
                    "saldo": float(linha.saldo),
                    **destaques.get((ep, linha.participante), {}),
                    "temas": temas_por.get((int(ep), linha.participante), []),
                }
                for linha in grupo.sort_values("mencoes", ascending=False).itertuples()
            ],
        })

    avaliacao = None
    if os.path.exists(AVALIACAO):
        with open(AVALIACAO, encoding="utf-8") as arquivo:
            avaliacao = json.load(arquivo)

    resumos = {}
    if os.path.exists(RESUMOS):
        with open(RESUMOS, encoding="utf-8") as arquivo:
            resumos = {nome: r["texto"] for nome, r in json.load(arquivo).items()}

    resumos_episodios = {}
    if os.path.exists(RESUMOS_EPISODIOS):
        with open(RESUMOS_EPISODIOS, encoding="utf-8") as arquivo:
            resumos_episodios = {ep: r["texto"] for ep, r in json.load(arquivo).items()}

    ganchos, aconteceu = {}, {}
    if os.path.exists(CONTEXTO):
        with open(CONTEXTO, encoding="utf-8") as arquivo:
            contexto = {ep: c for ep, c in json.load(arquivo).items() if not ep.startswith("_")}
        ganchos = {ep: c.get("ganchos", {}) for ep, c in contexto.items()}
        # Resumo curto do episódio para quem não assistiu, escrito à mão (campo "painel").
        aconteceu = {ep: c["painel"] for ep, c in contexto.items() if c.get("painel")}

    dados = {
        "exemplo": False,
        "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "proximo": proximo_episodio(episodios),
        "modelo": processados["modelo"].mode().iat[0] if len(processados) else None,
        "total_comentarios": int(len(comentarios)),
        "episodios": episodios,
        "avaliacao": avaliacao,
        "resumos": resumos,
        "resumos_episodios": resumos_episodios,
        "ganchos": ganchos,
        "aconteceu": aconteceu,
        "comentarios_resumo": comentarios_do_resumo(episodios),
        "fotos": achar_fotos(sorted(tabela["participante"].unique()) + APRESENTADORES),
        "apresentadores": APRESENTADORES,
        # Recorte sem fundo dos anfitriões (docs/fotos/edu-recorte.png): se existir, substitui o medalhão.
        "recortes": {n: f"fotos/{n.lower()}-recorte.png" for n in APRESENTADORES
                     if os.path.exists(os.path.join(FOTOS, f"{n.lower()}-recorte.png"))},
        "credito_fotos": CREDITO_FOTOS,
    }

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as arquivo:
        arquivo.write("window.DADOS = ")
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.write(";\n")

    print(f"Painel atualizado com {len(episodios)} episódio(s): {SAIDA}")
    print(f"  Fotos encontradas: {len(dados['fotos'])} de {tabela['participante'].nunique() + len(APRESENTADORES)} "
          f"({tabela['participante'].nunique()} participantes e {len(APRESENTADORES)} anfitriões)")
    for ep in episodios:
        j = ep["janela"]
        aviso = " (janela ainda aberta: colete de novo depois de " + j["fim"][:16].replace("T", " ") + " UTC)" if j["aberta"] else ""
        print(f"  Episódio {ep['numero']}: {ep['comentarios']} comentários nas primeiras {j['horas']}h, "
              f"{ep['comentarios_com_citacao']} citam participantes{aviso}")


if __name__ == "__main__":
    main()
