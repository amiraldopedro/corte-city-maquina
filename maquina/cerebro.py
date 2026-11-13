"""O "cérebro": decide onde cortar, escreve o título e a palavra-gancho da thumb.

Usa o Ollama (IA gratuita que roda dentro do GitHub Actions). Se o Ollama não
responder ou devolver algo sem sentido, cai num plano B com regras simples,
para a máquina nunca parar.
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import random
import re

import requests

from .momentos import ANTES_SEG

PROMPT = """Você é editor de um canal de cortes de GTA no YouTube Shorts. O canal é sobre o GTA 6: cortes das lives de quem joga e fala de GTA, sempre com o GTA 6 como tema.
Streamer: {nome}
Jogo/assunto: {jogo}{evento_txt}
Idioma do canal: {idioma_nome}
O trecho da live tem {duracao:.0f} segundos. Os espectadores fizeram clipes deste momento com estes títulos:
{titulos}

Transcrição com o segundo em que cada fala começa:
{transcricao}

Tarefa:
1. Escolha o corte entre {dmin} e {dmax} segundos (o ideal é de 15 a 30). Regras de corte de Short viral:
   - Comece 1 a 2 segundos ANTES da ação ou da fala que importa. Nada de silêncio, "oi chat" ou enrolação no começo.
   - Se precisar de contexto, use só o mínimo para entender (uma frase), não a história toda.
   - Termine logo depois da reação/risada/desfecho, sem deixar o vídeo morrer no final.
   - Não corte no meio de uma frase.
2. Escreva o TÍTULO em {idioma_nome} seguindo as regras de SEO abaixo. Ex.: "{exemplo}".
3. Escreva a CHAMADA: 3 a 6 palavras que aparecem escritas na tela nos 3 primeiros segundos, para a pessoa parar de rolar o feed (ex.: "ELE NÃO ESPERAVA ISSO", "OLHA O QUE ELE FEZ"). Sem repetir o título inteiro.
4. Escolha uma palavra-gancho para a thumb (1 ou 2 palavras, em maiúsculas, em {idioma_nome}), como "SOCORRO", "NÃO!", "INSANO".
5. Escreva a DESCRIÇÃO: 2 frases curtas em {idioma_nome} contando o que acontece, usando naturalmente as palavras que as pessoas buscam (nome do streamer, {jogo}, e termos como "cortes", "momentos engraçados", "reação").
6b. Escreva 4 TÍTULOS ALTERNATIVOS ("titulos_extra"), cada um com um ângulo diferente (curiosidade, humor, choque, pergunta), seguindo as mesmas regras.
6. Escreva 8 a 12 TAGS (palavras que a pessoa digitaria na busca do YouTube), do mais específico ao mais geral.
7. Dê uma NOTA de 0 a 10 para o potencial viral (engraçado, surpreendente, dá para entender sem contexto, tem desfecho).
8. Marque usar=false SÓ se não tiver nada aproveitável (silêncio, tela de loading). Momento fraco vira Short mesmo assim: capriche no título e na chamada.

{seo}

Responda só com JSON neste formato:
{{"usar": true, "nota": 7, "inicio": 8.0, "fim": 31.5, "titulo": "...", "chamada": "...", "gancho": "...", "descricao": "...", "tags": ["...", "..."], "titulos_extra": ["...", "..."], "motivo": "..."}}"""

SEO = {
    "pt": """REGRAS DE SEO DO YOUTUBE (siga todas):
- Título com 45 a 65 caracteres. A palavra que as pessoas buscam vem no começo: o nome do streamer e o jogo (ex.: "Coringa no GTA RP", "Alanzoka reagindo ao trailer do GTA 6").
- Depois, uma curiosidade que só se resolve assistindo ("...até isso acontecer", "...e ninguém esperava"). Gera clique sem mentir.
- Escreva como brasileiro fala: casual, direto. No máximo 1 emoji e só no fim. Nada de título todo em maiúsculas; no máximo 1 palavra em maiúsculas.
- Proibido: hashtag no título, mentir, prometer o que não acontece, dizer que é GTA 6 quando o jogo é GTA 5/RP, palavras como "clickbait", "vídeo", "short".
- O canal é sobre o GTA 6. Se o momento for de GTA 5/RP, você PODE ligar ao GTA 6 de forma verdadeira de vez em quando (ex.: "...enquanto o GTA 6 não chega", "treinando pro GTA 6"), mas sem repetir isso em todo título.
- Termos que o público brasileiro busca: "GTA RP", "cortes", "cidade alta", "complexo", "GTA 6", "trailer do GTA 6", "reagindo", nome do streamer.
- Tags: comece pelo nome do streamer + jogo, depois o jogo, depois o assunto do momento (ex.: "fuga da polícia gta rp"), por fim termos gerais ("cortes gta", "gta rp brasil").""",
    "en": """YOUTUBE SEO RULES (follow all):
- Title 45 to 65 characters. Searched words first: streamer name and game (e.g., "Kai Cenat in GTA RP").
- Then a curiosity gap only solved by watching ("...then this happened"). Click without lying.
- Casual tone. At most 1 emoji, at the end. Never all caps; at most 1 word in caps.
- Forbidden: hashtags in title, lying, calling it GTA 6 when it's GTA 5/RP, the words "clickbait", "video", "short".
- The channel is about GTA 6. For GTA 5/RP moments you MAY truthfully tie it to GTA 6 now and then ("...while we wait for GTA 6"), not in every title.
- Terms people search: "GTA RP", "GTA 6", "GTA 6 trailer", "reacts", "funny moments", streamer name.
- Tags: streamer + game first, then game, then the moment's topic, then general terms.""",
}

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
CHAMADAS = {"pt": ["ELE NÃO ESPERAVA ISSO", "OLHA O QUE ACONTECEU", "ESPERA O FINAL", "NINGUÉM ACREDITOU"],
            "en": ["HE DID NOT EXPECT THIS", "WAIT FOR IT", "WATCH TILL THE END", "NOBODY SAW THIS COMING"]}
GANCHOS = {"pt": ["INSANO", "SOCORRO", "NÃO!", "KKKKK"], "en": ["NO WAY", "INSANE", "BRO...", "WHAT?!"]}
LIXO = re.compile(r"^[\W_k]*$|^(lol|lmao|kkk+|haha+|clip|clipe)\W*$", re.I)


_CLAUDE_FORA = False


def _json_do_texto(texto: str) -> dict:
    texto = texto.strip()
    m = re.search(r"\{.*\}", texto, re.S)
    return json.loads(m.group(0) if m else texto)


def _perguntar_claude(prompt: str, imagens: list | None = None) -> dict:
    """Claude pela assinatura (CLAUDE_CODE_OAUTH_TOKEN). Com `imagens`, ele abre as folhas de quadros
    (ferramenta Read, só leitura) antes de responder; sem imagens, nenhuma ferramenta."""
    import subprocess
    if imagens:
        lista = "\n".join(f"- {Path(i).resolve()}" for i in imagens)
        prompt = (f"ANTES DE RESPONDER, abra e OLHE estas imagens com a ferramenta Read (são folhas de quadros do vídeo; "
                  f"cada quadro tem o segundo escrito no canto):\n{lista}\n\n" + prompt)
        ferramentas = ["--allowedTools", "Read", "--disallowedTools", "Bash,Edit,Write,WebFetch,WebSearch,Glob,Grep",
                       "--max-turns", str(len(imagens) + 3)]
    else:
        ferramentas = ["--max-turns", "1", "--disallowedTools", "Bash,Edit,Write,Read,WebFetch,WebSearch"]
    r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", os.getenv("CLAUDE_MODELO", "sonnet"),
                        *ferramentas],
                       input=prompt + "\n\nResponda APENAS com o JSON pedido, sem texto antes ou depois.",
                       capture_output=True, text=True, timeout=240,
                       env={**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": re.sub(r"\s", "", os.getenv("CLAUDE_CODE_OAUTH_TOKEN", ""))})
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-300:])
    saida = json.loads(r.stdout)
    if saida.get("is_error"):
        raise RuntimeError(str(saida.get("result"))[:300])
    return _json_do_texto(saida.get("result", ""))


def _perguntar_ollama(endereco: str, modelo: str, prompt: str, imagens: list | None = None) -> dict:
    """Pergunta pra IA. Se o Claude estiver ligado (chave nos Secrets), ele responde; senão, o Ollama grátis."""
    global _CLAUDE_FORA
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN") and not _CLAUDE_FORA:
        try:
            r = _perguntar_claude(prompt, imagens)
            print("    🤖 Claude respondeu" + (f" (viu {len(imagens)} folha(s) de quadros)" if imagens else ""))
            return r
        except Exception as e:
            print(f"  Claude não respondeu, usando o Ollama ({str(e)[:150]})")
            if "limit" in str(e).lower() or "auth" in str(e).lower() or "not found" in str(e).lower():
                _CLAUDE_FORA = True  # cota acabou / chave ruim: não insiste nesta rodada
    r = requests.post(f"{endereco}/api/generate", timeout=600, json={
        "model": modelo, "prompt": prompt, "format": "json", "stream": False,
        "options": {"temperature": 0.6, "num_ctx": 4096},
    })
    r.raise_for_status()
    return json.loads(r.json()["response"])


SIGLAS = {"gta", "rp", "vi", "iv", "v", "gta6", "irl", "pc", "ps5", "npc", "fps"}
ESTRANHAS = re.compile(r"\b(venir|pero|muy|cuando|ahora|también|aquí|hay|qué)\b", re.I)  # espanhol que a IA solta


def _limpar_titulo(t: str) -> str:
    t = re.sub(r"#\w+", "", t or "").strip().strip('"').strip()
    letras = [c for c in t if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) > 0.6 * len(letras):  # título gritando: vira normal
        palavras = t.lower().split()
        t = " ".join(w.upper() if re.sub(r"\W", "", w) in SIGLAS else w for w in palavras)
        t = t[:1].upper() + t[1:]
    return t[:90]


def titulo_ok(t: str, nome: str) -> bool:
    return len(t) >= 20 and nome.split()[0].lower() in t.lower() and not ESTRANHAS.search(t)


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
            "gancho": random.choice(GANCHOS[idioma]), "chamada": random.choice(CHAMADAS[idioma]),
            "descricao": "", "tags": [], "motivo": "regras (sem IA)", "fonte": "regras"}


VISAO = """

VOCÊ TAMBÉM ESTÁ VENDO O VÍDEO: as folhas de quadros mostram o que acontece na tela, com o segundo de cada quadro.
- Use as imagens pra entender a cena: batida, perseguição, tombo, susto, reação no rosto do streamer (webcam), tela de loading.
- O corte começa 1-2 s antes da AÇÃO VISUAL ou da fala que importa, e termina logo depois da reação.
- Título e chamada devem refletir o que SE VÊ (não invente o que não aparece nem é dito).
- Dê "pico_visual": o segundo do momento mais forte na tela (vai ganhar um zoom rápido).
- Se for silêncio, loading ou cena parada sem graça, pode marcar usar=false.
Inclua "pico_visual" no JSON."""


def decidir(momento: dict, palavras: list[dict], texto: str, nome: str, idioma: str,
            dmin: int, dmax: int, endereco: str, modelo: str, folhas: list | None = None) -> dict:
    janela = momento["fim"] - momento["inicio"]
    if len(palavras) < 4 and not (folhas and os.getenv("CLAUDE_CODE_OAUTH_TOKEN")):
        return plano_b(momento, palavras, nome, idioma, dmin, dmax)  # sem fala e sem visão: regras
    prompt = PROMPT.format(
        nome=nome, idioma_nome=IDIOMAS[idioma], duracao=janela, dmin=dmin, dmax=dmax,
        titulos="\n".join(f"- {t}" for t in momento.get("titulos_chat", [])[:8] if t) or "- (sem título)",
        transcricao=texto[:6000], exemplo=EXEMPLOS[idioma].format(jogo=apelido(momento.get("jogo", ""))),
        jogo=apelido(momento.get("jogo", "")), seo=SEO[idioma],
        evento_txt=(f"\nEste trecho é a REAÇÃO do streamer ao {momento['evento']}. O título deve dizer isso, "
                    f"ex.: \"{nome} reagindo ao {momento['evento']}\" ou parecido, em estilo curiosidade.")
                   if momento.get("evento") else "",
    )
    usa_visao = bool(folhas and os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))
    if usa_visao:
        prompt += VISAO
    try:
        r = _perguntar_ollama(endereco, modelo, prompt, folhas if usa_visao else None)
        inicio, fim = float(r.get("inicio", 0)), float(r.get("fim", 0))
        inicio = max(0.0, min(inicio, janela - dmin))
        fim = min(janela, max(fim, inicio + dmin))
        if fim - inicio > dmax:
            fim = inicio + dmax
        titulo = _limpar_titulo(r.get("titulo", ""))
        gancho = str(r.get("gancho", "")).upper().strip()[:16] or random.choice(GANCHOS[idioma])
        if ESTRANHAS.search(titulo):
            titulo = ""
        if len(titulo) < 12 or nome.split()[0].lower() not in titulo.lower():
            titulo = _limpar_titulo(f"{nome}: {titulo}") if len(titulo) >= 12 else \
                random.choice(MODELOS_TITULO[idioma]).format(nome=nome, jogo=apelido(momento.get("jogo", "")))
        chamada = re.sub(r"#\w+", "", str(r.get("chamada", ""))).strip().strip('"')[:40]
        if len(chamada.split()) < 2:
            chamada = random.choice(CHAMADAS[idioma])
        tags = [str(t).strip().lower()[:40] for t in (r.get("tags") or []) if str(t).strip()][:12]
        descricao = re.sub(r"#\w+", "", str(r.get("descricao", ""))).strip()[:400]
        try:
            nota = max(0, min(10, int(float(r.get("nota", 5)))))
        except (TypeError, ValueError):
            nota = 5
        try:
            pico_visual = float(r["pico_visual"]) if r.get("pico_visual") is not None else None
        except (TypeError, ValueError):
            pico_visual = None
        return {"pico_visual": pico_visual, "usar": bool(r.get("usar", True)), "nota": nota, "inicio": round(inicio, 2), "fim": round(fim, 2),
                "titulo": titulo, "gancho": gancho, "chamada": chamada, "descricao": descricao, "tags": tags,
                "titulos_extra": [t for t in (_limpar_titulo(str(x)) for x in (r.get("titulos_extra") or []))
                                  if len(t) >= 15 and not ESTRANHAS.search(t)][:5],
                "motivo": str(r.get("motivo", ""))[:200], "fonte": "ia"}
    except Exception as e:  # Ollama fora do ar, JSON quebrado etc.
        d = plano_b(momento, palavras, nome, idioma, dmin, dmax)
        d["motivo"] = f"plano B: {str(e)[:120]}"
        return d


def titulo_compilado(idioma: str, tipo: str, nomes: list[str], data: str, evento: str = "",
                     reacts: bool = False) -> str:
    """Palavra buscada na frente (GTA RP / GTA 6), nomes dos streamers no fim (pessoas buscam por eles)."""
    destaque = ", ".join(nomes[:3])
    if tipo == "serie":
        return (f"{evento}: a reação dos streamers ({destaque})" if idioma == "pt"
                else f"{evento}: streamers react ({destaque})")[:95]
    if reacts and tipo == "dia":
        return (f"GTA 6: a reação dos streamers aos trailers e adiamentos ({destaque})" if idioma == "pt"
                else f"GTA 6: streamers react to the trailers and delays ({destaque})")[:95]
    if idioma == "pt":
        if tipo == "top10":
            return f"GTA RP: TOP 10 momentos mais insanos da semana ({destaque})"[:95]
        return f"GTA RP: os momentos mais engraçados de {data} ({destaque})"[:95]
    if tipo == "top10":
        return f"GTA RP: TOP 10 craziest moments this week ({destaque})"[:95]
    return f"GTA RP: funniest moments of {data} ({destaque})"[:95]


PROMPT_LONGO = """Você é editor de um canal de cortes de GTA no YouTube. Este é um CORTE LONGO ({minutos:.0f} minutos) da live do {nome}.
Jogo: {jogo}. Idioma: {idioma_nome}.
Os espectadores clicaram este momento com estes títulos: {titulos}

Transcrição resumida (segundo: fala):
{transcricao}

Escreva em {idioma_nome}:
- "titulo": 50 a 70 caracteres, com "{nome}" e "{jogo}" no começo e uma curiosidade sobre o que acontece. Não minta.
- "descricao": 3 frases contando a história do corte, com palavras que o público busca.
- "tags": 10 a 14 buscas que levariam alguém a este vídeo.
- "gancho": 1 ou 2 palavras em maiúsculas para a thumb.

{seo}

Responda só com JSON: {{"titulo": "...", "descricao": "...", "tags": ["..."], "gancho": "..."}}"""


def textos_longo(nome: str, momento: dict, transcricao: str, idioma: str, endereco: str, modelo: str,
                 minutos: float) -> dict:
    jogo = apelido(momento.get("jogo", ""))
    padrao = {
        "titulo": (f"{nome} no {jogo}: o momento completo que ninguém esperava" if idioma == "pt"
                   else f"{nome} in {jogo}: the full moment nobody expected")[:90],
        "descricao": "", "tags": [], "gancho": random.choice(GANCHOS[idioma]),
    }
    try:
        r = _perguntar_ollama(endereco, modelo, PROMPT_LONGO.format(
            minutos=minutos, nome=nome, jogo=jogo, idioma_nome=IDIOMAS[idioma], seo=SEO[idioma],
            titulos="; ".join(t for t in momento.get("titulos_chat", [])[:6] if t) or "(sem título)",
            transcricao=transcricao[:5000]))
        titulo = _limpar_titulo(r.get("titulo", ""))
        if titulo_ok(titulo, nome):
            padrao["titulo"] = re.sub(re.escape(nome.split()[0]), nome.split()[0], titulo, count=1, flags=re.I)
        padrao["descricao"] = re.sub(r"#\w+", "", str(r.get("descricao", ""))).strip()[:600]
        padrao["tags"] = [str(t).strip().lower()[:40] for t in (r.get("tags") or []) if str(t).strip()][:12]
        padrao["gancho"] = str(r.get("gancho", "")).upper().strip()[:16] or padrao["gancho"]
    except Exception as e:
        print(f"  IA fora para o corte longo, usando título padrão ({str(e)[:100]})")
    return padrao


PROMPT_JANELA = """Você edita cortes longos de GTA para o YouTube. Abaixo está a transcrição (segundo: fala) de um trecho de {total:.0f} segundos
do vídeo "{titulo}" de {nome}.

Escolha o MELHOR bloco contínuo de {dmin} a {dmax} segundos para virar um corte longo: deve começar no início de um assunto
(não no meio de uma frase), ter o momento mais engraçado/interessante/reação forte, e terminar quando o assunto fecha.
Evite começar com silêncio, "oi chat" ou loading.

Transcrição:
{transcricao}

Responda só com JSON: {{"inicio": 30, "fim": 400, "motivo": "..."}}"""


def janela_longa(nome: str, momento: dict, transcricao: str, total: float, idioma: str, endereco: str, modelo: str,
                 dmin: int = 180, dmax: int = 480) -> tuple[float, float]:
    """Bloco de 3 a 8 min escolhido pela IA. Sem IA: o miolo do trecho."""
    if total <= dmax:
        return 0.0, total
    padrao = (max(0.0, total / 2 - dmax / 2), min(total, total / 2 + dmax / 2))
    try:
        r = _perguntar_ollama(endereco, modelo, PROMPT_JANELA.format(
            total=total, titulo=(momento.get("titulos_chat") or [""])[0][:120], nome=nome,
            dmin=dmin, dmax=dmax, transcricao=transcricao[:9000]))
        a, b = float(r.get("inicio", -1)), float(r.get("fim", -1))
        a, b = max(0.0, a), min(total, b)
        if b - a < dmin * 0.8:
            b = min(total, a + dmin)
        if b - a > dmax * 1.1:
            b = a + dmax
        if 0 <= a < b and b - a >= dmin * 0.8:
            return a, b
    except Exception as e:
        print(f"  IA fora para escolher o bloco do corte longo ({str(e)[:100]})")
    return padrao
