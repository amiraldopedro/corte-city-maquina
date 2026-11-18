"""Robô automático: todo dia a máquina procura sozinha os vídeos de GTA mais vistos do YouTube BR
(reacts, gameplay, lives) e põe na fila do robô do Mac, sem você colar link.

- Busca na API oficial do YouTube (custa ~100 unidades de cota por termo; a máquina desconta da cota do dia).
- Filtra: português, publicado nos últimos dias, entre 4 min e 4 h, com muita view, sem canal oficial
  (trailer puro da Rockstar não vira corte: só música e Content ID).
- React tem a música do trailer no fundo: os cortes desses vídeos saem com a voz isolada.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .estado import Estado
from .youtube_fonte import fila, pedir

OFICIAIS = re.compile(r"rockstar|take.?two|playstation|xbox|ign\b", re.I)


def _segundos(iso: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def buscar(yt, conf: dict, ja: set[str]) -> list[dict]:
    dias = int(conf.get("dias", 30))
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds").replace("+00:00", "Z")
    ids = []
    for termo in conf.get("termos", ["GTA 6 react", "reagindo trailer GTA 6"]):
        r = yt.search().list(q=termo, part="id", type="video", order="viewCount", maxResults=25,
                             publishedAfter=desde, regionCode="BR", relevanceLanguage="pt",
                             videoDuration="any").execute()
        ids += [it["id"]["videoId"] for it in r.get("items", []) if it["id"]["videoId"] not in ja]
    ids = list(dict.fromkeys(ids))
    videos = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        videos += r.get("items", [])
    bons = []
    for v in videos:
        s, st = v["snippet"], v.get("statistics", {})
        dur = _segundos(v["contentDetails"].get("duration"))
        views = int(st.get("viewCount") or 0)
        lingua = (s.get("defaultAudioLanguage") or s.get("defaultLanguage") or "pt")[:2]
        if OFICIAIS.search(s.get("channelTitle", "")) or lingua not in ("pt", ""):
            continue
        if not (240 <= dur <= 4 * 3600) or views < int(conf.get("min_views", 50000)):
            continue
        if not re.search(r"gta|grand theft", s.get("title", ""), re.I):
            continue
        bons.append({"id": v["id"], "titulo": s["title"], "canal": s["channelTitle"], "views": views, "duracao": dur,
                     "react": bool(re.search(r"react|reag|trailer", s["title"], re.I))})
    bons.sort(key=lambda x: -x["views"])
    return bons


def buscar_lives(yt, conf: dict, ja: set[str]) -> list[dict]:
    """Lives de GTA 6 que acabaram de terminar, de QUALQUER canal BR (não só os streamers da lista).
    O robô do Mac acha os melhores trechos sozinho (gráfico de mais repetidos + picos de volume)."""
    lv = conf.get("lives") or {}
    desde = (datetime.now(timezone.utc) - timedelta(hours=int(lv.get("horas", 48)))).isoformat(timespec="seconds").replace("+00:00", "Z")
    ids = []
    for termo in lv.get("termos", ["GTA 6"]):
        r = yt.search().list(q=termo, part="id", type="video", eventType="completed", order="viewCount",
                             maxResults=25, publishedAfter=desde, regionCode="BR",
                             relevanceLanguage="pt").execute()
        ids += [it["id"]["videoId"] for it in r.get("items", []) if it["id"]["videoId"] not in ja]
    ids = list(dict.fromkeys(ids))
    videos = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,statistics,contentDetails,liveStreamingDetails",
                             id=",".join(ids[i:i + 50])).execute()
        videos += r.get("items", [])
    bons = []
    for v in videos:
        s, st = v["snippet"], v.get("statistics", {})
        live = v.get("liveStreamingDetails") or {}
        dur = _segundos(v["contentDetails"].get("duration"))
        views = int(st.get("viewCount") or 0)
        lingua = (s.get("defaultAudioLanguage") or s.get("defaultLanguage") or "pt")[:2]
        if not live.get("actualEndTime"):   # ainda no ar (ou nunca foi live): o download travaria
            continue
        if OFICIAIS.search(s.get("channelTitle", "")) or lingua not in ("pt", ""):
            continue
        if not (1200 <= dur <= 12 * 3600) or views < int(lv.get("min_views", 20000)):
            continue
        if not re.search(r"gta|grand theft", s.get("title", ""), re.I):
            continue
        bons.append({"id": v["id"], "titulo": s["title"], "canal": s["channelTitle"], "views": views,
                     "duracao": dur, "react": False})
    bons.sort(key=lambda x: -x["views"])
    return bons


def rodar(cfg) -> int:
    """Põe os melhores vídeos novos do dia na fila do robô do Mac. Devolve quantos entraram."""
    conf = cfg.youtube_auto
    if not conf or not conf.get("ligado", True):
        print("  robô automático do YouTube desligado no config.yaml")
        return 0
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None)
    if not canal or not canal.refresh_token:
        print("  sem chave do YouTube do canal: não dá pra pesquisar")
        return 0
    from .publicar import _gastar, tem_cota
    est_canal = Estado(canal.id)
    if not tem_cota(est_canal, envios=2):  # guarda cota pros envios de vídeo, que importam mais
        print("  cota do YouTube apertada hoje: pesquisa fica pra amanhã")
        return 0
    from .youtube import YouTube
    yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token).yt
    est_fila = fila()
    ja = set(est_fila.momentos)
    hoje = datetime.now(timezone.utc).date().isoformat()
    total = 0

    # ---- vídeos/reacts de GTA mais vistos ----
    feitos_hoje = sum(1 for m in est_fila.momentos.values() if m.get("auto") and not m.get("origem")
                      and (m.get("pedido_em") or "")[:10] == hoje)
    vagas = int(conf.get("por_dia", 2)) - feitos_hoje
    if vagas <= 0:
        print("  reacts: o robô automático já pegou os de hoje")
    else:
        bons = buscar(yt, conf, ja)
        _gastar(est_canal, 100 * len(conf.get("termos", [1, 1])) + 2)
        est_canal.salvar()
        escolhidos = bons[:vagas]
        if escolhidos:
            pedir([f"https://www.youtube.com/watch?v={v['id']}" for v in escolhidos])
            est_fila = fila()
            for v in escolhidos:
                if v["id"] in est_fila.momentos:
                    est_fila.momentos[v["id"]].update(auto=True, titulo=v["titulo"], canal_nome=v["canal"],
                                                      isolar_voz=v["react"], views_yt=v["views"])
                    print(f"  🤖 {v['titulo'][:70]} ({v['canal']}, {v['views']:,} views)")
            est_fila.salvar()
            total += len(escolhidos)
        else:
            print("  reacts: nenhum vídeo novo de GTA passou no filtro agora")

    # ---- lives encerradas de GTA 6 (qualquer canal BR) ----
    lv = conf.get("lives") or {}
    if lv.get("ligado", True):
        feitas_hoje = sum(1 for m in est_fila.momentos.values()
                          if m.get("origem") == "live" and (m.get("pedido_em") or "")[:10] == hoje)
        vagas_lives = int(lv.get("por_dia", 3)) - feitas_hoje
        if vagas_lives > 0 and tem_cota(est_canal, envios=2):
            lives = buscar_lives(yt, conf, set(est_fila.momentos))
            _gastar(est_canal, 100 * len(lv.get("termos", [1])) + 2)
            est_canal.salvar()
            escolhidas = lives[:vagas_lives]
            if escolhidas:
                pedir([f"https://www.youtube.com/watch?v={v['id']}" for v in escolhidas])
                est_fila = fila()
                for v in escolhidas:
                    if v["id"] in est_fila.momentos:
                        est_fila.momentos[v["id"]].update(auto=True, origem="live", titulo=v["titulo"],
                                                          canal_nome=v["canal"], views_yt=v["views"])
                        print(f"  📡 live: {v['titulo'][:66]} ({v['canal']}, {v['views']:,} views, {v['duracao'] // 3600}h{v['duracao'] % 3600 // 60:02d})")
                est_fila.salvar()
                total += len(escolhidas)
            else:
                print("  nenhuma live encerrada de GTA 6 passou no filtro agora")

    # ---- lives de GTA dos gringos no YouTube (Speed etc.): viram cortes legendados ----
    try:
        total += lives_gringos(yt, canal, est_canal, est_fila, hoje)
    except Exception as e:
        print(f"  gringos no YouTube: falhou agora ({str(e)[:120]})")
    return total


def lives_gringos(yt, canal, est_canal, est_fila, hoje: str) -> int:
    """Lives encerradas de GTA dos canais gringos da lista (ex.: @IShowSpeed). O robô do Mac acha os picos
    (gráfico de mais repetidos) e a máquina faz o corte com o áudio original + legenda em português."""
    from .publicar import _gastar, tem_cota
    g = canal.gringos or {}
    handles = g.get("youtube") or []
    if not g.get("ligado", True) or not handles or not tem_cota(est_canal, envios=2):
        return 0
    feitas = sum(1 for m in est_fila.momentos.values() if m.get("origem") == "gringo" and (m.get("pedido_em") or "")[:10] == hoje)
    if feitas >= 2:  # live de gringo rende vários cortes: 2 lives por dia já enchem o quadro
        return 0
    cache = est_canal.dados.setdefault("canais_yt", {})
    desde = (datetime.now(timezone.utc) - timedelta(hours=36)).isoformat(timespec="seconds").replace("+00:00", "Z")
    achadas = []
    for h in handles:
        cid = cache.get(h)
        if not cid:
            r = yt.channels().list(part="id", forHandle=h.lstrip("@")).execute()
            cid = (r.get("items") or [{}])[0].get("id")
            if not cid:
                print(f"  gringos: canal {h} não encontrado")
                continue
            cache[h] = cid
        r = yt.search().list(channelId=cid, part="id", type="video", eventType="completed", order="date",
                             maxResults=5, publishedAfter=desde).execute()
        _gastar(est_canal, 101)
        ids = [it["id"]["videoId"] for it in r.get("items", []) if it["id"]["videoId"] not in est_fila.momentos]
        if not ids:
            continue
        info = yt.videos().list(part="snippet,statistics,liveStreamingDetails", id=",".join(ids)).execute()
        for v in info.get("items", []):
            sn = v["snippet"]
            if not (v.get("liveStreamingDetails") or {}).get("actualEndTime"):
                continue
            if not re.search(r"gta|grand theft|vice city|leonida", sn.get("title", ""), re.I):
                continue
            achadas.append({"id": v["id"], "titulo": sn["title"], "canal": sn["channelTitle"], "handle": h.lstrip("@"),
                            "views": int(v.get("statistics", {}).get("viewCount") or 0)})
    est_canal.salvar()
    achadas = sorted(achadas, key=lambda x: -x["views"])[: 2 - feitas]
    if not achadas:
        return 0
    pedir([f"https://www.youtube.com/watch?v={v['id']}" for v in achadas])
    f2 = fila()
    for v in achadas:
        if v["id"] in f2.momentos:
            f2.momentos[v["id"]].update(auto=True, origem="gringo", gringo=True, titulo=v["titulo"], canal_nome=v["canal"],
                                        canal_handle=v["handle"], views_yt=v["views"], isolar_voz=False)
            print(f"  🌎 gringo: {v['titulo'][:66]} ({v['canal']}, {v['views']:,} views)")
    f2.salvar()
    return len(achadas)
