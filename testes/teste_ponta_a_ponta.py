"""Roda a máquina inteira sem internet: Twitch, download, transcrição e YouTube são falsos.
Uso: python testes/teste_ponta_a_ponta.py VIDEO_DE_TESTE.mp4"""
import os, shutil, sys, tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
shutil.copytree(RAIZ, tmp / "repo", ignore=shutil.ignore_patterns(".git", "trabalho"))
os.chdir(tmp / "repo"); sys.path.insert(0, str(tmp / "repo"))
for f in Path("estado").glob("*.json"): f.unlink()
VIDEO = Path(sys.argv[1]).resolve()

import main
from maquina import twitch, youtube, baixar, transcrever, entrega
from maquina.config import carregar
from maquina.estado import Estado

class TwitchFalsa:
    def __init__(self, *a): pass
    def usuarios(self, logins): return {l: {"id": "u_" + l} for l in logins}
    def ids_jogos(self, nomes):
        ids = {"Grand Theft Auto V": "32982", "Grand Theft Auto VI": "999", "Just Chatting": "509658", "IRL": "509672"}
        return {ids[n]: n for n in nomes if n in ids}
    def clipes(self, broadcaster_id="", horas=24, maximo=300, game_id=""):
        if game_id == "32982":   # descoberta por jogo: 2 clipes BR de um streamer fora da lista, 1 gringo (fora)
            return [{"id": "g1", "game_id": "32982", "title": "fuga insana no RP", "video_id": "VOD9", "vod_offset": 500,
                     "duration": 25, "view_count": 2000, "url": "https://clips/g1", "language": "pt", "broadcaster_name": "Cellbit"},
                    {"id": "g2", "game_id": "32982", "title": "en clip", "video_id": "VOD8", "vod_offset": 50,
                     "duration": 25, "view_count": 9000, "url": "https://clips/g2", "language": "en", "broadcaster_name": "Gringo"}]
        if game_id: return []
        uid = broadcaster_id
        if uid != "u_cerol": return []
        c = lambda i, g, t, off, v: {"id": f"c{i}", "game_id": g, "title": t, "video_id": "VOD1", "vod_offset": off,
                                     "duration": 20, "view_count": v, "url": f"https://clips/{i}"}
        return [c(1, "32982", "fuga de moto", 100, 400), c(2, "32982", "kkkkk a moto", 110, 300),   # mesmo momento
                c(3, "509658", "reagindo ao trailer do GTA 6", 5000, 900),                          # react válido
                c(4, "509658", "ele riu muito", 9000, 5000),                                         # conversa: fora
                c(5, "27471", "minecraft", 300, 9999)]                                               # outro jogo: fora

enviados = []
class YouTubeFalso:
    def __init__(self, *a): pass
    def enviar(self, video, titulo, descricao, tags, idioma, publicar_em, thumb=None):
        assert Path(video).exists() and Path(thumb).exists(); enviados.append(titulo); return f"YT{len(enviados)}"
    def por_na_playlist(self, vid, nome): pass

twitch.Twitch = TwitchFalsa
def entregar_falso(video, capa, mid):
    assert Path(video).exists() and Path(capa).exists(); enviados.append(mid)
    return {"video_url": f"https://dl/{mid}.mp4", "video_asset": 1, "thumb_url": f"https://dl/{mid}.jpg", "thumb_asset": 2}
entrega.entregar = entregar_falso
youtube.YouTube = YouTubeFalso
def baixar_falso(m):
    destino = Path("trabalho/brutos") / f"{m['id']}.mp4"; destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(VIDEO, destino); return destino
main_baixar = baixar.baixar_momento = baixar_falso
transcrever.transcrever = lambda arq, idioma, modelo: [{"p": w, "i": 4 + i * .5, "f": 4.4 + i * .5} for i, w in
                                                      enumerate("mano olha isso o cara caiu da moto socorro kkkk".split())]
os.environ.update(TWITCH_CLIENT_ID="x", TWITCH_CLIENT_SECRET="x", YT_CLIENT_ID="x", YT_CLIENT_SECRET="x", YT_REFRESH_TOKEN_BR="x")

cfg = carregar()
main.fazer_cacada(cfg)
est = Estado("br"); ms = list(est.momentos.values())
print("momentos:", [(m["id"], m["n_clipes"], m["titulos_chat"]) for m in ms])
assert len(ms) == 3, "esperava 3 momentos (moto juntada + react + descoberta Cellbit)"
assert any(m.get("descoberto") and m["streamer"] == "cellbit" for m in ms), "descoberta por jogo falhou"
main.fazer_cacada(carregar())                       # rodar de novo não pode duplicar
assert len(Estado("br").momentos) == 3, "duplicou momento na segunda caçada"
print("fila:", main.tem_trabalho(carregar()))
main.produzir(carregar())
est = Estado("br"); post = [m for m in est.momentos.values() if m["status"] in ("pronto", "postado")]
print("entregues/enviados:", enviados); print("feitos:", [(m["status"], m["titulo"], m.get("youtube_id"), m.get("publicar_em"), m["video_url"]) for m in post])
assert len(post) == 1 and list(Path("estado/thumbs").glob("*.jpg")), "não ficou pronto"
assert post[0]["jogo"] == "Grand Theft Auto V"
assert post[0]["status"] == "postado" and post[0]["publicar_em"] and post[0]["video_url"], "automático deveria agendar e guardar reserva"
assert main.postados_hoje(est, cfg.canal("br")) == 1
print("OK: ponta a ponta funcionando")
