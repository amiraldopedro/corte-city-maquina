"""Máquina de cortes GTA 6 — comandos:

  python main.py cacar                   consulta a Twitch e enche a fila de momentos
  python main.py fila                    responde "sim" se há Short para produzir agora
  python main.py produzir                monta os Shorts da fila e deixa prontos para você postar
  python main.py compilado dia|top10     monta e posta o vídeo longo
  python main.py bloquear LOGIN          nunca mais corta esse streamer
  python main.py apagar LOGIN            apaga do YouTube todos os vídeos desse streamer
  python main.py numeros                 atualiza views/likes dos vídeos postados
  python main.py painel ACAO --id/--login/--nome/--canal/--quando   botões do painel visual
  python main.py teste                   confere chaves e conexões
  python main.py simular VIDEO.mp4       edita um vídeo local (sem Twitch/YouTube), para testar
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from maquina.config import PASTA_PRONTOS, RAIZ, Canal, Config, carregar
from maquina.estado import Estado, agora
from maquina.momentos import agrupar, priorizar

AVISO = {
    "pt": ("Canal de fãs, sem vínculo oficial com a Rockstar Games nem com os streamers. Todos os direitos "
           "pertencem aos seus criadores. Se algo for seu e você quiser a remoção, avise nos comentários."),
    "en": ("Fan channel, not affiliated with Rockstar Games or the streamers. All rights belong to their "
           "original creators. If something is yours and you want it removed, tell us in the comments."),
}
LIVE = {"pt": "🎮 Live original", "en": "🎮 Original stream"}
TESTE = os.getenv("MODO_TESTE") == "1"  # aceita clipe de qualquer jogo e marca o vídeo como [TESTE]


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ====================================================================== caçar
def cacar(cfg: Config, canal: Canal, est: Estado, tw) -> int:
    streamers = cfg.streamers_do(canal)
    usuarios = tw.usuarios([s.login for s in streamers])
    jogos = {} if TESTE else tw.ids_jogos(cfg.jogos)
    jogos_palavra = {} if TESTE or not cfg.jogos_com_palavra else tw.ids_jogos(cfg.jogos_com_palavra)
    novos = 0
    for s in streamers:
        u = usuarios.get(s.login)
        if not u:
            log(f"  {s.login}: não existe na Twitch (confira o login no config.yaml)")
            continue
        try:
            clipes = [c for c in tw.clipes(u["id"], cfg.janela_busca_horas) if not est.clipe_visto(c["id"])]
        except Exception as e:
            log(f"  {s.nome}: Twitch falhou ({str(e)[:100]}), sigo com os outros")
            continue
        momentos = agrupar(clipes, jogos, s.login, canal.id, cfg.minimo_clipes, cfg.minimo_views,
                           jogos_palavra, cfg.palavras, cfg.um_clipe_views)
        for m in momentos:
            if TESTE:
                m["teste"] = True
            if est.inserir(priorizar(m)):
                novos += 1
            est.marcar_clipes(m["clipe_ids"])
        log(f"  {s.nome}: {len(clipes)} clipes novos, {len(momentos)} momentos")
    try:
        novos += descobrir(cfg, canal, est, tw, {s.login for s in streamers})
    except Exception as e:
        log(f"  descoberta por jogo falhou ({str(e)[:100]})")
    novos += cacar_kick(cfg, canal, est)
    return novos


def cacar_kick(cfg: Config, canal: Canal, est: Estado) -> int:
    """Streamers que fazem live na Kick (precisa da chave KICK_API_KEY)."""
    from maquina import kick
    lista = [s for s in canal.kick if s.login not in cfg.bloqueados]
    if TESTE or not lista:
        return 0
    if not kick.ligado():
        log("  Kick: desligada (falta a chave KICK_API_KEY nos Secrets)")
        return 0
    palavras = list(cfg.palavras) + ["gta", "rp", "cidade alta", "complexo"]
    novos = 0
    for s in lista:
        try:
            clipes = [c for c in kick.clipes(s.login, cfg.janela_busca_horas) if not est.clipe_visto(c["id"])]
        except Exception as e:
            log(f"  Kick {s.login}: {e}")
            continue
        bons = [c for c in clipes if kick.vale(c, cfg.jogos, palavras)]
        ms = kick.momentos(bons, s.login, canal.id, cfg.minimo_views)
        for m in ms:
            m["nome"] = s.nome
            if est.inserir(priorizar(m)):
                novos += 1
            est.marcar_clipes(m["clipe_ids"])
        log(f"  Kick {s.nome}: {len(clipes)} clipes novos, {len(ms)} momentos")
    return novos


def descobrir(cfg: Config, canal: Canal, est: Estado, tw, ja_vistos: set) -> int:
    """Clipes mais vistos dos jogos escolhidos, de qualquer streamer do idioma do canal."""
    d = canal.descobrir
    if TESTE or not d.get("jogos"):
        return 0
    jogos = tw.ids_jogos(d["jogos"])
    conversa = tw.ids_jogos(cfg.jogos_com_palavra) if cfg.jogos_com_palavra else {}
    idioma, minimo = d.get("idioma", canal.idioma), int(d.get("min_views", 300))
    por_streamer: dict[str, list] = {}
    for gid in list(jogos) + list(conversa):
        for c in tw.clipes(game_id=gid, horas=cfg.janela_busca_horas, maximo=600 if cfg.lancado else 300):
            login = (c.get("broadcaster_name") or "").lower().replace(" ", "")
            if (c.get("language") or "")[:2] != idioma or c.get("view_count", 0) < minimo or est.clipe_visto(c["id"]):
                continue
            if not login or login in ja_vistos or login in cfg.bloqueados:
                continue
            c["_nome"] = c.get("broadcaster_name") or login
            por_streamer.setdefault(login, []).append(c)
    novos = 0
    for login, clipes in por_streamer.items():
        for m in agrupar(clipes, jogos, login, canal.id, 1, minimo, conversa, cfg.palavras):
            m["nome"] = clipes[0]["_nome"]
            m["descoberto"] = True
            if est.inserir(priorizar(m)):
                novos += 1
            est.marcar_clipes(m["clipe_ids"])
    log(f"  descoberta por jogo: {sum(len(v) for v in por_streamer.values())} clipes de {len(por_streamer)} streamers, {novos} momentos novos")
    return novos


# ====================================================================== produzir
MAX_ESPERANDO = 9  # se você não postar, a máquina para de fazer vídeo novo (e economiza minutos do GitHub)


def fazer_kit(video: Path, inicio: float, fim: float, pico: float | None, titulo: str, variantes: list[str],
              gancho: str, nome: str, jogo: str, canal: Canal, mid: str, vertical: bool) -> dict:
    """Kit da thumb (PDF + ZIP) para você montar a capa na sua IA de imagem. Nunca derruba o vídeo."""
    try:
        from maquina import kit
        from maquina.cerebro import apelido
        frames = kit.melhores_frames(video, inicio, fim, 6, pico)
        if not frames:
            return {}
        pdf, z = kit.gerar(frames, titulo, variantes, gancho, nome, apelido(jogo) or "GTA", canal.cor_destaque,
                           PASTA_PRONTOS / "kits", mid, vertical, canal.idioma)
        return kit.entregar_kit(pdf, z, mid)
    except Exception as e:
        log(f"  aviso: kit da thumb falhou ({str(e)[:150]})")
        return {}


def limite_streamer(cfg: Config, est: Estado, m: dict) -> str:
    """Diversidade: no máximo N Shorts do mesmo streamer por dia e nunca dois seguidos em menos de 6 h.
    React de evento velho (mais de 30 dias) sai da fila."""
    agora_dt = datetime.now(timezone.utc)
    if m.get("evento"):
        quando = m.get("clipado_em") or ""
        try:
            if (agora_dt - datetime.fromisoformat(quando.replace("Z", "+00:00"))).days > 30:
                return "velho"
        except ValueError:
            pass
    feitos = [x for x in est.momentos.values() if x.get("streamer") == m["streamer"] and m["streamer"] != "*"
              and x.get("tipo", "short") == "short" and x["status"] in ("pronto", "postado", "aguardando_cota")
              and (x.get("feito_em") or x.get("postado_em"))]
    def horas(x):
        try:
            return (agora_dt - datetime.fromisoformat((x.get("feito_em") or x.get("postado_em")).replace("Z", "+00:00"))).total_seconds() / 3600
        except ValueError:
            return 999
    if sum(1 for x in feitos if horas(x) < 24) >= cfg.max_por_streamer_dia:
        return "cota do dia"
    if any(horas(x) < 6 for x in feitos):
        return "muito seguido"
    return ""


def etiqueta_do(m: dict) -> str:
    """Plaquinha azul em cima da chamada: diz de que quadro é o corte."""
    from maquina.momentos import quadro
    if m.get("evento"):
        return "REACT"
    return {"gta6": "GTA 6", "rp": "GTA RP", "classicos": "CLÁSSICO", "noticias": "NOTÍCIA",
            "comunidade": "COMUNIDADE"}.get(m.get("quadro") or quadro(m), "GTA")


def playlist_do(canal: Canal, m: dict) -> str:
    """Amontoado organizado: cada Short vai para a playlist do seu quadro."""
    from maquina.momentos import quadro
    return canal.playlists.get(m.get("quadro") or quadro(m)) or canal.playlists.get("shorts", "")


def postados_hoje(est: Estado, canal: Canal) -> int:
    """Shorts que a máquina deixou prontos hoje (meta diária = número de horários do canal)."""
    tz = ZoneInfo(canal.fuso)
    hoje = datetime.now(tz).date()
    n = 0
    for m in est.momentos.values():
        quando = m.get("feito_em") or m.get("postado_em")
        if m.get("teste"):
            continue  # vídeo de teste não conta na meta
        if m.get("tipo", "short") == "short" and m["status"] in ("pronto", "postado", "aguardando_cota") and quando:
            if datetime.fromisoformat(quando).astimezone(tz).date() == hoje:
                n += 1
    return n


def esperando(est: Estado) -> int:
    return sum(1 for m in est.momentos.values() if m["status"] == "pronto")


def link_live(login: str, plataforma: str = "") -> str:
    if plataforma == "youtube":
        return f"https://www.youtube.com/channel/{login}" if login.startswith("UC") else f"https://www.youtube.com/@{login.lstrip('@')}"
    return f"https://kick.com/{login}" if plataforma == "kick" else f"https://twitch.tv/{login}"


def descricao_short(canal: Canal, titulo: str, login: str, plataforma: str = "", resumo: str = "") -> str:
    # as 2 primeiras linhas são as que o YouTube mostra e usa na busca
    topo = f"{titulo}\n{resumo}" if resumo else titulo
    return (f"{topo}\n\n{LIVE[canal.idioma]}: {link_live(login, plataforma)}\n\n{AVISO[canal.idioma]}\n\n"
            + " ".join(canal.hashtags))


def produzir_um(cfg: Config, canal: Canal, est: Estado, m: dict, yt) -> bool:
    from maquina import cerebro, compilado, editar, thumb, titulos
    from maquina.baixar import baixar_momento
    from maquina.transcrever import texto_com_tempos, transcrever
    nome = cfg.nome_streamer(m["streamer"], m.get("nome", ""))
    log(f"  produzindo {m['id']} ({nome}, {m['n_clipes']} clipes, {m['views']} views)")
    if m.get("yt_asset"):  # trecho de vídeo do YouTube que o robô do Mac subiu
        from maquina.youtube_fonte import preparar_bruto
        bruto = preparar_bruto(m, compilado.PASTA_BRUTOS / f"{m['id']}.mp4")
    else:
        bruto = baixar_momento(m)
    if bruto.with_suffix(".clipe").exists():  # usou o clipe do público: a janela é o clipe inteiro
        m = {**m, "inicio": 0.0, "fim": editar.info_video(bruto)[2], "video_id": None}
    palavras = transcrever(bruto, canal.idioma, cfg.whisper)
    folhas = []
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):  # o Claude "vê" o vídeo por folhas de quadros
        try:
            from maquina.kit import folhas_de_quadros
            # o arquivo baixado já começa no início do momento: os segundos vão de 0 até a duração da janela
            folhas = folhas_de_quadros(bruto, 0.0, editar.info_video(bruto)[2], PASTA_PRONTOS / "folhas" / m["id"])
        except Exception as e:
            log(f"    aviso: folhas de quadros falharam ({str(e)[:100]})")
    d = cerebro.decidir(m, palavras, texto_com_tempos(palavras), nome, canal.idioma,
                        cfg.duracao_min, cfg.duracao_max, cfg.ia_endereco, cfg.ia_modelo, folhas,
                        recentes=titulos.recentes(est))
    log(f"    cérebro ({d['fonte']}): {d['titulo']} | gancho {d['gancho']} | {d['inicio']}-{d['fim']}s")
    if not d["usar"]:
        est.atualizar(m["id"], status="descartado", motivo=d["motivo"])
        log(f"    descartado: {d['motivo']}")
        return False
    if d.get("ia") == "claude" and d.get("nota") is not None and d["nota"] < cfg.nota_minima and not m.get("prioridade"):
        est.atualizar(m["id"], status="descartado", nota=d["nota"], criterios=d.get("criterios"),
                      motivo=f"nota {d['nota']}/9 abaixo da mínima {cfg.nota_minima} ({d.get('criterios')})")
        log(f"    descartado pela nota: {d['nota']}/9 {d.get('criterios')}")
        return False

    if d.get("palavrao_inicio") and d["fim"] - d["inicio"] - 2.0 >= cfg.duracao_min:
        d["inicio"] = round(d["inicio"] + 2.0, 2)  # palavrão pesado logo de cara: o algoritmo pode segurar o Short
        log("    palavrão no começo: o corte começa 2 s depois")
    final = PASTA_PRONTOS / f"{m['id']}.mp4"
    voz = None
    if m.get("evento") or m.get("isolar_voz") or d.get("musica"):  # música (trailer, rádio) faz o YouTube silenciar o Short
        from maquina.voz import tentar_isolar
        voz = tentar_isolar(bruto)
        log(f"    voz isolada: {'sim' if voz else 'NÃO'}")
        if not voz:  # com música de trailer/rádio o Short leva Content ID: melhor não postar do que postar mudo
            raise RuntimeError("precisava isolar a voz (tem música com direitos) e não deu: tenta de novo depois")
    pico = d.get("pico_visual")
    if pico is None or not (d["inicio"] + 0.5 < pico < d["fim"] - 0.5):
        pico = editar.momento_mais_alto(bruto, d["inicio"], d["fim"])
    info = editar.editar_short(bruto, d["inicio"], d["fim"], palavras, final, RAIZ / canal.marca, canal.cor_destaque,
                               chamada=d.get("chamada", ""), pico=pico, audio=voz, etiqueta=etiqueta_do(m))
    pico_rel = pico - d["inicio"]
    try:
        novo = editar.cortar_silencios(final, palavras, d["inicio"], d["fim"])
        if novo:
            pico_rel = novo(pico_rel)
    except Exception as e:
        log(f"    aviso: jump cut falhou ({str(e)[:100]})")
    try:
        if editar.abrir_no_pico(final, pico_rel):
            log("    abertura no pico: o 1º segundo mostra o momento mais forte")
    except Exception as e:
        log(f"    aviso: abertura no pico falhou ({str(e)[:100]})")
    from maquina.baixar import MUDO_DB, volume_maximo
    if volume_maximo(final) <= MUDO_DB:
        raise RuntimeError("o vídeo final ficou sem som — não vou entregar")
    capa = thumb.gerar_thumb(editar.frame_em(bruto, pico), final.with_suffix(".jpg"), d["gancho"],
                             canal.cor_destaque, info["webcam"])
    from maquina.painel import guardar_thumb
    guardar_thumb(capa, m["id"])

    titulo = ("[TESTE] " if m.get("teste") else "") + d["titulo"]
    jogo = cerebro.apelido(m.get("jogo", "")).lower()
    base = [nome.lower(), f"{nome.lower()} {jogo}", jogo, "gta rp", "gta 6", "cortes", "cortes gta", "shorts"]
    tags = list(dict.fromkeys(d.get("tags", []) + base))[:15]
    resumo = d.get("descricao", "")
    from maquina.entrega import entregar
    try:
        arquivos = entregar(final, capa, m["id"])   # sempre fica uma cópia para baixar (reserva)
    except Exception as e:  # sem a cópia nos downloads o vídeo ainda pode ir pro YouTube
        log(f"    aviso: cópia nos downloads falhou ({str(e)[:100]})")
        arquivos = {}
    arquivos.update(fazer_kit(bruto, d["inicio"], d["fim"], pico, d["titulo"], d.get("titulos_extra", []),
                              d["gancho"], nome, m.get("jogo", ""), canal, m["id"], vertical=True))
    if canal.postar == "automatico" and not m.get("teste") and yt is not None:
        from maquina.youtube import proximo_horario
        ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
        publicar_em = proximo_horario(canal.horarios, canal.fuso, ocupados)
        descricao = descricao_short(canal, titulo, m["streamer"], m.get("plataforma", ""), resumo)
        from maquina.publicar import publicar
        vid = publicar(est, m["id"], yt, final, titulo, descricao, tags, canal.idioma, publicar_em, capa,
                       playlist_do(canal, m), log, tipo="short", jogo=m.get("jogo", ""), titulo=titulo,
                       gancho=d["gancho"], descricao=descricao, tags=tags, feito_em=agora(),
                       corte=[d["inicio"], d["fim"]], layout=info["layout"], cerebro=d["fonte"], nome=nome,
                       nota=d.get("nota"), quadro=m.get("quadro"), duracao=round(d["fim"] - d["inicio"], 1),
                       prioridade=False, **arquivos)
        if not vid:
            return True  # ficou pronto, esperando cota: conta como feito
        log(f"    ✅ enviado e agendado para {publicar_em}: https://youtu.be/{vid}")
        return True
    est.atualizar(m["id"], status="pronto", tipo="short", jogo=m.get("jogo", ""), titulo=titulo, gancho=d["gancho"],
                  descricao=descricao_short(canal, titulo, m["streamer"], m.get("plataforma", ""), resumo), tags=tags,
                  playlist=playlist_do(canal, m), corte=[d["inicio"], d["fim"]], feito_em=agora(),
                  layout=info["layout"], cerebro=d["fonte"], nome=nome, nota=d.get("nota"),
                  duracao=round(d["fim"] - d["inicio"], 1), prioridade=False, **arquivos)
    log(f"    ✅ pronto para postar: {titulo}")
    log(f"       baixar: {arquivos.get('video_url', '(sem cópia)')}")
    return True


def fazer_cacada(cfg: Config):
    """Etapa leve: só consulta a Twitch e guarda os momentos novos na fila."""
    from maquina.twitch import Twitch
    tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
    if cfg.lancado:
        log("🌴 MODO LANÇAMENTO DO GTA 6 ligado: mais Shorts, busca nas últimas 24h")
    for canal in cfg.canais_ativos():
        log(f"== {canal.nome}: caçando clipes")
        est = Estado(canal.id)
        for x in est.momentos.values():
            if not x.get("teste") or x.get("youtube_id"):
                continue
            if TESTE and x["status"] in ("erro", "descartado"):
                x["status"] = "novo"       # teste de novo depois de uma correção
            elif not TESTE and x["status"] == "novo":
                x["status"] = "descartado"  # momento de teste nunca vira vídeo de verdade
        from maquina.momentos import reescalar
        for x in est.momentos.values():
            reescalar(x)
        try:
            log(f"  {cacar(cfg, canal, est, tw)} momentos novos na fila")
        finally:
            est.salvar()


def buscar_series(cfg: Config, so_evento: str = ""):
    """Busca os reacts de cada evento (trailers, adiamentos, lançamento) e põe na fila."""
    import yaml
    from datetime import datetime as dt
    from maquina.twitch import Twitch
    series = (yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8")) or {}).get("series") or {}
    palavras = [p.lower() for p in series.get("palavras", [])]
    minimo = int(series.get("min_views", 200))
    tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
    jogos = tw.ids_jogos(["Just Chatting", "Grand Theft Auto V", "Grand Theft Auto VI", "IRL"])
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        usuarios = tw.usuarios([s.login for s in cfg.streamers_do(canal)])
        idioma = canal.descobrir.get("idioma", canal.idioma)
        for ev in series.get("eventos", []):
            if so_evento and so_evento.lower() not in ev["nome"].lower():
                continue
            ini = dt.fromisoformat(ev["inicio"]).replace(tzinfo=timezone.utc)
            fim = dt.fromisoformat(ev["fim"]).replace(tzinfo=timezone.utc) + timedelta(days=1)
            if ini > datetime.now(timezone.utc):
                continue
            por: dict[str, list] = {}
            fontes = [("u", u["id"], login) for login, u in usuarios.items()] + [("g", gid, "") for gid in jogos]
            for tipo, ident, login in fontes:
                lista = tw.clipes(broadcaster_id=ident, inicio=ini, fim=fim, maximo=200) if tipo == "u" else \
                    tw.clipes(game_id=ident, inicio=ini, fim=fim, maximo=500)
                for c in lista:
                    quem = login or (c.get("broadcaster_name") or "").lower().replace(" ", "")
                    titulo = (c.get("title") or "").lower()
                    if not quem or quem in cfg.bloqueados or est.clipe_visto(c["id"]):
                        continue
                    if tipo == "g" and (c.get("language") or "")[:2] != idioma:
                        continue
                    if c.get("view_count", 0) < minimo or not any(p in titulo for p in palavras):
                        continue
                    c["_nome"] = c.get("broadcaster_name") or quem
                    if ini < datetime.now(timezone.utc) - timedelta(days=55):
                        c["vod_offset"] = None  # live gravada já expirou: usa o clipe direto
                    por.setdefault(quem, {})[c["id"]] = c
            novos = 0
            for quem, cs in por.items():
                for m in agrupar(list(cs.values()), {}, quem, canal.id, 1, minimo):
                    m.update(evento=ev["nome"], nome=cfg.nome_streamer(quem, list(cs.values())[0]["_nome"]),
                             jogo="Just Chatting")
                    if est.inserir(priorizar(m)):
                        novos += 1
                    est.marcar_clipes(m["clipe_ids"])
            log(f"  {canal.nome} · {ev['nome']}: {sum(len(v) for v in por.values())} clipes de {len(por)} streamers → {novos} reacts na fila")
        est.salvar()


def tem_trabalho(cfg: Config) -> bool:
    """Existe algum canal com momento na fila e meta do dia ainda aberta?"""
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        fila = [m for m in est.por_status("novo") if m["streamer"] not in cfg.bloqueados
                and TESTE == bool(m.get("teste")) and not m.get("yt_longo")]
        if not TESTE and canal.postar == "automatico" and any(m["status"] == "aguardando_cota" for m in est.momentos.values()):
            return True  # tem vídeo pronto esperando cota do YouTube
        if fila and (TESTE or (postados_hoje(est, canal) < len(canal.horarios)
                               and (canal.postar == "automatico" or esperando(est) < MAX_ESPERANDO))):
            return True
    return False


def produzir(cfg: Config):
    """Etapa pesada: baixa, transcreve, edita e deixa pronto para postar (até a meta diária de cada canal)."""
    falhou = False
    for canal in cfg.canais_ativos():
        log(f"== {canal.nome} ({canal.modo})")
        est = Estado(canal.id)
        try:
            yt = None
            if canal.postar == "automatico" and not TESTE:
                from maquina.youtube import YouTube
                yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
                from maquina.publicar import enviar_pendentes
                from maquina.youtube import proximo_horario

                def horario_livre():
                    ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
                    return proximo_horario(canal.horarios, canal.fuso, ocupados)
                try:
                    if enviar_pendentes(est, canal, yt, PASTA_PRONTOS / "pendentes", horario_livre, log):
                        est.salvar()
                except Exception as e:
                    log(f"  aviso: envios pendentes falharam ({str(e)[:120]})")
                from maquina.publicar import tem_cota
                if not tem_cota(est):
                    log("  cota do YouTube de hoje já acabou: não vou montar vídeo novo agora")
                    continue
            limite = 1 if TESTE else len(canal.horarios) - postados_hoje(est, canal)
            if limite <= 0:
                log("  meta de Shorts de hoje já cumprida")
                continue
            if not TESTE and canal.postar != "automatico" and esperando(est) >= MAX_ESPERANDO:
                log(f"  já tem {esperando(est)} vídeos prontos esperando você postar — não vou fazer mais agora")
                continue
            feitos = tentativas = 0
            for m in est.por_status("novo"):
                if TESTE != bool(m.get("teste")) or m.get("yt_longo"):  # trecho longo do YouTube vai pro corte longo
                    continue
                quantos = int(os.getenv("QUANTOS") or cfg.max_por_rodada)
                if feitos >= (1 if TESTE else min(limite, quantos)) or tentativas >= quantos + 3:
                    break
                if m["streamer"] in cfg.bloqueados:
                    est.atualizar(m["id"], status="descartado", motivo="streamer bloqueado")
                    continue
                if not TESTE and not m.get("prioridade"):
                    regra = limite_streamer(cfg, est, m)
                    if regra == "velho":
                        est.atualizar(m["id"], status="descartado", motivo="react de evento com mais de 30 dias")
                        continue
                    if regra:
                        continue  # fica na fila: hoje esse streamer já teve o bastante
                if m.get("evento") and not TESTE:
                    feitos_evento = [x for x in est.momentos.values() if x.get("evento") and x["status"] in ("pronto", "postado")]
                    if any(x["streamer"] == m["streamer"] and x["evento"] == m["evento"] for x in feitos_evento):
                        est.atualizar(m["id"], status="descartado", motivo="mesmo streamer já reagiu a esse evento num vídeo")
                        continue
                    hoje = datetime.now(timezone.utc).date().isoformat()
                    if any((x.get("feito_em") or "")[:10] == hoje for x in feitos_evento):
                        continue  # no máximo 1 react de trailer por dia: fica pra amanhã
                    tres_dias = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
                    if any(x["streamer"] == m["streamer"] and (x.get("feito_em") or "") >= tres_dias for x in feitos_evento):
                        continue  # o mesmo streamer reagindo de novo cansa: espera 3 dias
                tentativas += 1
                try:
                    feitos += produzir_um(cfg, canal, est, m, yt)
                except Exception as e:
                    if est.momentos[m["id"]].get("youtube_id"):  # o erro veio depois do envio: já está no YouTube
                        est.atualizar(m["id"], status="postado", erro_pos_envio=str(e)[:200])
                        log(f"    aviso: erro depois do envio, mas o vídeo está no YouTube ({str(e)[:120]})")
                        feitos += 1
                        continue
                    falhas = m.get("falhas", 0) + 1
                    est.atualizar(m["id"], status="erro" if falhas >= 2 else "novo", falhas=falhas, erro=str(e)[:300],
                                  score=m.get("score", 0) * 0.5)
                    log(f"    ❌ erro ({falhas}ª vez): {str(e)[:300]}")
                finally:
                    est.salvar()
        except Exception:
            falhou = True
            traceback.print_exc()
        finally:
            for x in est.momentos.values():  # momentos de teste que sobraram não ficam na fila de verdade
                if x.get("teste") and x["status"] == "novo":
                    x["status"] = "descartado"
            est.salvar()
    if falhou:
        sys.exit(1)


# ====================================================================== compilado
def _capitulos(usados: list[dict], nomes: dict, idioma: str) -> str:
    """Capítulos na descrição (YouTube pede o primeiro em 00:00 e pelo menos 3)."""
    if len(usados) < 3:
        return ""
    linhas = []
    for m in usados:
        t = int(m.get("_cap", 0))
        nome = nomes.get(m["streamer"], m.get("nome") or m["streamer"])
        assunto = re.sub(re.escape(nome), "", m.get("titulo") or "", flags=re.I).strip(" :-–|.") or (m.get("evento") or "")
        linhas.append(f"{t // 60:02d}:{t % 60:02d} {nome}" + (f" — {assunto[:60]}" if assunto else ""))
    return ("⏱️ Capítulos\n" if idioma == "pt" else "⏱️ Chapters\n") + "\n".join(linhas)


def _postar_longo(cfg: Config, canal: Canal, est: Estado, saida: Path, capa: Path, cid: str, tipo: str,
                  titulo: str, descricao: str, tags: list[str], playlist: str, extra: dict):
    from maquina.entrega import entregar
    arquivos = entregar(saida, capa, cid)
    envio = {}
    if canal.postar == "automatico":
        from maquina.youtube import YouTube, proximo_horario
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
        ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
        horario = canal.horario_longo if tipo == "longo" else canal.horario_compilado
        publicar_em = proximo_horario([horario], canal.fuso, ocupados)
        envio = {"yt": yt, "publicar_em": publicar_em}
    anterior = est.momentos.get(cid, {})
    est.momentos[cid] = {**anterior, "id": cid, "streamer": "*", "canal": canal.id, "tipo": tipo,
                         "status": anterior.get("status", "pronto") if anterior.get("youtube_id") else "pronto",
                         "titulo": titulo, "descricao": descricao, "tags": tags, "playlist": playlist,
                         "feito_em": agora(), "criado_em": anterior.get("criado_em") or agora(), **extra, **arquivos}
    est.salvar()
    if envio:
        from maquina.publicar import publicar
        vid = publicar(est, cid, envio["yt"], saida, titulo, descricao, tags, canal.idioma, envio["publicar_em"],
                       capa, playlist, log)
        if vid:
            log(f"  ✅ enviado e agendado para {envio['publicar_em']}: https://youtu.be/{vid}")
    log(f"  ✅ {tipo} pronto: {titulo}")
    log(f"     baixar: {arquivos['video_url']}")


def fazer_compilado(cfg: Config, tipo: str, evento: str = ""):
    if tipo == "longo":
        return fazer_corte_longo(cfg)
    from maquina import cerebro, compilado, editar, thumb
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        horas = 7 * 24 if tipo == "top10" else 36
        desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat(timespec="seconds")
        candidatos = [m for m in est.momentos.values()
                      if (m.get("evento", "").lower() == evento.lower() if tipo == "serie" else m.get("criado_em", "") >= desde)
                      and m["status"] in ("novo", "pronto", "postado") and not m.get("teste")
                      and m.get("tipo", "short") == "short" and m["streamer"] not in cfg.bloqueados
                      and tipo not in m.get("usado_em", [])]
        candidatos.sort(key=lambda m: -m.get("score", 0))
        qtd = 10 if tipo == "top10" else 12
        escolhidos = candidatos[:qtd + 4]  # sobra, caso algum trecho não baixe ou não isole a voz
        log(f"== {canal.nome}: compilado {tipo} com até {min(len(escolhidos), qtd)} momentos")
        if len(escolhidos) < 3:
            log("  poucos momentos, fica para a próxima")
            continue
        nomes = {s.login: s.nome for s in canal.streamers + canal.kick}
        nomes.update({m["streamer"]: m["nome"] for m in escolhidos if m.get("nome") and m["streamer"] not in nomes})
        data = datetime.now(ZoneInfo(canal.fuso)).strftime("%d/%m" if canal.idioma == "pt" else "%b %d")
        saida = PASTA_PRONTOS / f"{tipo}_{canal.id}_{datetime.now().strftime('%Y%m%d')}.mp4"
        usados = compilado.montar(escolhidos, nomes, tipo, canal.cor_destaque, RAIZ / canal.marca, saida,
                                  maximo=qtd)
        ordem_nomes = list(dict.fromkeys(nomes.get(m["streamer"], m["streamer"]) for m in reversed(usados)))
        reacts = sum(1 for m in usados if m.get("evento")) * 2 > len(usados)
        titulo = cerebro.titulo_compilado(canal.idioma, tipo, ordem_nomes, data, evento, reacts, n=len(usados))

        melhor = usados[-1] if tipo == "top10" else usados[0]
        bruto = Path(compilado.PASTA_BRUTOS / f"{melhor['id']}.mp4")
        pico = editar.momento_mais_alto(bruto, 0, editar.info_video(bruto)[2])
        etiqueta = f"TOP {len(usados)}" if tipo == "top10" else "REACTS" if tipo == "serie" else ("MELHORES DO DIA" if canal.idioma == "pt" else "BEST OF THE DAY")
        capa = thumb.gerar_thumb(editar.frame_em(bruto, pico), saida.with_suffix(".jpg"),
                                 melhor.get("gancho") or cerebro.GANCHOS[canal.idioma][0], canal.cor_destaque,
                                 editar.achar_webcam(bruto, 0, editar.info_video(bruto)[2]), etiqueta)
        from maquina.painel import guardar_thumb
        cid = f"{tipo}_{datetime.now().strftime('%Y%m%d')}" + (f"_{re.sub(r'[^a-z0-9]', '', evento.lower())[:20]}" if evento else "")
        guardar_thumb(capa, cid)
        kit_extra = fazer_kit(bruto, 0, editar.info_video(bruto)[2], pico, titulo,
                              [cerebro.titulo_compilado(canal.idioma, t, ordem_nomes, data, evento) for t in ("dia", "top10")],
                              melhor.get("gancho") or cerebro.GANCHOS[canal.idioma][0],
                              nomes.get(melhor["streamer"], melhor["streamer"]), melhor.get("jogo", ""), canal, cid, vertical=False)
        plat = {m["streamer"]: m.get("plataforma", "") for m in usados}
        creditos = "\n".join(f"• {nomes.get(l, l)}: {link_live(l, p)}" for l, p in plat.items())
        resumo = ("Os momentos mais engraçados e insanos das lives de GTA RP: " if canal.idioma == "pt"
                  else "The funniest and craziest GTA RP stream moments: ") + ", ".join(ordem_nomes[:6]) + "."
        descricao = (f"{titulo}\n{resumo}\n\n{_capitulos(usados, nomes, canal.idioma)}\n\n"
                     f"{LIVE[canal.idioma]}:\n{creditos}\n\n{AVISO[canal.idioma]}\n\n#gtarp #gta6 #cortes")
        tags = list(dict.fromkeys([*(n.lower() for n in ordem_nomes[:6]), "gta rp", "gta rp brasil", "cortes gta rp",
                                   "momentos engraçados gta", "gta 6", "melhores momentos gta rp",
                                   *([evento.lower(), "reagindo trailer gta 6"] if evento else [])]))[:15]
        for m in usados:
            est.atualizar(m["id"], usado_em=list(dict.fromkeys(est.momentos[m["id"]].get("usado_em", []) + [tipo])))
        _postar_longo(cfg, canal, est, saida, capa, cid, tipo, titulo, descricao, tags,
                      canal.playlists.get("top10" if tipo == "top10" else "compilado", ""),
                      {"itens": [m["id"] for m in usados], "streamers": sorted({m["streamer"] for m in usados}), **kit_extra})


def fazer_corte_longo(cfg: Config):
    """Corte longo (16:9, até 9 min): o melhor momento do dia com o contexto inteiro da live."""
    from maquina import cerebro, compilado, editar, thumb
    from maquina.baixar import baixar_trecho
    from maquina.transcrever import texto_com_tempos, transcrever
    from maquina.voz import tentar_isolar
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        desde = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(timespec="seconds")
        candidatos = sorted([m for m in est.momentos.values()
                             if (m.get("video_id") or m.get("yt_longo")) and m.get("criado_em", "") >= desde
                             and not m.get("teste") and m["status"] in ("novo", "pronto", "postado")
                             and m.get("tipo", "short") == "short"
                             and m["streamer"] not in cfg.bloqueados and "longo" not in m.get("usado_em", [])],
                            key=lambda m: (not m.get("yt_longo"), -m.get("score", 0)))  # o que você mandou vem primeiro
        log(f"== {canal.nome}: corte longo ({len(candidatos)} candidatos)")
        for m in candidatos[:3]:
            ini = max(0.0, m["inicio"] - 120)
            fim = min(ini + 6 * 60, m["fim"] + 150)   # até 6 min: cabe na cota grátis do GitHub
            destino = compilado.PASTA_BRUTOS / f"longo_{m['id']}.mp4"
            try:
                if m.get("yt_longo"):
                    bruto, ini, fim, m = corte_longo_youtube(cfg, canal, m, destino)
                else:
                    bruto = baixar_trecho(m["video_id"], ini, fim, None, destino)
            except Exception as e:
                log(f"  {m['id']}: não deu para baixar a live ({str(e)[:120]})")
                est.atualizar(m["id"], usado_em=list(dict.fromkeys(m.get("usado_em", []) + ["longo"])))
                continue
            from maquina.baixar import MUDO_DB, volume_maximo
            if volume_maximo(bruto) <= MUDO_DB:
                log(f"  {m['id']}: trecho da live está mudo, pulando")
                continue
            voz = tentar_isolar(bruto)
            if not voz:
                continue
            nome = cfg.nome_streamer(m["streamer"], m.get("nome", ""))
            # para o título basta o miolo (3 min em volta do momento): economiza minutos do GitHub
            miolo = voz.with_name(voz.stem + ".miolo.mp4")
            centro = max(0.0, m["inicio"] - ini - 60)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{centro:.1f}", "-t", "180", "-i", str(voz),
                            "-vn", "-c:a", "aac", str(miolo)], check=False)
            palavras = transcrever(miolo if miolo.exists() else voz, canal.idioma, cfg.whisper)
            t = cerebro.textos_longo(nome, m, texto_com_tempos(palavras, 8.0), canal.idioma,
                                     cfg.ia_endereco, cfg.ia_modelo, (fim - ini) / 60)
            saida = PASTA_PRONTOS / f"longo_{canal.id}_{m['id']}.mp4"
            compilado._segmento(voz, saida, nome, None, canal.cor_destaque, RAIZ / canal.marca)
            dur = editar.info_video(saida)[2]
            pico = editar.momento_mais_alto(saida, 0, dur)
            capa = thumb.gerar_thumb(editar.frame_em(saida, pico), saida.with_suffix(".jpg"), t["gancho"],
                                     canal.cor_destaque, editar.achar_webcam(bruto, 0, dur), "CORTE COMPLETO"
                                     if canal.idioma == "pt" else "FULL CLIP")
            from maquina.painel import guardar_thumb
            cid = f"longo_{m['id']}"
            guardar_thumb(capa, cid)
            descricao = (f"{t['titulo']}\n{t['descricao']}\n\n{LIVE[canal.idioma]}: "
                         f"{link_live(m['streamer'], m.get('plataforma', ''))}\n\n{AVISO[canal.idioma]}\n\n#gtarp #cortes")
            tags = list(dict.fromkeys(t["tags"] + [nome.lower(), f"{nome.lower()} gta rp", "gta rp", "cortes gta rp",
                                                   "gta rp brasil", "gta 6"]))[:15]
            est.atualizar(m["id"], usado_em=list(dict.fromkeys(m.get("usado_em", []) + ["longo"])))
            kit_extra = fazer_kit(bruto, 0, dur, pico, t["titulo"], [], t["gancho"], nome, m.get("jogo", ""),
                                  canal, cid, vertical=False)
            _postar_longo(cfg, canal, est, saida, capa, cid, "longo", t["titulo"], descricao, tags,
                          canal.playlists.get("compilado", ""), {"itens": [m["id"]], "streamers": [m["streamer"]], **kit_extra})
            break
        else:
            log("  nenhum momento com a live disponível para o corte longo")


def corte_longo_youtube(cfg: Config, canal: Canal, m: dict, destino: Path):
    """Trecho grande do YouTube (até ~12 min): a IA lê a transcrição e escolhe o melhor bloco de 3 a 8 min."""
    from maquina import cerebro, editar
    from maquina.transcrever import texto_com_tempos, transcrever
    from maquina.youtube_fonte import preparar_bruto
    inteiro = preparar_bruto(m, destino.with_name(destino.stem + "_inteiro.mp4"))
    total = editar.info_video(inteiro)[2]
    palavras = transcrever(inteiro, canal.idioma, cfg.whisper)
    nome = cfg.nome_streamer(m["streamer"], m.get("nome", ""))
    a, b = cerebro.janela_longa(nome, m, texto_com_tempos(palavras, 10.0), total, canal.idioma,
                                cfg.ia_endereco, cfg.ia_modelo)
    log(f"  IA escolheu o bloco {a / 60:.1f}-{b / 60:.1f} min de {total / 60:.1f} min")
    editar.rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", str(inteiro),
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k", str(destino)])
    # o resto do corte longo espera o momento "no meio" do trecho
    return destino, 0.0, b - a, {**m, "inicio": min(120.0, (b - a) / 2), "fim": b - a}


# ====================================================================== notícias (Google Notícias + posts do X)
def fazer_noticias(cfg: Config, links: list[str]):
    """Shorts de notícia: posts do X que você colou (sempre) + as notícias mais novas de GTA 6 (até o limite do dia)."""
    from maquina import cerebro, editar, noticias, thumb
    from maquina.baixar import baixar_trecho
    conf = cfg.noticias
    for canal in cfg.canais_ativos():
        if canal.idioma != "pt" and not links:
            continue
        est = Estado(canal.id)
        tz = ZoneInfo(canal.fuso)
        hoje = datetime.now(tz).date()

        def do_dia(m):
            try:
                return datetime.fromisoformat(m["feito_em"].replace("Z", "+00:00")).astimezone(tz).date() == hoje
            except (KeyError, ValueError, AttributeError):
                return False
        feitas_hoje = sum(1 for m in est.momentos.values() if m.get("tipo") == "noticia"
                          and m.get("origem") == "noticia" and do_dia(m))
        for link in links:
            fazer_post_x(cfg, canal, est, link)
        fila = []
        vagas = max(0, int(conf.get("por_dia", 2)) - feitas_hoje)
        if vagas:
            try:
                novas = [n for n in noticias.google_noticias(conf.get("termos", ["GTA 6", "GTA VI"]), canal.idioma)
                         if n["id"] not in est.momentos]
                log(f"  Google Notícias: {len(novas)} notícias novas de GTA 6")
                fila += novas[: vagas * 4]  # não gasta tempo de IA com notícia demais
            except Exception as e:
                log(f"  Google Notícias fora do ar: {str(e)[:120]}")
        feitas = 0
        from maquina import titulos
        ja = titulos.recentes(est, dias=5)
        for item in fila:
            if item["origem"] == "noticia" and feitas >= vagas:
                break
            if item["id"] in est.momentos and item["origem"] == "noticia":
                continue
            base = {"id": item["id"], "streamer": "*", "canal": canal.id, "tipo": "noticia", "quadro": "noticias",
                    "origem": item["origem"], "fonte": item["fonte"], "link": item["link"], "criado_em": agora(),
                    "titulo_fonte": item.get("titulo_fonte", "")}
            if item["origem"] == "noticia" and titulos.repetido(item.get("titulo_fonte", ""), ja, 0.5):
                est.momentos[item["id"]] = {**base, "status": "descartado", "motivo": "assunto repetido",
                                            "atualizado_em": agora()}
                log(f"  assunto já saiu no canal: {item.get('titulo_fonte', '')[:80]}")
                continue
            ja.append(item.get("titulo_fonte", ""))
            if noticias.bloqueado(item["titulo_fonte"]):
                est.momentos[item["id"]] = {**base, "status": "descartado", "motivo": "filtro (vazamento/sensível)"}
                log(f"  barrada pelo filtro: {item['titulo_fonte'][:80]}")
                continue
            try:
                r = noticias.roteiro(item, canal.nome, canal.idioma,
                                     lambda pr: cerebro._perguntar_ollama(cfg.ia_endereco, conf.get("modelo") or cfg.ia_modelo, pr))
            except Exception as e:
                log(f"  IA fora do ar, notícia fica para depois: {str(e)[:100]}")
                break
            if not r:
                est.momentos[item["id"]] = {**base, "status": "descartado", "motivo": "IA barrou"}
                continue
            r["titulo"] = titulos.caixa_de_livro(r["titulo"])
            if titulos.ruim(r["titulo"]) or titulos.repetido(r["titulo"], ja[:-1], 0.6):
                est.momentos[item["id"]] = {**base, "status": "descartado",
                                            "motivo": f"título ruim ou repetido: {r['titulo'][:60]}"}
                log(f"  título ruim/repetido, pulei: {r['titulo'][:80]}")
                continue
            try:
                final, capa = montar_noticia(cfg, canal, item, r, baixar_trecho, editar, noticias, thumb)
            except Exception as e:
                log(f"  ❌ notícia falhou: {str(e)[:200]}")
                continue
            from maquina.painel import guardar_thumb
            guardar_thumb(capa, item["id"])
            descricao = (f"{r['titulo']}\n{r['narracao']}\n\n"
                         f"{'Fonte' if canal.idioma == 'pt' else 'Source'}: {item['fonte']} {item['link']}\n\n"
                         + " ".join(canal.hashtags))
            tags = list(dict.fromkeys(r["tags"] + ["gta 6", "gta vi", "noticias gta 6", "gta 6 novidades", "rockstar"]))[:15]
            est.momentos[item["id"]] = {**base, "status": "pronto", "titulo": r["titulo"], "descricao": descricao,
                                       "tags": tags, "feito_em": agora(), "duracao": editar.info_video(final)[2]}
            from maquina.entrega import entregar
            est.momentos[item["id"]].update(entregar(final, capa, item["id"]))
            if canal.postar == "automatico" and not TESTE:
                from maquina.youtube import YouTube, proximo_horario
                yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
                ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
                quando = proximo_horario(conf.get("horarios", ["10:30", "20:30"]), canal.fuso, ocupados)
                from maquina.publicar import publicar
                try:
                    vid = publicar(est, item["id"], yt, final, r["titulo"], descricao, tags, canal.idioma, quando,
                                   capa, canal.playlists.get("noticias", ""), log)
                    if vid:
                        log(f"  ✅ notícia agendada para {quando}: https://youtu.be/{vid}")
                except Exception as e:
                    log(f"  ❌ envio da notícia falhou (fica pronta pra baixar): {str(e)[:150]}")
            est.salvar()
            if item["origem"] == "noticia":
                feitas += 1
        est.salvar()


def fazer_post_x(cfg: Config, canal: Canal, est: Estado, link: str):
    """Post do X do jeito que a pessoa postou (texto + foto/vídeo) num template de post, com crédito."""
    from maquina import cerebro, editar, noticias, thumb, xposts
    try:
        post = xposts.buscar(link)
    except Exception as e:
        log(f"  post do X não abriu ({link}): {str(e)[:150]}")
        return
    if post["id"] in est.momentos and (est.momentos[post["id"]].get("status") in ("pronto", "postado", "aguardando_cota")
                                       or est.momentos[post["id"]].get("youtube_id")):
        log(f"  post já foi feito: {link}")
        return
    base = {"id": post["id"], "streamer": "*", "canal": canal.id, "tipo": "noticia", "quadro": "comunidade",
            "origem": "x", "fonte": post["fonte"], "link": post["link"], "criado_em": agora()}
    ok, motivo = xposts.seguro(post)
    if not ok:
        est.momentos[post["id"]] = {**base, "status": "descartado", "motivo": motivo}
        est.salvar()
        log(f"  post barrado ({motivo}): {link}")
        return
    autor = post["autor"] or post["perfil"]
    # post em inglês (ou outra língua): o texto do card vira português pra pessoa conseguir ler
    try:
        if xposts.traduzir(post, lambda pr: cerebro._perguntar_ollama(
                cfg.ia_endereco, cfg.noticias.get("modelo") or cfg.ia_modelo, pr), canal.idioma):
            log(f"  traduzido do {post['traduzido_de']}: {post['texto'][:80]}")
    except Exception as e:
        log(f"  aviso: não consegui traduzir o post, vai no original ({str(e)[:80]})")
    # título: a IA só resume em poucas palavras (o post em si não é reescrito)
    titulo = ""
    try:
        r = cerebro._perguntar_ollama(cfg.ia_endereco, cfg.noticias.get("modelo") or cfg.ia_modelo,
            f'Escreva um título de YouTube Shorts em português do Brasil, de 40 a 65 caracteres, para este post da comunidade '
            f'do GTA 6 no X, feito por {autor}. Pode ser meme, opinião, teoria ou novidade: o título acompanha o tom do post '
            f'(se for meme, título engraçado). Comece com "GTA 6:". Não invente nada que não está no post. '
            f'Post: "{post["texto"][:600]}". Responda só com JSON: {{"titulo": "..."}}')
        titulo = cerebro._limpar_titulo(str(r.get("titulo", "")))
    except Exception as e:
        log(f"  IA fora para o título, usando o padrão ({str(e)[:80]})")
    from maquina import titulos
    titulo = titulos.caixa_de_livro(titulo)
    if titulos.ruim(titulo):
        resumo = re.sub(r"\s+", " ", post["texto"])[:48].rstrip(" ,.;:") or "olha isso"
        titulo = titulos.caixa_de_livro(f"GTA 6: {resumo}"[:90])
    import random
    oficial = post["perfil"].lower() in ("rockstargames", "rockstarsupport", "take2interactive")
    chamada = ((f"{autor[:18]} POSTOU" if oficial else random.choice(
        ["OLHA O QUE POSTARAM", "A COMUNIDADE TÁ ASSIM", "VIU ISSO NO X?", "O X TÁ FALANDO DISSO"]))
        if canal.idioma == "pt" else (f"{autor[:18]} POSTED" if oficial else "SEEN THIS ON X?")).upper()
    narrar = None
    if post["idioma"] == canal.idioma and not any(m["tipo"] == "video" for m in post["midias"]):
        narrar = lambda texto, destino: noticias.narrar(texto, canal.idioma, destino)
    try:
        final = xposts.montar(post, PASTA_PRONTOS / "noticias" / post["id"], canal.cor_destaque,
                              RAIZ / canal.marca, chamada, narrar)
    except Exception as e:
        log(f"  ❌ post do X falhou: {str(e)[:200]}")
        return
    dur = editar.info_video(final)[2]
    capa = thumb.gerar_thumb(editar.frame_em(final, min(2.5, dur / 2)), final.with_suffix(".jpg"),
                             "OLHA ISSO" if canal.idioma == "pt" else "LOOK", canal.cor_destaque, None, "GTA 6")
    from maquina.painel import guardar_thumb
    guardar_thumb(capa, post["id"])
    rotulo = "Post original" if canal.idioma == "pt" else "Original post"
    original = (f"\n\nOriginal ({post['traduzido_de']}): “{post['texto_original'][:700]}”"
                if post.get("traduzido_de") else "")
    descricao = (f"{titulo}\n\n“{post['texto'][:900]}”\n— {post['fonte']}{original}\n\n{rotulo}: {post['link']}\n\n"
                 + " ".join(canal.hashtags))
    tags = list(dict.fromkeys([autor.lower(), post["perfil"].lower(), "gta 6", "gta vi", "gta 6 memes",
                               "comunidade gta 6", "gta 6 novidades", "rockstar games"]))[:15]
    from maquina.entrega import entregar
    est.momentos[post["id"]] = {**base, "status": "pronto", "titulo": titulo, "descricao": descricao, "tags": tags,
                               "feito_em": agora(), "duracao": dur, **entregar(final, capa, post["id"])}
    if canal.postar == "automatico" and not TESTE:
        from maquina.youtube import YouTube, proximo_horario
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
        ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
        quando = proximo_horario(cfg.noticias.get("horarios", ["10:30", "20:30"]) + canal.horarios, canal.fuso, ocupados)
        from maquina.publicar import publicar
        try:
            vid = publicar(est, post["id"], yt, final, titulo, descricao, tags, canal.idioma, quando, capa,
                           canal.playlists.get("comunidade") or canal.playlists.get("noticias", ""), log)
            if vid:
                log(f"  ✅ post do X agendado para {quando}: https://youtu.be/{vid}")
        except Exception as e:
            log(f"  ❌ envio do post falhou (fica pronto pra baixar): {str(e)[:150]}")
    est.salvar()


def montar_noticia(cfg, canal, item, r, baixar_trecho, editar, noticias, thumb):
    """Fundo de gameplay de GTA (sem som) + cartão da notícia + narração com legenda palavra por palavra."""
    pasta = PASTA_PRONTOS / "noticias"
    pasta.mkdir(parents=True, exist_ok=True)
    voz = pasta / f"{item['id']}.mp3"
    palavras = noticias.narrar(r["narracao"], canal.idioma, voz)
    dur = (palavras[-1]["f"] if palavras else 30) + 0.8
    fundo = fundo_gameplay(cfg, pasta, baixar_trecho)
    card = noticias.cartao(item, r["manchete"], canal.cor_destaque, pasta / f"{item['id']}_card.png", canal.idioma)
    legenda = pasta / f"{item['id']}.ass"
    editar.gerar_legenda(palavras, 0, dur, legenda, 1500, canal.cor_destaque, chamada=r["chamada"], y_chamada=290,
                         etiqueta="NOTÍCIA")
    final = pasta / f"{item['id']}.mp4"
    barra = "0x" + canal.cor_destaque.lstrip("#")
    entradas = ["-stream_loop", "-1", "-i", str(fundo), "-i", str(voz), "-i", str(card)]
    filtro = (f"[0:v]scale=-2:1920,crop=1080:1920,eq=brightness=-0.18:saturation=1.1,setsar=1,fps=30[bg];"
              f"[bg][2:v]overlay=(W-w)/2:430[v0]")
    marca = RAIZ / canal.marca
    if marca.exists():
        entradas += ["-i", str(marca)]
        filtro += ";[3:v]scale=130:-1,format=rgba,colorchannelmixer=aa=0.85[m];[v0][m]overlay=W-w-28:40[v1]"
    else:
        filtro += ";[v0]null[v1]"
    filtro += (f";[v1]ass='{editar._escapar(legenda)}':fontsdir='{editar._escapar(editar.FONTES)}',"
               f"drawbox=x=0:y=0:w='iw*t/{dur:.2f}':h=12:color={barra}@1:t=fill,format=yuv420p[v]")
    editar.rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", filtro,
                  "-map", "[v]", "-map", "1:a", "-t", f"{dur:.2f}", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                  "-movflags", "+faststart", str(final)])
    frame = editar.frame_em(final, min(3.0, dur / 2))
    capa = thumb.gerar_thumb(frame, final.with_suffix(".jpg"), "NOVIDADE" if canal.idioma == "pt" else "BREAKING",
                             canal.cor_destaque, None, "GTA 6")
    return final, capa


def fundo_gameplay(cfg: Config, pasta: Path, baixar_trecho) -> Path:
    """Um clipe de GTA bem visto das últimas 48h (Twitch) para ficar de fundo, sem som."""
    import random
    from maquina.twitch import Twitch
    pronto = sorted(pasta.glob("fundo_*.mp4"))
    if pronto:
        return random.choice(pronto)
    tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
    jogos = tw.ids_jogos(["Grand Theft Auto VI", "Grand Theft Auto V"])
    clipes = []
    for gid in jogos:
        clipes += [c for c in tw.clipes(game_id=gid, horas=48, maximo=50) if c.get("duration", 0) >= 20]
    clipes.sort(key=lambda c: -c.get("view_count", 0))
    for c in clipes[:6]:
        try:
            return baixar_trecho(None, 0, c["duration"], c["url"], pasta / f"fundo_{c['id']}.mp4")
        except Exception as e:
            log(f"  fundo: clipe {c['id']} não baixou ({str(e)[:80]})")
    raise RuntimeError("sem clipe de fundo")


# ====================================================================== vídeo longo narrado (você posta)
def fazer_narrado(cfg: Config, rid: str):
    """Roteiro roteiros/longos/<rid>.json -> vídeo 16:9 narrado; posta agendado (POSTAR=nao só entrega)."""
    import json as _json
    from maquina import editar, kit, narrado, thumb
    from maquina.baixar import baixar_trecho
    roteiro = _json.loads((RAIZ / "roteiros" / "longos" / f"{rid}.json").read_text(encoding="utf-8"))
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None) or cfg.canais_ativos()[0]
    pasta = PASTA_PRONTOS / f"narrado_{rid}"
    fontes = narrado.biblioteca(PASTA_PRONTOS / "biblioteca")
    if fontes:
        log(f"  imagens de fundo: {len(fontes)} vídeos da biblioteca")
    else:
        log("  biblioteca vazia: usando clipes de GTA da Twitch como fundo")
        fontes = fundos_twitch(cfg, pasta / "fundos", baixar_trecho, 12)
    final, capitulos = narrado.montar(roteiro, fontes, canal.cor_destaque, RAIZ / canal.marca, pasta, log)
    dur = editar.info_video(final)[2]
    pico = editar.momento_mais_alto(final, 5, min(dur, 60))
    cid = f"narrado_{rid}"
    capa = thumb.gerar_thumb(editar.frame_em(final, pico), final.with_suffix(".jpg"),
                             roteiro.get("gancho_thumb", "GTA 6"), canal.cor_destaque, None, "GTA 6")
    from maquina.painel import guardar_thumb
    guardar_thumb(capa, cid)
    desc = narrado.descricao(roteiro, capitulos, ["#gta6", "#gtavi", "#gta"])
    from maquina.entrega import entregar
    arquivos = entregar(final, capa, cid)
    arquivos.update(fazer_kit(final, 3, min(dur, 300), pico, roteiro["titulo"], roteiro.get("titulos_extra", []),
                              roteiro.get("gancho_thumb", "GTA 6"), "GTA 6", "Grand Theft Auto VI", canal, cid,
                              vertical=False))
    est = Estado(canal.id)
    ja_postado = (est.momentos.get(cid) or {}).get("youtube_id")
    if ja_postado:
        log(f"  este roteiro já está no YouTube (https://youtu.be/{ja_postado}): não reenvio, só atualizo os downloads")
        est.momentos[cid].update(arquivos)
        est.salvar()
        return
    est.momentos[cid] = {"id": cid, "streamer": "*", "canal": canal.id, "tipo": "narrado", "status": "pronto",
                         "titulo": roteiro["titulo"], "titulos_extra": roteiro.get("titulos_extra", []),
                         "descricao": desc, "tags": roteiro.get("tags", []), "duracao": dur,
                         "feito_em": agora(), "criado_em": agora(), **arquivos}
    est.salvar()
    log(f"  ✅ vídeo narrado pronto ({dur / 60:.1f} min): {arquivos.get('video_url')}")
    if os.environ.get("POSTAR", "sim") != "sim" or canal.postar != "automatico" or not canal.refresh_token:
        log("     (não foi postado: baixe no painel e poste você)")
        return
    _postar_narrado(cfg, canal, est, cid, final, capa, roteiro, desc)


def _postar_narrado(cfg: Config, canal, est, cid: str, final: Path, capa: Path, roteiro: dict, desc: str):
    """Agenda o vídeo narrado: no horário do roteiro ("publicar") ou no próximo 19h livre."""
    # postagem automática: no horário do roteiro ("publicar": "2026-11-17T19:00") ou no próximo 19h livre
    from zoneinfo import ZoneInfo
    from maquina.publicar import publicar
    from maquina.youtube import YouTube
    fuso = ZoneInfo(canal.fuso)
    if roteiro.get("publicar"):
        quando_dt = datetime.fromisoformat(roteiro["publicar"]).replace(tzinfo=fuso)
    else:
        ocupados = {str(m.get("publicar_em", ""))[:13] for m in est.momentos.values()
                    if m.get("tipo") == "narrado" and m.get("publicar_em")}
        quando_dt = datetime.now(fuso).replace(hour=19, minute=0, second=0, microsecond=0)
        while quando_dt < datetime.now(fuso) + timedelta(hours=1) or \
                quando_dt.astimezone(timezone.utc).isoformat()[:13] in ocupados:
            quando_dt += timedelta(days=1)
    quando = quando_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    est.momentos[cid]["publicar_em"] = quando
    yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
    vid = publicar(est, cid, yt, final, roteiro["titulo"], desc, roteiro.get("tags", []), canal.idioma, quando, capa,
                   canal.playlists.get("gta6", ""), log, horario_fixo=True)
    est.salvar()
    if vid:
        log(f"  ✅ agendado pra {quando_dt:%d/%m %H:%M}: https://youtu.be/{vid}")


def so_pendentes(cfg: Config):
    """Só sobe o que ficou esperando cota (roda logo depois que a cota do YouTube renova)."""
    from maquina.publicar import enviar_pendentes
    from maquina.youtube import YouTube, proximo_horario
    for canal in cfg.canais_ativos():
        if canal.postar != "automatico" or not canal.refresh_token:
            continue
        est = Estado(canal.id)
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)

        def horario_livre():
            ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
            return proximo_horario(canal.horarios, canal.fuso, ocupados)
        n = enviar_pendentes(est, canal, yt, PASTA_PRONTOS / "pendentes", horario_livre, log)
        est.salvar()
        log(f"  {canal.id}: {n} envio(s) pendente(s) subiram")


def postar_narrado(cfg: Config, rid: str):
    """Posta um narrado já montado (o vídeo e a thumb que estão nos downloads), sem montar de novo."""
    import json as _json
    import requests
    roteiro = _json.loads((RAIZ / "roteiros" / "longos" / f"{rid}.json").read_text(encoding="utf-8"))
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None) or cfg.canais_ativos()[0]
    est = Estado(canal.id)
    cid = f"narrado_{rid}"
    m = est.momentos.get(cid)
    if not m:
        log(f"  {cid} ainda não foi montado"); return
    if m.get("youtube_id"):
        log(f"  já está no YouTube: https://youtu.be/{m['youtube_id']}"); return
    pasta = PASTA_PRONTOS / cid
    pasta.mkdir(parents=True, exist_ok=True)
    cab = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/octet-stream"}
    repo = os.environ["GITHUB_REPOSITORY"]
    arqs = {}
    for chave, nome in (("video_asset", "final.mp4"), ("thumb_asset", "capa.jpg")):
        r = requests.get(f"https://api.github.com/repos/{repo}/releases/assets/{m[chave]}", headers=cab, timeout=900)
        r.raise_for_status()
        (pasta / nome).write_bytes(r.content)
        arqs[chave] = pasta / nome
    _postar_narrado(cfg, canal, est, cid, arqs["video_asset"], arqs["thumb_asset"], roteiro, m["descricao"])


def fazer_contagem(cfg: Config):
    """Contagem regressiva pro GTA 6 (roteiros/contagem): monta e agenda cada Short no dia e hora marcados."""
    from zoneinfo import ZoneInfo
    from maquina import contagem, editar, narrado, thumb
    from maquina.baixar import baixar_trecho
    from maquina.entrega import entregar
    from maquina.painel import guardar_thumb
    from maquina.publicar import publicar
    canal = next((c for c in cfg.canais_ativos() if c.idioma == "pt"), None) or cfg.canais_ativos()[0]
    est = Estado(canal.id)
    agora_utc = datetime.now(timezone.utc)
    pendentes = []
    for r in contagem.roteiros():
        cid = f"contagem_{r['id']}"
        quando_dt = datetime.fromisoformat(r["publicar"]).replace(tzinfo=ZoneInfo(canal.fuso)).astimezone(timezone.utc)
        x = est.momentos.get(cid, {})
        refazer = not x.get("youtube_id") and r.get("versao", 1) > x.get("versao", 1)
        if not refazer and (x.get("youtube_id") or x.get("status") in ("aguardando_cota", "postado")):
            continue
        if quando_dt < agora_utc + timedelta(minutes=30):
            log(f"  {r['id']}: o dia já passou, pulei")
            continue
        pendentes.append((r, cid, quando_dt.strftime("%Y-%m-%dT%H:%M:%SZ")))
    if not pendentes:
        log("  contagem: nada novo pra montar")
        return
    pasta = PASTA_PRONTOS / "contagem"
    fontes = narrado.biblioteca(PASTA_PRONTOS / "biblioteca")
    if not fontes:
        log("  biblioteca vazia: usando clipes de GTA da Twitch como fundo")
        fontes = fundos_twitch(cfg, pasta / "fundos", baixar_trecho, 8)
    yt = None
    if canal.postar == "automatico" and canal.refresh_token:
        from maquina.youtube import YouTube
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
    for r, cid, quando in pendentes:
        log(f"== contagem {r['id']} (publica {quando})")
        try:
            final = contagem.montar(r, fontes, pasta / r["id"], log)
            dur = editar.info_video(final)[2]
            capa = thumb.gerar_thumb(editar.frame_em(final, min(3.0, dur / 2)), final.with_suffix(".jpg"),
                                     r["selo"], canal.cor_destaque, None, "GTA 6")
            guardar_thumb(capa, cid)
            try:
                arquivos = entregar(final, capa, cid)
            except Exception as e:
                log(f"  aviso: cópia nos downloads falhou ({str(e)[:100]})")
                arquivos = {}
            est.momentos[cid] = {"id": cid, "streamer": "*", "canal": canal.id, "tipo": "short", "quadro": "contagem",
                                 "status": "pronto", "titulo": r["titulo"], "descricao": r["descricao"],
                                 "tags": r["tags"], "duracao": round(dur, 1), "feito_em": agora(), "criado_em": agora(),
                                 "publicar_em": quando, "versao": r.get("versao", 1), **arquivos}
            est.salvar()
            if yt:
                vid = publicar(est, cid, yt, final, r["titulo"], r["descricao"], r["tags"], canal.idioma, quando, capa,
                               canal.playlists.get("gta6", ""), log, horario_fixo=True)
                if vid:
                    log(f"  ✅ agendado pra {quando}: https://youtu.be/{vid}")
            else:
                log(f"  ✅ pronto pra baixar: {arquivos.get('video_url')}")
        except Exception as e:
            log(f"  ❌ {r['id']} falhou: {str(e)[:200]}")
        est.salvar()


def fundos_twitch(cfg: Config, pasta: Path, baixar_trecho, quantos: int) -> list[Path]:
    """Clipes de GTA bem vistos (últimas 72h) pra servir de fundo quando a biblioteca está vazia."""
    from maquina.twitch import Twitch
    pasta.mkdir(parents=True, exist_ok=True)
    tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
    clipes = []
    for gid in tw.ids_jogos(["Grand Theft Auto VI", "Grand Theft Auto V"]):
        clipes += [c for c in tw.clipes(game_id=gid, horas=72, maximo=80) if c.get("duration", 0) >= 15]
    clipes.sort(key=lambda c: -c.get("view_count", 0))
    saida = []
    for c in clipes:
        if len(saida) >= quantos:
            break
        try:
            saida.append(baixar_trecho(None, 0, c["duration"], c["url"], pasta / f"tw_{c['id']}.mp4"))
        except Exception as e:
            log(f"  fundo {c['id']} não baixou ({str(e)[:80]})")
    return saida


# ====================================================================== controle
def bloquear(login: str):
    from maquina import painel
    painel.bloquear(login)


def apagar(cfg: Config, login: str):
    from maquina.youtube import YouTube
    login = login.lower().strip()
    for canal in cfg.canais:
        if not canal.refresh_token:
            continue
        est = Estado(canal.id)
        alvos = [m for m in est.momentos.values() if m.get("youtube_id") and m["status"] == "postado"
                 and (m["streamer"] == login or login in m.get("streamers", []))]
        if not alvos:
            continue
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
        for m in alvos:
            if yt.apagar(m["youtube_id"]):
                est.atualizar(m["id"], status="removido")
                log(f"  {canal.nome}: apagado {m['youtube_id']} ({m.get('titulo', '')[:60]})")
        est.salvar()


def teste(cfg: Config):
    import requests
    ok = True
    try:
        from maquina.twitch import Twitch
        tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
        log(f"Twitch OK — jogos encontrados: {list(tw.ids_jogos(cfg.jogos).values())}")
    except BaseException as e:
        ok = False
        log(f"Twitch FALHOU: {e}")
    for canal in cfg.canais:
        try:
            from maquina.youtube import YouTube
            nome = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token).nome_do_canal()
            log(f"YouTube [{canal.id}] OK — conectado ao canal: {nome}")
        except Exception as e:
            if canal.ativo:
                ok = False
            log(f"YouTube [{canal.id}] {'FALHOU' if canal.ativo else 'ainda sem chave (canal inativo)'}: {str(e)[:150]}")
    try:
        r = requests.post(f"{cfg.ia_endereco}/api/generate", timeout=300,
                          json={"model": cfg.ia_modelo, "prompt": "Responda só: ok", "stream": False})
        log(f"IA (Ollama) OK — respondeu: {r.json().get('response', '')[:40]!r}")
    except Exception as e:
        log(f"IA (Ollama) indisponível — a máquina usa o plano B com regras: {str(e)[:100]}")
    if not ok:
        sys.exit(1)


def simular(cfg: Config, video: str, canal_id: str = "br"):
    """Edita um vídeo local de ponta a ponta (sem Twitch/YouTube) para conferir o resultado."""
    from maquina import cerebro, compilado, editar, thumb
    from maquina.baixar import baixar_momento
    from maquina.transcrever import texto_com_tempos, transcrever
    canal = cfg.canal(canal_id)
    bruto = Path(video)
    dur = editar.info_video(bruto)[2]
    m = {"id": bruto.stem, "video_id": None, "inicio": 0.0, "fim": dur, "titulos_chat": ["teste"], "streamer": "teste"}
    palavras = transcrever(bruto, canal.idioma, cfg.whisper) if "--sem-whisper" not in sys.argv else []
    d = cerebro.decidir(m, palavras, texto_com_tempos(palavras), "Coringa", canal.idioma,
                        cfg.duracao_min, cfg.duracao_max, cfg.ia_endereco, cfg.ia_modelo)
    final = PASTA_PRONTOS / f"sim_{bruto.stem}.mp4"
    info = editar.editar_short(bruto, d["inicio"], d["fim"], palavras, final, RAIZ / canal.marca, canal.cor_destaque)
    pico = editar.momento_mais_alto(bruto, d["inicio"], d["fim"])
    thumb.gerar_thumb(editar.frame_em(bruto, pico), final.with_suffix(".jpg"), d["gancho"], canal.cor_destaque,
                      info["webcam"])
    log(f"pronto: {final} | layout {info['layout']} | {d}")


def acao_painel(cfg: Config, a):
    """Botões do painel visual. a.alvo = nome da ação."""
    from maquina import painel
    acao = a.alvo
    if acao == "postei":
        painel.marcar_postado(cfg, a.id, a.quando)   # a.quando = link do vídeo no YouTube (opcional)
    elif acao == "descartar":
        painel.descartar(cfg, a.id)
    elif acao == "priorizar":
        painel.priorizar(cfg, a.id)
    elif acao == "bloquear":
        painel.bloquear(a.login)
    elif acao == "desbloquear":
        painel.desbloquear(a.login)
    elif acao == "apagar":
        painel.bloquear(a.login)
        apagar(carregar(), a.login)
    elif acao == "adicionar":
        painel.adicionar_streamer(a.canal, a.login, a.nome)
    elif acao == "remover":
        painel.remover_streamer(a.canal, a.login)
    else:
        raise SystemExit(f"ação desconhecida: {acao}")


def main():
    p = argparse.ArgumentParser(description="Máquina de cortes GTA 6")
    p.add_argument("comando", choices=["cacar", "reacts", "fila", "produzir", "numeros", "painel", "sincronizar", "compilado", "bloquear", "apagar", "teste", "simular", "noticias", "youtube_pedir", "youtube_processar", "youtube_auto", "narrado", "postar_narrado", "pendentes", "contagem"])
    p.add_argument("alvo", nargs="?", default="")
    p.add_argument("--canal", default="br")
    p.add_argument("--sem-whisper", action="store_true")
    p.add_argument("--id", default="")
    p.add_argument("--login", default="")
    p.add_argument("--nome", default="")
    p.add_argument("--quando", default="")
    p.add_argument("--evento", default="")
    p.add_argument("--links", default="", help="links de posts do X separados por espaço")
    a = p.parse_args()
    cfg = carregar()
    if a.comando == "cacar":
        fazer_cacada(cfg)
    elif a.comando == "fila":
        print("sim" if tem_trabalho(cfg) else "nao")
    elif a.comando == "produzir":
        produzir(cfg)
    elif a.comando == "numeros":
        from maquina import painel
        painel.atualizar_numeros(cfg)
        painel.limpar_thumbs()
    elif a.comando == "painel":
        acao_painel(cfg, a)
    elif a.comando == "sincronizar":
        from maquina.sincronizar import sincronizar
        sincronizar(a.alvo or "Memória da máquina")
    elif a.comando == "compilado":
        fazer_compilado(cfg, a.alvo or "dia", a.evento)
    elif a.comando == "reacts":
        buscar_series(cfg, a.evento)
    elif a.comando == "bloquear":
        bloquear(a.alvo)
    elif a.comando == "apagar":
        apagar(cfg, a.alvo)
    elif a.comando == "teste":
        teste(cfg)
    elif a.comando == "narrado":
        fazer_narrado(cfg, a.alvo)
    elif a.comando == "postar_narrado":
        postar_narrado(cfg, a.alvo)
    elif a.comando == "pendentes":
        so_pendentes(cfg)
    elif a.comando == "youtube_pedir":
        from maquina import youtube_fonte
        youtube_fonte.pedir([l for l in re.split(r"[\s,]+", a.links) if l], a.evento or "cortes")
    elif a.comando == "youtube_processar":
        from maquina import youtube_fonte
        youtube_fonte.processar(cfg)
    elif a.comando == "contagem":
        fazer_contagem(cfg)
    elif a.comando == "youtube_auto":
        from maquina import youtube_auto
        youtube_auto.rodar(cfg)
    elif a.comando == "noticias":
        fazer_noticias(cfg, [l for l in re.split(r"[\s,]+", a.links) if re.search(r"(x|twitter)\.com/.+/status/\d+", l)])
    elif a.comando == "simular":
        simular(cfg, a.alvo, a.canal)


if __name__ == "__main__":
    main()
