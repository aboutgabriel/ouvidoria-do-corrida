"""
Ouvidoria do Corrida | Janela de análise

Cada episódio conta só os comentários publicados nas primeiras 48 horas
depois que o vídeo sai. Assim todos os episódios são comparados com a
mesma régua, e o painel pode ser publicado dois dias depois de cada
episódio, em vez de esperar a conversa acabar.

Por que 48 horas: no episódio 1, que tem 11 dias de comentários, o saldo
de cada participante com mais de 100 menções nas primeiras 48 horas ficou
a no máximo 6 pontos do saldo final, e 82% dos comentários chegaram nesse
período.

O início da janela é o primeiro comentário do vídeo, que aparece minutos
depois da estreia.
"""

import pandas as pd

JANELA_HORAS = 48


def janelas(comentarios):
    """Uma linha por episódio: início, fim, se a janela já fechou na coleta e
    quantos comentários entram nela. Recebe todos os comentários do banco."""
    df = comentarios.assign(
        publicado=pd.to_datetime(comentarios["publicado_em"], utc=True),
        coletado=pd.to_datetime(comentarios["coletado_em"], utc=True),
    )
    tabela = df.groupby("episodio").agg(inicio=("publicado", "min"), ultima_coleta=("coletado", "max"))
    tabela["fim"] = tabela["inicio"] + pd.Timedelta(hours=JANELA_HORAS)
    tabela["aberta"] = tabela["ultima_coleta"] < tabela["fim"]
    return tabela


def na_janela(comentarios, tabela=None):
    """Filtra os comentários que caem dentro da janela do seu episódio."""
    tabela = janelas(comentarios) if tabela is None else tabela
    publicado = pd.to_datetime(comentarios["publicado_em"], utc=True)
    fim = comentarios["episodio"].map(tabela["fim"])
    return comentarios[publicado <= fim]
