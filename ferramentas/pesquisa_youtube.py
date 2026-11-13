"""Pesquisa de performance no YouTube (API oficial): vídeos de GTA 6 que bombaram acima do tamanho do canal.

Uso: python ferramentas/pesquisa_youtube.py "GTA 6" "GTA VI" --dias 30
Salva em estado/pesquisa/<data>.json (o painel e o Claude leem dali).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maquina.youtube import YouTube  # noqa: E402


def segundos(iso: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("termos", nargs="+")
    ap.add_argument("--dias", type=int, default=30)
    a = ap.parse_args()
    yt = YouTube(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN_BR"]).yt
    desde = (datetime.now(timezone.utc) - timedelta(days=a.dias)).isoformat(timespec="seconds").replace("+00:00", "Z")
    ids = {}
    for termo in a.termos:
        for regiao, lingua in (("BR", "pt"), ("US", "en")):
            r = yt.search().list(q=termo, part="id", type="video", order="viewCount", maxResults=50,
                                 publishedAfter=desde, regionCode=regiao, relevanceLanguage=lingua).execute()
            for it in r.get("items", []):
                ids.setdefault(it["id"]["videoId"], f"{termo}/{regiao}")
    videos = []
    lista = list(ids)
    for i in range(0, len(lista), 50):
        r = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(lista[i:i + 50])).execute()
        videos += r.get("items", [])
    canais = {}
    cids = list({v["snippet"]["channelId"] for v in videos})
    for i in range(0, len(cids), 50):
        r = yt.channels().list(part="statistics", id=",".join(cids[i:i + 50])).execute()
        for c in r.get("items", []):
            canais[c["id"]] = int(c["statistics"].get("subscriberCount") or 0)
    saida = []
    for v in videos:
        s, st = v["snippet"], v.get("statistics", {})
        views, inscritos = int(st.get("viewCount") or 0), canais.get(s["channelId"], 0)
        dur = segundos(v["contentDetails"].get("duration"))
        saida.append({
            "id": v["id"], "link": f"https://youtu.be/{v['id']}", "titulo": s["title"], "canal": s["channelTitle"],
            "inscritos": inscritos, "views": views, "likes": int(st.get("likes") or st.get("likeCount") or 0),
            "comentarios": int(st.get("commentCount") or 0), "duracao_s": dur, "formato": "short" if dur <= 70 else "longo",
            "publicado": s["publishedAt"], "idioma": s.get("defaultAudioLanguage") or s.get("defaultLanguage") or "",
            "razao": round(views / max(inscritos, 1000), 2), "busca": ids[v["id"]],
        })
    saida.sort(key=lambda x: -x["razao"])
    pasta = Path("estado/pesquisa")
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"{datetime.now():%Y%m%d}.json"
    arq.write_text(json.dumps({"termos": a.termos, "dias": a.dias, "feito_em": datetime.now(timezone.utc).isoformat(),
                               "videos": saida}, ensure_ascii=False, indent=1))
    longos = [x for x in saida if x["formato"] == "longo"]
    print(f"{len(saida)} vídeos ({len(longos)} longos). Top longos por views/inscritos:")
    for x in longos[:25]:
        print(f"  {x['razao']:>7}x | {x['views']:>10,} views | {x['inscritos']:>9,} insc | {x['duracao_s'] // 60:>3} min | {x['canal'][:22]:22} | {x['titulo'][:80]}")


if __name__ == "__main__":
    main()
