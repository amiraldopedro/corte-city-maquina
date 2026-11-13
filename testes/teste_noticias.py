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
from maquina import xposts
from PIL import Image
Image.new("RGB", (1600, 900), (40, 90, 200)).save(tmp / "foto.jpg")
def baixar_falso(url, destino):
    origem = VIDEO if url.endswith(".mp4") else tmp / "foto.jpg"
    shutil.copy(origem, destino); return Path(destino)
xposts._baixar = baixar_falso
def post(link):
    pid = xposts.id_do_post(link)
    midias = {"1": [{"tipo": "video", "url": "https://v/1.mp4"}], "2": [{"tipo": "foto", "url": "https://p/1.jpg"}, {"tipo": "foto", "url": "https://p/2.jpg"}],
              "3": [], "4": [{"tipo": "foto", "url": "https://p/x.jpg"}], "5": []}[pid]
    return {"id": "x_" + pid, "origem": "x", "link": link, "autor": "Rockstar Games", "perfil": "RockstarGames", "avatar": "https://a/a.jpg",
            "verificado": True, "texto": {"4": "mapa vazado do gta 6", "5": "esse leaker do gta 6 de novo kkkkk ninguém aguenta mais"}.get(pid, "Faltam 6 dias para Grand Theft Auto VI. Pré-carregamento liberado dia 17 de novembro."),
            "idioma": "en" if pid == "3" else "pt", "data": "2026-11-13T12:00:00.000Z", "curtidas": 254000, "sensivel": False, "midias": midias,
            "fonte": "Rockstar Games (@RockstarGames)", "titulo_fonte": ""}
xposts.buscar = post
TITULOS_FALSOS = iter(["Pré-carregamento do GTA 6 liberado no PS5",
                       "GTA 6 bate recorde de pré-venda na PlayStation Store", "Leonida aparece em detalhes no novo vídeo do GTA 6",
                       "Comunidade acha segredo escondido no trailer do GTA 6", "Jason e Lucia ganham pôster novo do GTA 6",
                       "Fãs fazem fila virtual pra jogar GTA 6 à meia-noite", "GTA 6 terá modo foto no lançamento", "GTA 6: a Rockstar confirmou o horário de lançamento"] * 3)
def ia(pr):
    if "Traduza este post" in pr:
        return {"traducao": "Faltam 6 dias para o Grand Theft Auto VI. Pré-carregamento liberado dia 17 de novembro."}
    return {"categoria": "ok", "narracao": "A Rockstar acabou de confirmar uma novidade enorme do GTA 6 e a galera ficou maluca com isso, " * 2 + "E aí, vai comprar no dia?",
            "titulo": next(TITULOS_FALSOS), "chamada": "A ROCKSTAR CONFIRMOU",
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

_cfg = carregar(); _cfg.noticias["por_dia"] = 2  # o teste confere o limite de 2 por dia
main.fazer_noticias(_cfg, [f"https://x.com/RockstarGames/status/{i}" for i in (1, 2, 3, 4, 5)])
ms = Estado("br").momentos
print({k: v["status"] for k, v in ms.items()})
assert "Original (inglês)" in ms["x_3"]["descricao"], "post em inglês não foi traduzido"
assert ms["news_b"]["status"] == "descartado", "vazamento passou!"
assert all(ms[f"x_{i}"]["status"] == "postado" for i in (1, 2, 3)), "post do X não postou"
assert ms["x_4"]["status"] == "descartado", "post com material vazado passou!"
assert ms["x_5"]["status"] == "postado", "meme sobre leaker (sem material) devia passar"
assert "Post original: https://x.com/RockstarGames/status/1" in ms["x_1"]["descricao"]
assert ms["news_a"]["status"] == "postado" and ms["news_c"]["status"] in ("postado", "aguardando_cota")  # 6º envio do dia passa da cota
assert "news_d" not in ms, "passou do limite de 2 notícias por dia"
assert "Fonte: IGN Brasil" in ms["news_a"]["descricao"]
_cfg = carregar(); _cfg.noticias["por_dia"] = 2  # o teste confere o limite de 2 por dia
main.fazer_noticias(_cfg, [])
assert "news_d" not in Estado("br").momentos, "limite do dia não segurou"
print("pasta:", tmp)
print("OK: notícias funcionando")
