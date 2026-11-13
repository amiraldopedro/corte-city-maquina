"""Confere no YouTube se os vídeos que a máquina postou estão públicos, agendados ou travados no privado."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maquina.youtube import YouTube

est = json.loads(Path("estado/br.json").read_text())
ms = [m for m in est["momentos"].values() if m.get("youtube_id") and not m.get("teste")]
yt = YouTube(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN_BR"]).yt
ids = [m["youtube_id"] for m in ms]
info = {}
for i in range(0, len(ids), 50):
    r = yt.videos().list(part="status,statistics", id=",".join(ids[i:i + 50])).execute()
    for v in r.get("items", []):
        info[v["id"]] = v
resumo = {}
for m in sorted(ms, key=lambda x: x.get("publicar_em") or ""):
    v = info.get(m["youtube_id"])
    if not v:
        estado = "NÃO EXISTE MAIS"
    else:
        s = v["status"]
        estado = s["privacyStatus"] + (f" (agendado {s['publishAt']})" if s.get("publishAt") else "")
        if s.get("uploadStatus") == "rejected":
            estado += f" REJEITADO: {s.get('rejectionReason')}"
    resumo[estado.split()[0]] = resumo.get(estado.split()[0], 0) + 1
    views = (v or {}).get("statistics", {}).get("viewCount", "-")
    print(f"{estado:45} | {views:>7} views | {(m.get('publicar_em') or '')[:16]} | {(m.get('titulo') or '')[:60]}")
print("RESUMO:", resumo)
