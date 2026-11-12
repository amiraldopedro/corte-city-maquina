"""Transforma clipes do público em "momentos".

Ideia: quando várias pessoas clipam o mesmo trecho da live, ali tem coisa boa.
Agrupamos clipes da mesma VOD cujo início está a menos de JUNTAR_SEG um do outro,
e somamos as views. Cada grupo vira um momento com uma janela de vídeo real
(um pouco antes e depois) que será baixada direto da VOD, em qualidade máxima.
"""
from __future__ import annotations

import math

JUNTAR_SEG = 40     # clipes com início até 40s de distância = mesmo momento
ANTES_SEG = 10      # contexto antes do primeiro clipe (o setup da piada)
DEPOIS_SEG = 6      # sobra depois do último clipe
JANELA_MAX = 95     # janela bruta máxima baixada (a IA recorta depois)


def _score(views: int, n: int) -> float:
    # vários clipeiros diferentes valem mais que um clipe com muita view
    return views * (1 + 0.6 * (n - 1)) + 150 * math.log1p(n)


def agrupar(clipes: list[dict], jogos_ok: dict[str, str], streamer: str, canal: str,
            minimo_clipes: int, minimo_views: int) -> list[dict]:
    com_vod: dict[str, list[dict]] = {}
    sem_vod: list[dict] = []

    for c in clipes:
        if jogos_ok and c.get("game_id") not in jogos_ok:
            continue
        if c.get("video_id") and c.get("vod_offset") is not None:
            com_vod.setdefault(c["video_id"], []).append(c)
        else:
            sem_vod.append(c)

    momentos = []

    for video_id, lista in com_vod.items():
        lista.sort(key=lambda c: c["vod_offset"])
        grupo: list[dict] = []
        for c in lista:
            if grupo and c["vod_offset"] - grupo[-1]["vod_offset"] > JUNTAR_SEG:
                momentos.append(_fechar(grupo, video_id, streamer, canal))
                grupo = []
            grupo.append(c)
        if grupo:
            momentos.append(_fechar(grupo, video_id, streamer, canal))

    # VOD apagada/desligada: usa o próprio clipe (máx. 60s, qualidade do clipe)
    for c in sem_vod:
        momentos.append({
            "id": f"clip_{c['id']}",
            "streamer": streamer, "canal": canal,
            "video_id": None, "inicio": 0.0, "fim": float(c.get("duration", 30)),
            "clipe_url": c["url"], "clipe_ids": [c["id"]],
            "titulos_chat": [c.get("title", "")],
            "views": c.get("view_count", 0), "n_clipes": 1,
            "score": _score(c.get("view_count", 0), 1) * 0.7,  # penaliza: sem contexto
        })

    return [m for m in momentos
            if m["n_clipes"] >= minimo_clipes or m["views"] >= minimo_views * 3
            if m["views"] >= minimo_views]


def _fechar(grupo: list[dict], video_id: str, streamer: str, canal: str) -> dict:
    inicio = max(0.0, min(c["vod_offset"] for c in grupo) - ANTES_SEG)
    fim = max(c["vod_offset"] + float(c.get("duration", 30)) for c in grupo) + DEPOIS_SEG
    if fim - inicio > JANELA_MAX:
        # centraliza no clipe mais visto
        top = max(grupo, key=lambda c: c.get("view_count", 0))
        centro = top["vod_offset"] + float(top.get("duration", 30)) / 2
        inicio = max(0.0, centro - JANELA_MAX / 2)
        fim = inicio + JANELA_MAX
    views = sum(c.get("view_count", 0) for c in grupo)
    titulos = sorted(grupo, key=lambda c: -c.get("view_count", 0))
    return {
        "id": f"{video_id}_{int(inicio)}",
        "streamer": streamer, "canal": canal,
        "video_id": video_id, "inicio": float(inicio), "fim": float(fim),
        "clipe_url": titulos[0]["url"],
        "clipe_ids": [c["id"] for c in grupo],
        "titulos_chat": [c.get("title", "") for c in titulos[:8]],
        "views": views, "n_clipes": len(grupo),
        "score": _score(views, len(grupo)),
    }
