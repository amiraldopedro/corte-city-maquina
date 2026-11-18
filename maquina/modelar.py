"""Shorts em alta -> versão Corte City: a máquina acha os Shorts de GTA 6 que mais viralizaram
(qualquer idioma), o robô do Mac baixa, e aqui a gente refaz em português com voz nova.

Como fica o vídeo final:
- o gameplay é o do Short original (a parte boa: a imagem que viralizou);
- a fala original SAI (Demucs separa e joga fora a voz, fica só o som do jogo);
- entra uma narração nova em português (tradução adaptada, não literal) com a voz do canal;
- legendas no estilo Corte City, marca CC e crédito ao canal original na descrição.

Etapas (cada uma roda sozinha):
1. `cacar`  (1x por dia): busca na API do YouTube os Shorts de GTA 6 mais vistos dos últimos dias
   e põe na fila do robô do Mac (status modelo_pendente).
2. Robô do Mac: baixa o Short inteiro e sobe pro GitHub (status modelo_baixado).
3. `montar` (toda rodada): transcreve, adapta pro PT com a IA, tira a voz, narra, monta e agenda.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .estado import Estado
from .youtube_auto import OFICIAIS, _segundos
from .youtube_fonte import _baixar_asset, agora, fila

PALAVRAS_GTA = re.compile(r"gta|grand theft|vice city|leonida|rockstar|lucia|jason", re.I)

PROMPT = """Você escreve narrações de Shorts em português do Brasil para o canal Corte City (cortes de GTA 6).
Abaixo está a transcrição de um Short gringo que viralizou. Reescreva em português do Brasil:
- NÃO traduza ao pé da letra: adapte como um brasileiro contaria, mas mantenha o gancho da primeira frase,
  a ordem das informações e o clima (piada fica piada, surpresa fica surpresa).
- Fala natural de narrador jovem, frases curtas, sem palavrão, sem gírias forçadas.
- NO MÁXIMO {max_palavras} palavras (o vídeo tem {dur:.0f} segundos). Isso é um limite duro.
- Não cite o nome do canal original nem diga "esse vídeo".
- Se o original terminar chamando pra seguir/curtir, troque por "segue a Corte City". Senão, não invente.

Título original: {titulo}
Transcrição ({idioma}): {texto}

Responda SÓ em JSON: {{"texto": "a narração em português", "titulo": "título chamativo em português com no máximo 90 letras", "gancho": "chamada de 3 a 6 palavras pra tela (ex: OLHA O QUE ELE FEZ)"}}"""


# ---------------------------------------------------------------- 1) caçar
def cacar(cfg) -> int:
    """Acha os Shorts de GTA 6 mais virais dos últimos dias e põe na fila do robô do Mac."""
    conf = cfg.modelar
    if not conf or not conf.get("ligado", True):
        return 0
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None)
    if not canal or not canal.refresh_token:
        print("  modelar: sem chave do YouTube")
        return 0
    from .publicar import _gastar, tem_cota
    est_canal = Estado(canal.id)
    est_fila = fila()
    hoje = datetime.now(timezone.utc).date().isoformat()
    feitos = sum(1 for m in est_fila.momentos.values()
                 if m.get("modo") == "modelo" and (m.get("pedido_em") or "")[:10] == hoje)
    vagas = int(conf.get("por_dia", 3)) - feitos
    if vagas <= 0 or not tem_cota(est_canal, envios=2):
        return 0
    from datetime import timedelta
    from .youtube import YouTube
    yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token).yt
    desde = (datetime.now(timezone.utc) - timedelta(days=int(conf.get("dias", 4)))).isoformat(timespec="seconds").replace("+00:00", "Z")
    ids = []
    for termo in conf.get("termos", ["GTA 6", "GTA 6 gameplay"]):
        r = yt.search().list(q=termo, part="id", type="video", videoDuration="short", order="viewCount",
                             maxResults=25, publishedAfter=desde).execute()
        ids += [it["id"]["videoId"] for it in r.get("items", [])]
    _gastar(est_canal, 100 * len(conf.get("termos", [1, 1])) + 2)
    est_canal.salvar()
    ids = [i for i in dict.fromkeys(ids) if i not in est_fila.momentos]
    videos = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        videos += r.get("items", [])
    # canais que a gente já modelou há pouco tempo: pula (pra não virar xerox de um canal só)
    recentes = {m.get("canal_id_yt") for m in est_fila.momentos.values()
                if m.get("modo") == "modelo" and (m.get("pedido_em") or "") >= (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()}
    bons = []
    for v in videos:
        s, st = v["snippet"], v.get("statistics", {})
        dur = _segundos(v["contentDetails"].get("duration"))
        views = int(st.get("viewCount") or 0)
        texto_busca = " ".join([s.get("title", ""), s.get("description", "")[:200], " ".join(s.get("tags", [])[:10])])
        if OFICIAIS.search(s.get("channelTitle", "")) or s.get("channelId") in recentes:
            continue
        if not (8 <= dur <= int(conf.get("max_seg", 75))) or views < int(conf.get("min_views", 150000)):
            continue
        if not PALAVRAS_GTA.search(texto_busca):
            continue
        dias_no_ar = max(0.5, (datetime.now(timezone.utc)
                               - datetime.fromisoformat(s["publishedAt"].replace("Z", "+00:00"))).total_seconds() / 86400)
        bons.append({"id": v["id"], "titulo": s["title"], "canal": s["channelTitle"], "canal_id": s["channelId"],
                     "views": views, "dur": dur, "forca": views / dias_no_ar})
    bons.sort(key=lambda x: -x["forca"])
    novos = 0
    canais_vistos = set()
    for v in bons:
        if novos >= vagas:
            break
        if v["canal_id"] in canais_vistos:
            continue
        canais_vistos.add(v["canal_id"])
        est_fila.momentos[v["id"]] = {
            "id": v["id"], "link": f"https://www.youtube.com/watch?v={v['id']}", "modo": "modelo",
            "status": "modelo_pendente", "titulo": v["titulo"], "canal_nome": v["canal"],
            "canal_id_yt": v["canal_id"], "views_yt": v["views"], "dur": v["dur"],
            "pedido_em": agora(), "atualizado_em": agora(),
        }
        novos += 1
        print(f"  🔥 modelo na fila do Mac: {v['titulo'][:62]} ({v['canal']}, {v['views']:,} views, {v['dur']}s)")
    est_fila.salvar()
    if not novos:
        print("  modelar: nenhum Short viral novo passou no filtro hoje")
    return novos


# ---------------------------------------------------------------- 3) montar
def _adaptar(cfg, item: dict, palavras: list[dict], idioma: str, dur: float) -> dict | None:
    from . import cerebro
    texto = " ".join(w["p"] for w in palavras)
    if len(texto.split()) < 5:
        return None  # Short sem fala (só música/gameplay): não tem o que narrar
    max_palavras = int(dur * 2.4)
    try:
        r = cerebro._perguntar_ollama(cfg.ia_endereco, cfg.noticias.get("modelo", cfg.ia_modelo),
                                      PROMPT.format(max_palavras=max_palavras, dur=dur,
                                                    titulo=item.get("titulo", ""), idioma=idioma, texto=texto[:2500]))
    except Exception as e:
        print(f"    IA não respondeu ({str(e)[:100]}): fica pra próxima rodada")
        return None
    novo = (r.get("texto") or "").strip()
    if len(novo.split()) < 5:
        return None
    if len(novo.split()) > max_palavras + 8:  # passou do limite: corta na última frase que cabe
        corte, soma = [], 0
        for frase in re.split(r"(?<=[.!?…])\s+", novo):
            soma += len(frase.split())
            if soma > max_palavras:
                break
            corte.append(frase)
        novo = " ".join(corte) or " ".join(novo.split()[:max_palavras])
    return {"texto": novo, "titulo": (r.get("titulo") or item.get("titulo", ""))[:95],
            "gancho": (r.get("gancho") or "").strip()[:40]}


def montar(cfg, maximo: int = 2) -> int:
    """Shorts que o Mac baixou viram vídeos do Corte City: voz original sai, narração nova entra."""
    import subprocess
    import tempfile

    from . import editar, thumb
    from .narrado import falar
    from .transcrever import transcrever
    from .voz import tirar_voz
    est_fila = fila()
    pendentes = {k: v for k, v in est_fila.momentos.items() if v.get("status") == "modelo_baixado"}
    if not pendentes:
        return 0
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None)
    if not canal:
        return 0
    est = Estado(canal.id)
    yt = None
    if canal.postar == "automatico" and canal.refresh_token:
        from .youtube import YouTube
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token).yt
    from .config import RAIZ
    feitos = 0
    for vid, item in list(pendentes.items())[:maximo]:
        mid = f"mod_{vid}"
        if mid in est.momentos:
            item.update(status="modelado", atualizado_em=agora())
            continue
        print(f"  🎬 modelando: {item.get('titulo', vid)[:66]}")
        pasta = Path(tempfile.mkdtemp(prefix="cc_mod_"))
        try:
            bruto = _baixar_asset(int(item["asset_id"]), pasta / "bruto.mp4")
            _, _, dur = editar.info_video(bruto)
            dur = min(dur, float(cfg.duracao_max))
            orig = transcrever(bruto, None, cfg.whisper)
            idioma = item.get("idioma_falado") or "auto"
            plano = _adaptar(cfg, item, orig, idioma, dur)
            if not plano:
                item.update(status="modelo_sem_fala" if len(orig) < 5 else "modelo_baixado",
                            atualizado_em=agora())
                if item["status"] == "modelo_sem_fala":
                    print("    sem fala no original: descartado (nada pra traduzir)")
                continue
            # narração nova (se ficar maior que o vídeo, acelera um pouco; limite +25%)
            narr = pasta / "narr.mp3"
            palavras = falar(plano["texto"], cfg.modelar.get("voz", "pt-BR-AntonioNeural"), "+8%", narr)
            fala_dur = palavras[-1]["f"] if palavras else 0
            if fala_dur > dur - 0.2:
                extra = min(25, int((fala_dur / max(dur - 0.4, 1)) * 108 - 100))
                palavras = falar(plano["texto"], cfg.modelar.get("voz", "pt-BR-AntonioNeural"), f"+{extra}%", narr)
                fala_dur = palavras[-1]["f"] if palavras else 0
            fim = min(max(dur, 12.0), max(fala_dur + 0.6, 12.0), float(cfg.duracao_max))
            # tira a voz original, mistura o som do jogo (baixo) com a narração
            jogo = pasta / "jogo.flac"
            try:
                tirar_voz(bruto, jogo)
            except Exception as e:
                print(f"    aviso: não separou a voz ({str(e)[:80]}): uso o som original bem baixo")
                jogo = None
            mix = pasta / "mix.m4a"
            if jogo:
                fc = "[0:a]volume=0.30[j];[1:a]volume=1.0[n];[j][n]amix=inputs=2:duration=longest:normalize=0[a]"
                ent = ["-i", str(jogo), "-i", str(narr)]
            else:
                fc = "[0:a]volume=0.12[j];[1:a]volume=1.0[n];[j][n]amix=inputs=2:duration=longest:normalize=0[a]"
                ent = ["-i", str(bruto), "-i", str(narr)]
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ent, "-filter_complex", fc, "-map", "[a]",
                            "-t", f"{fim:.2f}", "-c:a", "aac", "-b:a", "192k", str(mix)], check=True, timeout=600)
            # se a narração passa do vídeo, congela o último quadro até ela acabar
            fonte_video = bruto
            if fim > dur + 0.3:
                est_v = pasta / "esticado.mp4"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bruto),
                                "-vf", f"tpad=stop_mode=clone:stop_duration={fim - dur + 0.5:.2f}",
                                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(est_v)],
                               check=True, timeout=900)
                fonte_video = est_v
            from .config import PASTA_PRONTOS
            PASTA_PRONTOS.mkdir(parents=True, exist_ok=True)
            final = PASTA_PRONTOS / f"{mid}.mp4"
            info = editar.editar_short(fonte_video, 0.0, fim, palavras, final, RAIZ / canal.marca,
                                       canal.cor_destaque, chamada=plano["gancho"], audio=mix,
                                       etiqueta="GTA 6")
            capa = thumb.gerar_thumb(editar.frame_em(bruto, min(1.0, dur / 2)), final.with_suffix(".jpg"),
                                     plano["gancho"] or plano["titulo"][:40], canal.cor_destaque, info["webcam"])
            titulo = plano["titulo"]
            tags = ["gta 6", "gta vi", "gta 6 gameplay", "shorts", "cortes gta"]
            credito = item.get("url_final") or f"https://www.youtube.com/watch?v={vid}"
            descricao = (f"{titulo}\n\nIdeia e gameplay: {item.get('canal_nome', 'YouTube')} ({credito})\n"
                         f"Versão em português: Corte City.\n\n" + " ".join(canal.hashtags))
            from .entrega import entregar
            try:
                arquivos = entregar(final, capa, mid)
            except Exception as e:
                print(f"    aviso: cópia nos downloads falhou ({str(e)[:80]})")
                arquivos = {}
            base = {"tipo": "short", "jogo": "Grand Theft Auto VI", "titulo": titulo, "gancho": plano["gancho"],
                    "descricao": descricao, "tags": tags, "feito_em": agora(), "nome": item.get("canal_nome", ""),
                    "streamer": "corte-city", "plataforma": "youtube", "quadro": "modelado",
                    "duracao": round(fim, 1), "modelo_de": credito, **arquivos}
            if yt is not None:
                from .publicar import publicar
                from .youtube import proximo_horario
                ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
                quando = proximo_horario(canal.horarios, canal.fuso, ocupados)
                est.momentos[mid] = {"id": mid, "canal": canal.id, "status": "novo", "criado_em": agora(),
                                     "atualizado_em": agora(), **base}
                est.salvar()
                publicar(est, mid, yt, final, titulo, descricao, tags, canal.idioma, quando, capa,
                         canal.playlists.get("shorts", ""), print, **base)
            else:
                est.momentos[mid] = {"id": mid, "canal": canal.id, "status": "pronto", "criado_em": agora(),
                                     "atualizado_em": agora(), **base}
                est.salvar()
            item.update(status="modelado", atualizado_em=agora())
            feitos += 1
            print(f"    ✅ modelado: {titulo[:70]}")
        except Exception as e:
            item.update(status="modelo_erro", erro=str(e)[:300], atualizado_em=agora())
            print(f"    ❌ deu errado ({str(e)[:160]})")
        finally:
            import shutil
            shutil.rmtree(pasta, ignore_errors=True)
            est_fila.salvar()
    return feitos
