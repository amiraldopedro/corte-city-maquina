"""Testes rápidos (sem vídeo, sem internet): rodam a cada push no GitHub.
Uso: python testes/teste_unidades.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maquina.sincronizar import juntar_estado
from maquina import titulos, cerebro, publicar
from maquina.momentos import _score, score_atual

# 1) junção do estado: listas somam, youtube_id nunca some, status não volta pra trás, cota fica com o maior
l = {"momentos": {"a": {"status": "postado", "youtube_id": "X", "atualizado_em": "2026-01-01T00:00:01", "usado_em": ["dia"]}},
     "cota": {"2026-01-01": 1700}}
r = {"momentos": {"a": {"status": "novo", "atualizado_em": "2026-01-01T00:00:05", "usado_em": ["top10"]},
                  "b": {"status": "novo", "atualizado_em": "2026-01-01"}}, "cota": {"2026-01-01": 3400}}
j = juntar_estado(l, r)
assert j["momentos"]["a"]["status"] == "postado" and j["momentos"]["a"]["youtube_id"] == "X"
assert set(j["momentos"]["a"]["usado_em"]) == {"dia", "top10"} and "b" in j["momentos"]
assert j["cota"]["2026-01-01"] == 3400

# 2) títulos
assert titulos.ruim("...Alanzoka reagindo ao trailer do GTA 6...", "Alanzoka")
assert titulos.ruim("MOUNT GTA RP: O QUE HÁ A VENIR?", "Mount")
assert titulos.ruim("Isso é Mario msm 0.o - Alanzoka", "Alanzoka")
assert not titulos.ruim("Alanzoka tentou fugir da polícia no GTA RP e deu tudo errado", "Alanzoka")
assert titulos.caixa_de_livro("GTA 6: Mapa É O Maior De Todos Os Tempos") == "GTA 6: Mapa é o maior de todos os tempos"

# 3) o corte começa onde a fala que a IA citou começa (não no número chutado)
palavras = [{"p": w, "i": 10 + i * 0.5, "f": 10.4 + i * 0.5} for i, w in enumerate("mano olha a polícia vindo socorro".split())]
assert cerebro._conferir_inicio(8.0, "olha a polícia", palavras, 60, 12) == 9.9

# 4) score: consenso de pessoas diferentes vale mais; momento velho perde força
assert _score(300, 3, 3) > _score(3000, 1, 1)
assert score_atual({"score": 100, "clipado_em": "2020-01-01T00:00:00Z"}) < 1

# 5) publicar: com youtube_id gravado, nunca reenviar
class Est:
    def __init__(self): self.dados = {"momentos": {"m": {"id": "m", "youtube_id": "JA"}}}
    @property
    def momentos(self): return self.dados["momentos"]
class YT:
    def enviar(self, *a, **k): raise AssertionError("reenviou!")
assert publicar.publicar(Est(), "m", YT(), Path("x.mp4"), "t", "d", [], "pt", None, None, log=lambda *_: None) == "JA"

print("OK: testes rápidos")


# ---- nomes de canal viram nome de streamer; títulos sem palavrão e sem final vago na frente
from maquina.config import limpar_nome
assert limpar_nome("Cortes do Davy Jones [OFICIAL]") == "Davy Jones"
assert limpar_nome("BisteconeLive") == "Bistecone" and limpar_nome("CellbitLives") == "Cellbit"
assert limpar_nome("xQc") == "xQc" and limpar_nome("IShowSpeed") == "IShowSpeed" and limpar_nome("alanzoka") == "alanzoka"
assert titulos.ruim("GTA 6: que porra foi essa que aconteceu com o Davy") == "palavrão"
assert not titulos.ruim("GTA 6: o putt de golfe mais difícil de Vice City")  # 'putt' não é palavrão
_t, _ = titulos.escolher("Calango no GTA 6 quis buzinar, pulou do carro e deu nisso",
                         ["Calango no GTA 6 quis buzinar e pulou do carro andando"], "Calango", [])
assert _t.endswith("andando"), _t
assert titulos.limpar_cru("Kkkkkkkkkkkk que porra e ESSA?????????") in ("que e essa", "que e ESSA")
assert "http" not in titulos.limpar_cru("olha o ovni no pântano do GTA 6 https://t.co/abc @fulano")
from maquina.youtube_auto import rodizio
class _F:  # fila de mentira
    dados = {}
_f = _F()
assert rodizio(_f, "x", ["a", "b", "c", "d"], 3) == ["a", "b", "c"] and rodizio(_f, "x", ["a", "b", "c", "d"], 3) == ["d", "a", "b"]
print("ok: nomes, palavrão, final vago e rodízio de temas")
