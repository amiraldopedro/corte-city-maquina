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
from maquina import twitch, youtube, baixar, transcrever
from maquina.config import carregar
from maquina.estado import Estado

class TwitchFalsa:
    def __init__(self, *a): pass
    def usuarios(self, logins): return {l: {"id": "u_" + l} for l in logins}
    def ids_jogos(self, nomes): return {{"Grand Theft Auto V": "32982", "Grand Theft Auto VI": "999", "Just Chatting": "509658", "IRL": "509672"}[n]: n for n in nomes}
    def clipes(self, uid, horas):
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
assert len(ms) == 2, "esperava 2 momentos (moto juntada + react)"
main.fazer_cacada(carregar())                       # rodar de novo não pode duplicar
assert len(Estado("br").momentos) == 2, "duplicou momento na segunda caçada"
print("fila:", main.tem_trabalho(carregar()))
main.produzir(carregar())
est = Estado("br"); post = [m for m in est.momentos.values() if m["status"] == "postado"]
print("enviados:", enviados); print("postados:", [(m["titulo"], m["layout"], m["cerebro"]) for m in post])
assert len(post) == 1 and Path("estado/thumbs").glob("*.jpg"), "não postou"
assert main.postados_hoje(est, cfg.canal("br")) == 1
print("OK: ponta a ponta funcionando")
