"""Notícias sem internet: Google Notícias, X, IA, voz e YouTube falsos."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp()); shutil.copytree(RAIZ, tmp / "repo", ignore=shutil.ignore_patterns(".git", "trabalho"))
os.chdir(tmp / "repo"); sys.path.insert(0, str(tmp / "repo"))
for f in Path("estado").glob("*.json"): f.unlink()
VIDEO = Path(sys.argv[1]).resolve()
import main
from maquina import noticias, cerebro, entrega, youtube
from maquina.config import carregar
from maquina.estado import Estado

noticias.google_noticias = lambda termos, idioma="pt", horas=30: [
    {"id": "news_a", "origem": "noticia", "titulo_fonte": "Rockstar confirma horário de lançamento do GTA 6", "fonte": "IGN Brasil", "link": "https://ign/x", "publicado": ""},
    {"id": "news_b", "origem": "noticia", "titulo_fonte": "Vazamento mostra mapa inteiro de GTA 6", "fonte": "Site X", "link": "https://x", "publicado": ""},
    {"id": "news_c", "origem": "noticia", "titulo_fonte": "GTA 6 terá pré-carregamento dia 17", "fonte": "The Enemy", "link": "https://te/x", "publicado": ""},
    {"id": "news_d", "origem": "noticia", "titulo_fonte": "GTA 6: modo foto confirmado", "fonte": "Eurogamer", "link": "https://eu/x", "publicado": ""}]
noticias.post_do_x = lambda link: {"id": "news_x1", "origem": "x", "titulo_fonte": "GTA 6 chega em 7 dias!", "fonte": "Rockstar Games (@RockstarGames)", "link": link}
def ia(pr):
    return {"seguro": True, "narracao": "A Rockstar acabou de confirmar uma novidade enorme do GTA 6 e a galera ficou maluca com isso, " * 2 + "E aí, vai comprar no dia?",
            "titulo": "GTA 6: a Rockstar confirmou o que todo mundo esperava", "chamada": "A ROCKSTAR CONFIRMOU",
            "manchete": "Rockstar confirma novidade do GTA 6", "tags": ["gta 6 lançamento"]}
cerebro._perguntar_ollama = lambda e, m, pr: ia(pr)
def narrar(texto, idioma, destino):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300", "-t", "12", str(destino)], check=True)
    return [{"p": w, "i": i * .4, "f": i * .4 + .35} for i, w in enumerate(texto.split()[:28])]
noticias.narrar = narrar
def fundo(cfg, pasta, baixar):
    d = pasta / "fundo_teste.mp4"; shutil.copy(VIDEO, d); return d
main.fundo_gameplay = fundo
enviados = []
entrega.entregar = lambda v, c, i: {"video_url": f"https://dl/{i}.mp4", "thumb_url": f"https://dl/{i}.jpg"}
class YT:
    def __init__(self, *a): pass
    def enviar(self, *a, **k): enviados.append(a[1]); return f"YT{len(enviados)}"
    def por_na_playlist(self, *a): pass
youtube.YouTube = YT
os.environ.update(TWITCH_CLIENT_ID="x", TWITCH_CLIENT_SECRET="x", YT_CLIENT_ID="x", YT_CLIENT_SECRET="x", YT_REFRESH_TOKEN_BR="x")

main.fazer_noticias(carregar(), ["https://x.com/RockstarGames/status/123"])
ms = Estado("br").momentos
print({k: v["status"] for k, v in ms.items()})
assert ms["news_b"]["status"] == "descartado", "vazamento passou!"
assert ms["news_x1"]["status"] == "postado" and ms["news_a"]["status"] == "postado" and ms["news_c"]["status"] == "postado"
assert "news_d" not in ms, "passou do limite de 2 notícias por dia"
assert "Fonte: IGN Brasil" in ms["news_a"]["descricao"]
main.fazer_noticias(carregar(), [])
assert "news_d" not in Estado("br").momentos, "limite do dia não segurou"
print("pasta:", tmp)
print("OK: notícias funcionando")
