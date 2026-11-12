"""Testa a busca da série de reacts com uma Twitch falsa."""
import os, shutil, sys, tempfile
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp()); shutil.copytree(RAIZ, tmp / "repo", ignore=shutil.ignore_patterns(".git", "trabalho"))
os.chdir(tmp / "repo"); sys.path.insert(0, str(tmp / "repo"))
for f in Path("estado").glob("*.json"): f.unlink()
import main
from maquina import twitch
from maquina.config import carregar
from maquina.estado import Estado
class T:
    def __init__(self, *a): pass
    def usuarios(self, logins): return {l: {"id": "u_" + l} for l in logins}
    def ids_jogos(self, nomes): return {"509658": "Just Chatting"}
    def clipes(self, broadcaster_id="", horas=24, maximo=300, game_id="", inicio=None, fim=None):
        assert inicio and fim
        if inicio.year == 2025 and inicio.month == 5 and inicio.day == 6:
            if broadcaster_id == "u_coringa":
                return [{"id": "r1", "title": "CORINGA REAGINDO AO TRAILER 2 DO GTA 6", "video_id": "V1", "vod_offset": 100,
                         "duration": 40, "view_count": 50000, "url": "https://clips/r1", "broadcaster_name": "Coringa"}]
            if game_id:
                return [{"id": "r2", "title": "a lucia é linda kkk", "video_id": "V2", "vod_offset": 10, "duration": 30,
                         "view_count": 9000, "url": "https://clips/r2", "broadcaster_name": "Casimiro", "language": "pt"},
                        {"id": "r3", "title": "gta 6 trailer reaction", "video_id": "V3", "vod_offset": 10, "duration": 30,
                         "view_count": 90000, "url": "https://clips/r3", "broadcaster_name": "Kai", "language": "en"},
                        {"id": "r4", "title": "almoço", "video_id": "V4", "vod_offset": 10, "duration": 30,
                         "view_count": 9000, "url": "https://clips/r4", "broadcaster_name": "X", "language": "pt"}]
        return []
twitch.Twitch = T
os.environ.update(TWITCH_CLIENT_ID="x", TWITCH_CLIENT_SECRET="x")
main.buscar_series(carregar())
ms = list(Estado("br").momentos.values())
print([(m["streamer"], m["evento"], m["video_id"], m["titulos_chat"]) for m in ms])
assert {m["streamer"] for m in ms} == {"coringa", "casimiro"}, "deveria pegar Coringa (lista) e Casimiro (descoberta pt), ignorar gringo e clipe sem palavra"
assert all(m["evento"] == "Trailer 2 do GTA 6" and m["video_id"] is None for m in ms)
main.buscar_series(carregar()); assert len(Estado("br").momentos) == 2, "duplicou"
from maquina.cerebro import plano_b
print(plano_b(ms[0], [], "Coringa", "pt", 15, 58)["titulo"])
print("OK: série de reacts funcionando")
