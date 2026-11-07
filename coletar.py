"""
Ouvidoria do Corrida | Etapa 1: coleta

Baixa os comentários públicos de um episódio no YouTube (API oficial,
YouTube Data API v3) e salva em um banco SQLite local.

Uso:
    python coletar.py --episodio 1 --video https://www.youtube.com/watch?v=XXXXXXXXXXX

Rodar de novo para o mesmo episódio não duplica nada: comentários que já
estão no banco são ignorados e os novos são acrescentados.
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
BANCO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados", "corrida.db")


def extrair_id_video(texto):
    """Aceita o link completo do YouTube ou só o ID do vídeo."""
    padrao = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})", texto)
    if padrao:
        return padrao.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", texto):
        return texto
    raise ValueError(f"Não consegui encontrar o ID do vídeo em: {texto}")


def criar_banco(conexao):
    # Não guardamos o nome de quem comentou: o projeto só publica números agregados.
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS comentarios (
            id            TEXT PRIMARY KEY,
            episodio      INTEGER NOT NULL,
            video_id      TEXT    NOT NULL,
            texto         TEXT    NOT NULL,
            curtidas      INTEGER NOT NULL DEFAULT 0,
            eh_resposta   INTEGER NOT NULL DEFAULT 0,
            publicado_em  TEXT    NOT NULL,
            coletado_em   TEXT    NOT NULL
        )
    """)
    conexao.execute("CREATE INDEX IF NOT EXISTS idx_episodio ON comentarios (episodio)")


def montar_registro(item, episodio, video_id, eh_resposta, agora):
    snippet = item["snippet"]
    return (
        item["id"],
        episodio,
        video_id,
        snippet["textDisplay"],
        snippet.get("likeCount", 0),
        1 if eh_resposta else 0,
        snippet["publishedAt"],
        agora,
    )


def buscar_comentarios(video_id, chave, episodio):
    """Percorre todas as páginas da API (100 comentários por página)."""
    registros = []
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params = {
        "part": "snippet,replies",
        "videoId": video_id,
        "maxResults": 100,
        "textFormat": "plainText",
        "key": chave,
    }

    while True:
        resposta = requests.get(API_URL, params=params, timeout=30)
        if resposta.status_code != 200:
            erro = resposta.json().get("error", {}).get("message", resposta.text)
            raise RuntimeError(f"Erro da API do YouTube ({resposta.status_code}): {erro}")

        dados = resposta.json()
        for thread in dados.get("items", []):
            principal = thread["snippet"]["topLevelComment"]
            registros.append(montar_registro(principal, episodio, video_id, False, agora))
            # A API devolve até 5 respostas por comentário junto com o principal.
            for resposta_item in thread.get("replies", {}).get("comments", []):
                registros.append(montar_registro(resposta_item, episodio, video_id, True, agora))

        print(f"  {len(registros)} comentários lidos até agora...")
        proxima = dados.get("nextPageToken")
        if not proxima:
            break
        params["pageToken"] = proxima

    return registros


def main():
    parser = argparse.ArgumentParser(description="Coleta comentários de um episódio do Corrida das Blogueiras.")
    parser.add_argument("--episodio", type=int, required=True, help="Número do episódio (ex.: 1)")
    parser.add_argument("--video", required=True, help="Link do episódio no YouTube ou ID do vídeo")
    args = parser.parse_args()

    load_dotenv()
    chave = os.getenv("YOUTUBE_API_KEY")
    if not chave or chave == "cole_sua_chave_aqui":
        sys.exit("Configure a YOUTUBE_API_KEY no arquivo .env antes de rodar.")

    video_id = extrair_id_video(args.video)
    print(f"Coletando comentários do episódio {args.episodio} (vídeo {video_id})...")
    registros = buscar_comentarios(video_id, chave, args.episodio)

    os.makedirs(os.path.dirname(BANCO), exist_ok=True)
    with sqlite3.connect(BANCO) as conexao:
        criar_banco(conexao)
        antes = conexao.execute("SELECT COUNT(*) FROM comentarios WHERE episodio = ?", (args.episodio,)).fetchone()[0]
        conexao.executemany("INSERT OR IGNORE INTO comentarios VALUES (?, ?, ?, ?, ?, ?, ?, ?)", registros)
        depois = conexao.execute("SELECT COUNT(*) FROM comentarios WHERE episodio = ?", (args.episodio,)).fetchone()[0]

    print(f"Pronto! {depois - antes} comentários novos salvos. Total do episódio {args.episodio}: {depois}.")


if __name__ == "__main__":
    main()
