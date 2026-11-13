"""Títulos que dão clique sem parecer robô, e sem repetir o que o canal já postou.

- `ruim(t)`: barra título quebrado (reticências no começo, espanhol, CAIXA ALTA, Título Em Caixa De Livro...).
- `parecido(a, b)`: mede se dois títulos falam da mesma coisa (palavras em comum).
- `recentes(est, dias)`: títulos que o canal postou nos últimos dias.
- `escolher(...)`: pega o melhor entre o título principal e as variantes da IA.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone

ESPANHOL = re.compile(r"\b(venir|pero|muy|cuando|ahora|también|aquí|hay|qué|está aquí|lo que|el nuevo|nuevo|"
                      r"juego|todos los|mejor|increíble|tráiler)\b", re.I)
QUEBRADO = re.compile(r"^\W|\.\.\.$|…$|\?\?|!!|\b(\w+) \1\b", re.I)
PROIBIDAS = re.compile(r"\b(clickbait|short|shorts|vídeo|video|inscreva|subscribe)\b|#", re.I)
PALAVRAS_VAZIAS = set("""a o as os um uma de do da dos das no na nos nas em e é que com por pra para ao à se
seu sua the of in to and is on at for with gta 6 vi rp live ele ela isso esse essa""".split())
# nomes que podem ficar com inicial maiúscula num título normal
PROPRIOS = {"gta", "rp", "vi", "rockstar", "jason", "lucia", "vice", "city", "leonida", "trevor", "michael", "franklin",
            "ps5", "xbox", "pc", "cidade", "alta", "liberty", "san", "andreas", "los", "santos", "brasil", "take-two"}


COMUNS = {"que", "há", "ha", "de", "do", "da", "em", "no", "na", "os", "as", "um", "uma", "ao", "se", "eu", "ele",
          "the", "is", "of", "it"}


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def palavras(t: str) -> set[str]:
    ws = re.findall(r"[a-z0-9]+", _sem_acento(t.lower()))
    return {w[:6] for w in ws if w not in PALAVRAS_VAZIAS and len(w) > 2}


def parecido(a: str, b: str) -> float:
    pa, pb = palavras(a), palavras(b)
    if not pa or not pb:
        return 0.0
    comum = len(pa & pb)
    if comum < 3:  # 1 ou 2 palavras iguais (ex.: "Rockstar", "confirma") não é o mesmo assunto
        return 0.0
    return comum / min(len(pa), len(pb))


def caixa_de_livro(t: str) -> str:
    """'GTA 6: Mapa É O Maior De Todos Os Tempos' -> 'GTA 6: mapa é o maior de todos os tempos'."""
    ws = t.split()
    iniciais = [w for w in ws if w[:1].isalpha()]
    if len(iniciais) < 5 or sum(w[:1].isupper() for w in iniciais) < 0.75 * len(iniciais):
        return t
    saida = []
    for i, w in enumerate(ws):
        limpa = re.sub(r"\W", "", w).lower()
        sigla = w.isupper() and 2 <= len(limpa) <= 4 and limpa not in COMUNS
        if sigla or limpa in PROPRIOS or limpa.isdigit():
            saida.append(w if w.isupper() else w[:1].upper() + w[1:].lower())
        else:
            saida.append(w.lower())
    t = " ".join(saida)
    # primeira letra e a letra depois de ":" maiúsculas
    t = re.sub(r"(^|[:!?]\s+)([a-zà-ú])", lambda m: m.group(1) + m.group(2).upper(), t)
    return t


def ruim(t: str, nome: str = "") -> str:
    """Devolve o motivo se o título for ruim; vazio se estiver bom."""
    if not t or len(t) < 22:
        return "curto demais"
    if len(t) > 95:
        return "longo demais"
    if ESPANHOL.search(t):
        return "espanhol"
    if QUEBRADO.search(t):
        return "quebrado"
    if PROIBIDAS.search(t):
        return "palavra proibida"
    letras = [c for c in t if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) > 0.5 * len(letras):
        return "caixa alta"
    if nome and nome != "*" and nome.split()[0].lower() not in t.lower():
        return "sem o nome do streamer"
    return ""


def recentes(est, dias: int = 7) -> list[str]:
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    saida = []
    for m in est.momentos.values():
        if m.get("status") not in ("pronto", "postado") or not m.get("titulo") or m.get("teste"):
            continue
        quando = m.get("feito_em") or m.get("postado_em") or ""
        try:
            if datetime.fromisoformat(quando.replace("Z", "+00:00")) < limite:
                continue
        except ValueError:
            continue
        saida.append(m["titulo"])
        if m.get("titulo_fonte"):
            saida.append(m["titulo_fonte"])
    return saida


def repetido(t: str, lista: list[str], limite: float = 0.6) -> bool:
    return any(parecido(t, x) >= limite for x in lista)


def escolher(principal: str, extras: list[str], nome: str, ja: list[str]) -> tuple[str, list[str]]:
    """O primeiro título bom e não repetido; se nenhum servir, o menos parecido com o que já saiu."""
    candidatos = [caixa_de_livro(t) for t in [principal, *extras] if t]
    bons = [t for t in candidatos if not ruim(t, nome)]
    novos = [t for t in bons if not repetido(t, ja)]
    if novos:
        escolhido = novos[0]
    elif bons:
        escolhido = min(bons, key=lambda t: max((parecido(t, x) for x in ja), default=0))
    else:
        escolhido = ""
    resto = [t for t in bons if t != escolhido]
    return escolhido, resto
