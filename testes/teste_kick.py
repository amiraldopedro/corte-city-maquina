"""Kick sem internet: resposta falsa do serviço -> momentos na fila."""
import os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maquina import kick

agora = datetime.now(timezone.utc)
def iso(m): return (agora - timedelta(minutes=m)).isoformat().replace("+00:00", "Z")
resposta = {"data": [
    {"id": "a1", "title": "COMPLEXO PEGOU FOGO", "view_count": 5000, "duration": 40, "video_url": "https://clips.kick.com/a1/playlist.m3u8",
     "category": {"name": "Grand Theft Auto V"}, "vod": {"id": "v1"}, "started_at": iso(100), "created_at": iso(99)},
    {"id": "a2", "title": "kkkk perseguição", "view_count": 900, "duration": 30, "video_url": "https://clips.kick.com/a2/playlist.m3u8",
     "category": {"name": "Grand Theft Auto V"}, "vod": {"id": "v1"}, "started_at": iso(99.6), "created_at": iso(99)},
    {"id": "b1", "title": "reagindo trailer gta 6", "views": 3000, "duration": 50, "clip_url": "https://clips.kick.com/b1/playlist.m3u8",
     "category": {"name": "Just Chatting"}, "vod": {"id": "v2"}, "started_at": iso(300), "created_at": iso(300)},
    {"id": "c1", "title": "jogando fortnite", "view_count": 9000, "duration": 30, "video_url": "https://clips.kick.com/c1/playlist.m3u8",
     "category": {"name": "Fortnite"}, "vod": {"id": "v3"}, "started_at": iso(50), "created_at": iso(50)},
    {"id": "d1", "title": "velho gta", "view_count": 9000, "duration": 30, "video_url": "https://clips.kick.com/d1/playlist.m3u8",
     "category": {"name": "Grand Theft Auto V"}, "vod": {"id": "v4"}, "started_at": iso(60*24*10), "created_at": iso(60*24*10)},
]}

class R:
    status_code = 200
    def json(self): return resposta
    def raise_for_status(self): pass
kick.requests.post = lambda *a, **k: R()
os.environ["KICK_API_KEY"] = "x"

cl = kick.clipes("coringa", 72)
assert len(cl) == 4, cl            # o de 10 dias atrás fica de fora
bons = [c for c in cl if kick.vale(c, ["Grand Theft Auto V", "Grand Theft Auto VI"], ["gta", "trailer"])]
assert {c["id"] for c in bons} == {"kick_a1", "kick_a2", "kick_b1"}, bons
ms = kick.momentos(bons, "coringa", "br", 100)
assert len(ms) == 2, ms             # a1 + a2 viram um momento só
top = max(ms, key=lambda m: m["views"])
assert top["views"] == 5900 and top["clipe_url"].endswith("a1/playlist.m3u8") and top["plataforma"] == "kick"
print("Kick OK:", [(m["id"], m["views"], m["jogo"]) for m in ms])
