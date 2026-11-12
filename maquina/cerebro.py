"""O "cérebro": decide onde cortar, escreve o título e a palavra-gancho da thumb.

Usa o Ollama (IA gratuita que roda dentro do GitHub Actions). Se o Ollama não
responder ou devolver algo sem sentido, cai num plano B com regras simples,
para a máquina nunca parar.
"""
from __future__ import annotations

import json
import random
import re

import requests

from .momentos import ANTES_SEG

PROMPT = """Você é editor de um canal de cortes de GTA no YouTube Shorts.
Streamer: {nome}
Jogo/assunto: {jogo}{evento_txt}
Idioma do canal: {idioma_nome}
O trecho da live tem {duracao:.0f} segundos. Os espectadores fizeram clipes deste momento com estes títulos:
{titulos}

Transcrição com o segundo em que cada fala começa:
{transcricao}

Tarefa:
1. Escolha o melhor corte entre {dmin} e {dmax} segundos que tenha começo (contexto), meio e o momento engraçado/insano. Não corte no meio de uma frase.
2. Escreva um TÍTULO em {idioma_nome}, até 70 caracteres, estilo curiosidade, escrito de forma casual, com o nome do streamer e o nome do jogo ({jogo}). Ex.: "{exemplo}". Sem hashtags. Não invente o que não aconteceu e não diga que é GTA 6 se o jogo não for GTA 6.
3. Escolha uma palavra-gancho para a thumb (1 ou 2 palavras, em maiúsculas, em {idioma_nome}), como "SOCORRO", "NÃO!", "INSANO".
4. Se o trecho não tiver nada interessante (silêncio, loading, conversa sem graça), marque usar=false.

Responda só com JSON neste formato:
{{"usar": true, "inicio": 8.0, "fim": 49.5, "titulo": "...", "gancho": "...", "motivo": "..."}}"""

EXEMPLOS = {
    "pt": "O Coringa achou que tava sozinho no {jogo}... até isso acontecer",
    "en": "Kai Cenat thought he was alone in {jogo}... then this happened",
}
APELIDOS = {"Grand Theft Auto VI": "GTA 6", "Grand Theft Auto V": "GTA RP", "Grand Theft Auto IV": "GTA 4",
            "Grand Theft Auto: San Andreas": "GTA San Andreas", "Red Dead Redemption 2": "Red Dead 2",
            "Just Chatting": "live", "IRL": "live"}


def apelido(jogo: str) -> str:
    return APELIDOS.get(jogo, jogo or "GTA")
IDIOMAS = {"pt": "português do Brasil", "en": "inglês dos EUA"}

MODELOS_TITULO = {
    "pt": ["{nome} não esperava por isso no {jogo}", "O que aconteceu com o {nome} no {jogo} é surreal",
           "{nome} perdeu a cabeça no {jogo}", "Ninguém acreditou no que o {nome} fez no {jogo}"],
    "en": ["{nome} did NOT expect this in {jogo}", "What happened to {nome} in {jogo} is unreal",
           "{nome} lost it in {jogo}", "Nobody believed what {nome} did in {jogo}"],
}
GANCHOS = {"pt": ["INSANO", "SOCORRO", "NÃO!", "KKKKK"], "en": ["NO WAY", "INSANE", "BRO...", "WHAT?!"]}
LIXO = re.compile(r"^[\W_k]*$|^(lol|lmao|kkk+|haha+|clip|clipe)\W*$", re.I)


def _perguntar_ollama(endereco: str, modelo: str, prompt: str) -> dict:
    r = requests.post(f"{endereco}/api/generate", timeout=600, json={
        "model": modelo, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": 0.6, "num_ctx": 4096},
    })
    r.raise_for_status()
    return json.loads(r.json()["response"])


def _limpar_titulo(t: str) -> str:
    t = re.sub(r"#\w+", "", t or "").strip().strip('"').strip()
    return t[:95]


REACT = {"pt": ["{nome} reagindo ao {evento}", "A reação do {nome} ao {evento} 😱", "{nome} viu o {evento} e não acreditou"],
         "en": ["{nome} reacts to {evento}", "{nome}'s reaction to {evento} 😱", "{nome} watched {evento} and lost it"]}


def plano_b(momento: dict, palavras: list[dict], nome: str, idioma: str, dmin: int, dmax: int) -> dict:
    """Sem IA: começa um pouco antes do primeiro clipe e fecha numa pausa da fala."""
    janela = momento["fim"] - momento["inicio"]
    inicio = max(0.0, min(ANTES_SEG - 3, janela - dmin)) if momento.get("video_id") else 0.0
    fim = min(janela, inicio + dmax)
    # termina no fim da palavra mais próxima, para não cortar frase no meio
    fins = [w["f"] for w in palavras if inicio + dmin <= w["f"] <= fim]
    if fins:
        fim = min(fim, fins[-1] + 0.6)
    chat = next((t for t in momento.get("titulos_chat", []) if t and len(t) > 8 and not LIXO.match(t)), "")
    if momento.get("evento"):
        titulo = random.choice(REACT[idioma]).format(nome=nome, evento=momento["evento"])
    else:
        titulo = f"{nome}: {chat}" if chat else random.choice(MODELOS_TITULO[idioma]).format(nome=nome, jogo=apelido(momento.get("jogo", "")))
    return {"usar": True, "inicio": round(inicio, 2), "fim": round(fim, 2), "titulo": _limpar_titulo(titulo),
            "gancho": random.choice(GANCHOS[idioma]), "motivo": "regras (sem IA)", "fonte": "regras"}


def decidir(momento: dict, palavras: list[dict], texto: str, nome: str, idioma: str,
            dmin: int, dmax: int, endereco: str, modelo: str) -> dict:
    janela = momento["fim"] - momento["inicio"]
    if len(palavras) < 4:  # quase ninguém falando: corte por regras mesmo
        return plano_b(momento, palavras, nome, idioma, dmin, dmax)
    prompt = PROMPT.format(
        nome=nome, idioma_nome=IDIOMAS[idioma], duracao=janela, dmin=dmin, dmax=dmax,
        titulos="\n".join(f"- {t}" for t in momento.get("titulos_chat", [])[:8] if t) or "- (sem título)",
        transcricao=texto[:6000], exemplo=EXEMPLOS[idioma].format(jogo=apelido(momento.get("jogo", ""))),
        jogo=apelido(momento.get("jogo", "")),
        evento_txt=(f"\nEste trecho é a REAÇÃO do streamer ao {momento['evento']}. O título deve dizer isso, "
                    f"ex.: \"{nome} reagindo ao {momento['evento']}\" ou parecido, em estilo curiosidade.")
                   if momento.get("evento") else "",
    )
    try:
        r = _perguntar_ollama(endereco, modelo, prompt)
        inicio, fim = float(r.get("inicio", 0)), float(r.get("fim", 0))
        inicio = max(0.0, min(inicio, janela - dmin))
        fim = min(janela, max(fim, inicio + dmin))
        if fim - inicio > dmax:
            fim = inicio + dmax
        titulo = _limpar_titulo(r.get("titulo", ""))
        gancho = str(r.get("gancho", "")).upper().strip()[:16] or random.choice(GANCHOS[idioma])
        if len(titulo) < 12 or nome.split()[0].lower() not in titulo.lower():
            titulo = _limpar_titulo(f"{nome}: {titulo}") if len(titulo) >= 12 else \
                random.choice(MODELOS_TITULO[idioma]).format(nome=nome, jogo=apelido(momento.get("jogo", "")))
        return {"usar": bool(r.get("usar", True)), "inicio": round(inicio, 2), "fim": round(fim, 2),
                "titulo": titulo, "gancho": gancho, "motivo": str(r.get("motivo", ""))[:200], "fonte": "ia"}
    except Exception as e:  # Ollama fora do ar, JSON quebrado etc.
        d = plano_b(momento, palavras, nome, idioma, dmin, dmax)
        d["motivo"] = f"plano B: {str(e)[:120]}"
        return d


def titulo_compilado(idioma: str, tipo: str, nomes: list[str], data: str, evento: str = "") -> str:
    destaque = ", ".join(nomes[:3])
    if tipo == "serie":
        return (f"Streamers reagindo ao {evento} ({destaque})" if idioma == "pt"
                else f"Streamers react to {evento} ({destaque})")[:95]
    if idioma == "pt":
        if tipo == "top10":
            return f"TOP 10 momentos mais insanos de GTA da semana ({destaque})"[:95]
        return f"Os melhores momentos de GTA do dia {data} ({destaque})"[:95]
    if tipo == "top10":
        return f"TOP 10 craziest GTA moments this week ({destaque})"[:95]
    return f"Best GTA moments of {data} ({destaque})"[:95]
