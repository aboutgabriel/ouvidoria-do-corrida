"""
Ouvidoria do Corrida | Etapa 3b: do que a torcida fala

Para cada participante em cada episódio, o Gemini lê TODAS as menções das
primeiras 48 horas e:
  A. define de 3 a 6 temas que resumem do que os comentários falam;
  B. coloca cada menção em um desses temas (ou em "Outros assuntos").

Com isso, os números deixam de ser só "quantos elogios e quantas críticas" e
passam a dizer DO QUE são as críticas: "62 das 159 críticas falam da discussão
com Talitah". Os resumos e as fichas usam essas contagens, em vez de
generalizar a partir dos poucos comentários mais curtidos.

Uso:
    python temas.py              (faz só o que falta)
    python temas.py --refazer    (apaga os temas e refaz tudo)

Pode ser interrompido e rodado de novo: o que já foi feito é pulado.
"""

import argparse
import json
import os
import sqlite3
import sys
import time

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

from classificar import SEGURANCA, RespostaVazia
from janela import janelas, na_janela
from verificar_apelidos import BANCO, PASTA

CONTEXTO = os.path.join(PASTA, "dados", "contexto.json")
OCULTAS = os.path.join(PASTA, "dados", "citacoes_ocultas.csv")
NOMES_REVISADOS = os.path.join(PASTA, "dados", "temas_nomes.csv")  # nomes de tema corrigidos na revisão humana

MIN_MENCOES = 15        # abaixo disso, poucos comentários para falar em "temas"
TAMANHO_LOTE = 60       # menções por chamada na etapa B
PAUSA = 4               # segundos entre chamadas, para respeitar o limite gratuito
LIMITE_TEXTO = 280      # caracteres de cada comentário enviados ao modelo
MAX_AMOSTRA_A = 500     # na etapa A, grupos maiores mandam uma amostra (as mais curtidas e um sorteio)
OUTROS = 0              # id fixo do tema "Outros assuntos"
NOME_OUTROS = "Outros assuntos"
GERAL = 98              # id fixo de quem só declara torcida ou rejeição, sem motivo
NOME_GERAL = "Opinião geral, sem citar um momento"
DESCRICAO_GERAL = "Comentários que só declaram amor, torcida ou rejeição pela pessoa, sem dizer por quê."
ERROS_TEMPORARIOS = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "10053", "10054",
                     "onnection", "imeout", "timed out", "RemoteProtocol", "EOF")


# ---------------------------------------------------------------- banco

def criar_tabelas(conexao):
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS temas (
            episodio     INTEGER NOT NULL,
            participante TEXT NOT NULL,
            tema_id      INTEGER NOT NULL,
            nome         TEXT NOT NULL,
            descricao    TEXT NOT NULL,
            PRIMARY KEY (episodio, participante, tema_id)
        )
    """)
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS temas_mencoes (
            comentario_id TEXT NOT NULL,
            participante  TEXT NOT NULL,
            episodio      INTEGER NOT NULL,
            tema_id       INTEGER NOT NULL,
            PRIMARY KEY (comentario_id, participante)
        )
    """)
    conexao.commit()


def mencoes_na_janela(conexao):
    """Todas as menções classificadas das primeiras 48 horas, com texto e curtidas."""
    todos = pd.read_sql("SELECT id, episodio, texto, curtidas, publicado_em, coletado_em FROM comentarios", conexao)
    classificacoes = pd.read_sql("SELECT * FROM classificacoes", conexao)
    comentarios = na_janela(todos, janelas(todos))
    return classificacoes.merge(comentarios, left_on="comentario_id", right_on="id")


# ---------------------------------------------------------------- modelo

ESQUEMA_TEMAS = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "nome": types.Schema(type=types.Type.STRING, description="Nome curto e concreto do tema, até 6 palavras"),
            "descricao": types.Schema(type=types.Type.STRING, description="Uma frase dizendo o que os comentários desse tema dizem"),
        },
        required=["nome", "descricao"],
    ),
)

ESQUEMA_ATRIBUICAO = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "n": types.Schema(type=types.Type.INTEGER, description="Número do comentário"),
            "tema": types.Schema(type=types.Type.INTEGER, description="Número do tema"),
        },
        required=["n", "tema"],
    ),
)


def instrucoes_temas(nome, ep, contexto_ep):
    fatos = contexto_ep.get("participantes", {}).get(nome, "")
    return f"""Você recebe TODOS os comentários do YouTube que citam {nome} no episódio {ep} do reality Corrida das Blogueiras 8, cada um com o sentimento dele para {nome} (positivo, negativo ou neutro).

O que aconteceu no episódio: {contexto_ep.get('geral', '')}
O que aconteceu com {nome}: {fatos}

Liste de 3 a 7 temas que expliquem do que esses comentários falam sobre {nome}.

Regras:
1. Cada tema precisa aparecer em vários comentários. Os temas, junto com os dois temas fixos abaixo, devem cobrir pelo menos 80% dos comentários.
2. Cada tema diz o motivo concreto: qual momento, com quem, em qual prova, o que foi dito ou feito. Nome curto, até 7 palavras. Bom: "Discussão com Talitah sobre idade", "Deixou Breia sem dupla", "Maquiagem de Ana Mary B no flop". Proibido usar nomes genéricos como "Personalidade e carisma", "Postura no jogo", "Comportamento", "Desempenho nas provas", "Torcida e favoritismo", "Polêmicas".
3. Comentários que só dizem que amam, torcem ou não suportam a pessoa, sem dizer por quê, NÃO viram tema: eles vão para o tema fixo "{NOME_GERAL}", que é adicionado depois.
4. A descrição diz, em uma frase, o que a torcida fala nesse tema, sem opinião sua.
5. Se elogios e críticas sobre o mesmo momento forem muito diferentes, tudo bem ficarem no mesmo tema: o sentimento já está marcado em cada comentário.
5b. Não crie um tema "Outros": ele também é adicionado depois, automaticamente.
6. Não crie temas sobre saúde, saúde mental ou corpo de ninguém. Comentários assim ficam em "Outros".
7. Português do Brasil, sem travessões."""


def instrucoes_atribuicao(nome, temas):
    lista = "\n".join(f"{i}. {t['nome']}: {t['descricao']}" for i, t in enumerate(temas, start=1))
    return f"""Você recebe comentários do YouTube que citam {nome}, do reality Corrida das Blogueiras 8.
Para cada comentário, diga o número do tema que melhor descreve o que ele fala sobre {nome}.

Temas:
{lista}
{len(temas) + 1}. {NOME_GERAL}: {DESCRICAO_GERAL}
{OUTROS}. {NOME_OUTROS}: o comentário não se encaixa em nenhum dos temas acima.

Prefira sempre um tema específico quando o comentário citar um momento, uma prova ou outra pessoa.
Responda com um item para cada comentário, sem pular nenhum."""


def chamar(cliente, modelo, instrucoes, entrada, esquema):
    espera = 5
    for tentativa in range(5):
        try:
            resposta = cliente.models.generate_content(
                model=modelo,
                contents=entrada,
                config=types.GenerateContentConfig(
                    system_instruction=instrucoes,
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=esquema,
                    safety_settings=SEGURANCA,
                ),
            )
            if not resposta.text:
                motivo = resposta.candidates[0].finish_reason if resposta.candidates else resposta.prompt_feedback
                raise RespostaVazia(str(motivo))
            return json.loads(resposta.text)
        except RespostaVazia:
            raise
        except Exception as erro:
            texto_erro = str(erro)
            temporario = any(c in texto_erro for c in ERROS_TEMPORARIOS)
            if not temporario or tentativa == 4:
                raise
            print(f"  Limite ou instabilidade da API. Nova tentativa em {espera}s...")
            time.sleep(espera)
            espera *= 2


def numerar(linhas):
    return "\n".join(
        f"[{i}] ({s}) {' '.join(str(t).split())[:LIMITE_TEXTO]}"
        for i, (s, t) in enumerate(linhas, start=1)
    )


def eh_fixo(nome):
    """O modelo às vezes recria por conta própria os temas fixos ("Outros", "Opinião geral")."""
    n = " ".join(str(nome).lower().replace("ã", "a").replace("ç", "c").split())
    return n.startswith("outros") or n.startswith("opiniao geral")


def definir_temas(cliente, modelo, nome, ep, grupo, contexto_ep):
    if len(grupo) > MAX_AMOSTRA_A:
        # Grupo muito grande: metade com as mais curtidas e metade sorteada, para não
        # perder os assuntos de quem teve poucas curtidas. A etapa B classifica todas.
        metade = MAX_AMOSTRA_A // 2
        topo = grupo.head(metade)
        grupo = pd.concat([topo, grupo.drop(topo.index).sample(metade, random_state=42)])
    linhas = list(zip(grupo["sentimento"], grupo["texto"]))
    temas = chamar(cliente, modelo, instrucoes_temas(nome, ep, contexto_ep), numerar(linhas), ESQUEMA_TEMAS)
    temas = [t for t in temas if isinstance(t, dict) and t.get("nome") and t.get("descricao")]
    temas = [t for t in temas if not eh_fixo(t["nome"])][:7]
    if len(temas) < 2:
        raise ValueError(f"o modelo devolveu só {len(temas)} tema(s)")
    return temas


def atribuir_lote(cliente, modelo, instrucoes, lote, total_temas):
    """Devolve {posição no lote: tema_id}. Se o modelo devolver vazio, divide o lote ao meio."""
    try:
        resposta = chamar(cliente, modelo, instrucoes, numerar(lote), ESQUEMA_ATRIBUICAO)
    except RespostaVazia:
        if len(lote) == 1:
            return {}
        meio = len(lote) // 2
        a = atribuir_lote(cliente, modelo, instrucoes, lote[:meio], total_temas)
        b = atribuir_lote(cliente, modelo, instrucoes, lote[meio:], total_temas)
        return {**a, **{k + meio: v for k, v in b.items()}}
    saida = {}
    for item in resposta:
        if not isinstance(item, dict):
            continue
        n, tema = item.get("n"), item.get("tema")
        if isinstance(n, int) and 1 <= n <= len(lote):
            if tema == total_temas + 1:
                saida[n] = GERAL
            else:
                saida[n] = tema if isinstance(tema, int) and 0 <= tema <= total_temas else OUTROS
    return saida


# ---------------------------------------------------------------- contagens (usadas pelo painel e pelos resumos)

def contar_temas(conexao, mencoes, ocultos=None):
    """Para cada (episódio, participante), a lista de temas com contagens por
    sentimento e o comentário mais curtido de cada tema. As contagens usam a
    classificação atual (já com as correções humanas) e só as primeiras 48 horas."""
    ocultos = ocultos or set()
    existe = conexao.execute("SELECT name FROM sqlite_master WHERE name = 'temas_mencoes'").fetchone()
    if not existe:
        return {}
    temas = pd.read_sql("SELECT * FROM temas", conexao)
    atrib = pd.read_sql("SELECT comentario_id, participante, episodio, tema_id FROM temas_mencoes", conexao)
    # Junta no tema fixo as cópias que o modelo criou por conta própria
    # (um segundo "Opinião geral" ou um "Outros" dentro dos temas específicos).
    copias = temas[temas["nome"].map(eh_fixo) & ~temas["tema_id"].isin([GERAL, OUTROS])]
    for linha in copias.itertuples():
        destino = OUTROS if linha.nome.lower().startswith("outros") else GERAL
        alvo = (atrib["episodio"] == linha.episodio) & (atrib["participante"] == linha.participante) & (atrib["tema_id"] == linha.tema_id)
        atrib.loc[alvo, "tema_id"] = destino
    atrib = atrib.drop(columns="episodio")
    # Nomes de tema corrigidos à mão (ex.: "Postura com Breia no jogo" vira "Relação com Breia").
    if os.path.exists(NOMES_REVISADOS):
        for linha in pd.read_csv(NOMES_REVISADOS).itertuples():
            alvo = (temas["episodio"] == linha.episodio) & (temas["participante"] == linha.participante) & (temas["nome"] == linha.nome_original)
            temas.loc[alvo, "nome"] = linha.nome_novo
    base = mencoes.merge(atrib, on=["comentario_id", "participante"], how="inner")
    saida = {}
    for (ep, nome), grupo in base.groupby(["episodio", "participante"]):
        total_mencoes = int(((mencoes["episodio"] == ep) & (mencoes["participante"] == nome)).sum())
        nomes = temas[(temas["episodio"] == ep) & (temas["participante"] == nome)].set_index("tema_id")
        lista = []
        for tema_id, g in grupo.groupby("tema_id"):
            if tema_id not in nomes.index:
                continue
            contagem = g["sentimento"].value_counts()
            candidatos = g[~g["texto"].str.contains("http", na=False) & ~g["comentario_id"].isin(ocultos)]
            exemplo = candidatos.sort_values("curtidas", ascending=False).head(1)
            lista.append({
                "id": int(tema_id),
                "nome": nomes.at[tema_id, "nome"],
                "descricao": nomes.at[tema_id, "descricao"],
                "mencoes": int(len(g)),
                "pct": round(len(g) / total_mencoes * 100) if total_mencoes else 0,
                "positivo": int(contagem.get("positivo", 0)),
                "negativo": int(contagem.get("negativo", 0)),
                "neutro": int(contagem.get("neutro", 0)),
                "exemplo": None if exemplo.empty else {
                    "texto": exemplo["texto"].iat[0],
                    "curtidas": int(exemplo["curtidas"].iat[0]),
                    "sentimento": exemplo["sentimento"].iat[0],
                },
            })
        # Mais citados primeiro; opinião geral e "Outros assuntos" sempre no fim.
        lista.sort(key=lambda t: (t["id"] == OUTROS, t["id"] == GERAL, -t["mencoes"]))
        saida[(int(ep), nome)] = lista
    return saida


# ---------------------------------------------------------------- execução

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refazer", action="store_true", help="Apaga os temas e refaz tudo")
    args = parser.parse_args()

    load_dotenv()
    chave = os.getenv("GEMINI_API_KEY")
    if not chave or chave == "cole_sua_chave_aqui":
        sys.exit("Configure a GEMINI_API_KEY no arquivo .env antes de rodar.")
    modelo = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    cliente = genai.Client(api_key=chave)

    contexto = {}
    if os.path.exists(CONTEXTO):
        with open(CONTEXTO, encoding="utf-8") as arquivo:
            contexto = json.load(arquivo)

    with sqlite3.connect(BANCO) as conexao:
        criar_tabelas(conexao)
        if args.refazer:
            conexao.execute("DELETE FROM temas")
            conexao.execute("DELETE FROM temas_mencoes")
            conexao.commit()

        mencoes = mencoes_na_janela(conexao)
        feitos = set(conexao.execute("SELECT DISTINCT episodio, participante FROM temas").fetchall())
        atribuidas = set(conexao.execute("SELECT comentario_id, participante FROM temas_mencoes").fetchall())

        grupos = [(int(ep), nome, g.sort_values("curtidas", ascending=False))
                  for (ep, nome), g in mencoes.groupby(["episodio", "participante"]) if len(g) >= MIN_MENCOES]
        print(f"{len(grupos)} combinações de episódio e participante com pelo menos {MIN_MENCOES} menções.")

        for ep, nome, grupo in grupos:
            contexto_ep = contexto.get(str(ep), {})

            # Etapa A: definir os temas a partir de todas as menções.
            if (ep, nome) not in feitos:
                print(f"Episódio {ep}, {nome}: definindo temas a partir de {len(grupo)} menções...")
                try:
                    temas = definir_temas(cliente, modelo, nome, ep, grupo, contexto_ep)
                except Exception as erro:
                    print(f"  Aviso: não foi possível definir os temas ({erro}). Pulando por agora.")
                    continue
                for i, t in enumerate(temas, start=1):
                    conexao.execute("INSERT INTO temas VALUES (?, ?, ?, ?, ?)", (ep, nome, i, t["nome"].strip(), t["descricao"].strip()))
                conexao.execute("INSERT INTO temas VALUES (?, ?, ?, ?, ?)", (ep, nome, GERAL, NOME_GERAL, DESCRICAO_GERAL))
                conexao.execute("INSERT INTO temas VALUES (?, ?, ?, ?, ?)",
                                (ep, nome, OUTROS, NOME_OUTROS, "Comentários que não se encaixam nos outros temas."))
                conexao.commit()
                for i, t in enumerate(temas, start=1):
                    print(f"  {i}. {t['nome']}")
                time.sleep(PAUSA)

            temas = [{"nome": n, "descricao": d} for n, d in conexao.execute(
                "SELECT nome, descricao FROM temas WHERE episodio = ? AND participante = ? AND tema_id BETWEEN 1 AND 90 ORDER BY tema_id",
                (ep, nome)).fetchall()]
            instrucoes = instrucoes_atribuicao(nome, temas)

            # Etapa B: colocar cada menção em um tema, em lotes.
            pendentes = grupo[[(cid, nome) not in atribuidas for cid in grupo["comentario_id"]]]
            if pendentes.empty:
                continue
            print(f"Episódio {ep}, {nome}: classificando {len(pendentes)} menções nos temas...")
            sem_tema = 0
            for inicio in range(0, len(pendentes), TAMANHO_LOTE):
                parte = pendentes.iloc[inicio:inicio + TAMANHO_LOTE]
                lote = list(zip(parte["sentimento"], parte["texto"]))
                resultado = atribuir_lote(cliente, modelo, instrucoes, lote, len(temas))
                for i, cid in enumerate(parte["comentario_id"], start=1):
                    if i in resultado:
                        conexao.execute("INSERT OR REPLACE INTO temas_mencoes VALUES (?, ?, ?, ?)", (cid, nome, ep, resultado[i]))
                    else:
                        sem_tema += 1  # fica pendente para a próxima rodada
                conexao.commit()
                time.sleep(PAUSA)
            if sem_tema:
                print(f"  {sem_tema} menções ficaram sem tema. Rode de novo para tentar outra vez.")

        # Resumo no terminal, para revisar.
        ocultos = set(pd.read_csv(OCULTAS)["comentario_id"]) if os.path.exists(OCULTAS) else set()
        for (ep, nome), lista in sorted(contar_temas(conexao, mencoes, ocultos).items()):
            total = int(((mencoes["episodio"] == ep) & (mencoes["participante"] == nome)).sum())
            print(f"\nEpisódio {ep} | {nome} ({total} menções)")
            for t in lista:
                print(f"  {t['pct']:3d}%  {t['nome']}: {t['positivo']} elogios, {t['negativo']} críticas, {t['neutro']} neutros")
            outros = next((t for t in lista if t["id"] == OUTROS), None)
            if outros and outros["pct"] > 25:
                print(f"  Atenção: {outros['pct']}% ficaram em Outros assuntos. Vale revisar esses temas.")


if __name__ == "__main__":
    main()
