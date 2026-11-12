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
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from maquina.config import PASTA_PRONTOS, RAIZ, Canal, Config, carregar
from maquina.estado import Estado, agora
from maquina.momentos import agrupar

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
        clipes = [c for c in tw.clipes(u["id"], cfg.janela_busca_horas) if not est.clipe_visto(c["id"])]
        momentos = agrupar(clipes, jogos, s.login, canal.id, cfg.minimo_clipes, cfg.minimo_views,
                           jogos_palavra, cfg.palavras)
        for m in momentos:
            if TESTE:
                m["teste"] = True
            if est.inserir(m):
                novos += 1
            est.marcar_clipes(m["clipe_ids"])
        log(f"  {s.nome}: {len(clipes)} clipes novos, {len(momentos)} momentos")
    novos += descobrir(cfg, canal, est, tw, {s.login for s in streamers})
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
            if est.inserir(m):
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
    idioma, minimo = d.get("idioma", canal.idioma), int(d.get("min_views", 300))
    por_streamer: dict[str, list] = {}
    for gid in jogos:
        for c in tw.clipes(game_id=gid, horas=cfg.janela_busca_horas, maximo=300):
            login = (c.get("broadcaster_name") or "").lower().replace(" ", "")
            if (c.get("language") or "")[:2] != idioma or c.get("view_count", 0) < minimo or est.clipe_visto(c["id"]):
                continue
            if not login or login in ja_vistos or login in cfg.bloqueados:
                continue
            c["_nome"] = c.get("broadcaster_name") or login
            por_streamer.setdefault(login, []).append(c)
    novos = 0
    for login, clipes in por_streamer.items():
        for m in agrupar(clipes, jogos, login, canal.id, 1, minimo):
            m["nome"] = clipes[0]["_nome"]
            m["descoberto"] = True
            if est.inserir(m):
                novos += 1
            est.marcar_clipes(m["clipe_ids"])
    log(f"  descoberta por jogo: {sum(len(v) for v in por_streamer.values())} clipes de {len(por_streamer)} streamers, {novos} momentos novos")
    return novos


# ====================================================================== produzir
MAX_ESPERANDO = 9  # se você não postar, a máquina para de fazer vídeo novo (e economiza minutos do GitHub)


def postados_hoje(est: Estado, canal: Canal) -> int:
    """Shorts que a máquina deixou prontos hoje (meta diária = número de horários do canal)."""
    tz = ZoneInfo(canal.fuso)
    hoje = datetime.now(tz).date()
    n = 0
    for m in est.momentos.values():
        quando = m.get("feito_em") or m.get("postado_em")
        if m.get("teste"):
            continue  # vídeo de teste não conta na meta
        if m.get("tipo", "short") == "short" and m["status"] in ("pronto", "postado") and quando:
            if datetime.fromisoformat(quando).astimezone(tz).date() == hoje:
                n += 1
    return n


def esperando(est: Estado) -> int:
    return sum(1 for m in est.momentos.values() if m["status"] == "pronto")


def link_live(login: str, plataforma: str = "") -> str:
    return f"https://kick.com/{login}" if plataforma == "kick" else f"https://twitch.tv/{login}"


def descricao_short(canal: Canal, titulo: str, login: str, plataforma: str = "", resumo: str = "") -> str:
    # as 2 primeiras linhas são as que o YouTube mostra e usa na busca
    topo = f"{titulo}\n{resumo}" if resumo else titulo
    return (f"{topo}\n\n{LIVE[canal.idioma]}: {link_live(login, plataforma)}\n\n{AVISO[canal.idioma]}\n\n"
            + " ".join(canal.hashtags))


def produzir_um(cfg: Config, canal: Canal, est: Estado, m: dict, yt) -> bool:
    from maquina import cerebro, compilado, editar, thumb
    from maquina.baixar import baixar_momento
    from maquina.transcrever import texto_com_tempos, transcrever
    nome = cfg.nome_streamer(m["streamer"], m.get("nome", ""))
    log(f"  produzindo {m['id']} ({nome}, {m['n_clipes']} clipes, {m['views']} views)")
    bruto = baixar_momento(m)
    if bruto.with_suffix(".clipe").exists():  # usou o clipe do público: a janela é o clipe inteiro
        m = {**m, "inicio": 0.0, "fim": editar.info_video(bruto)[2], "video_id": None}
    palavras = transcrever(bruto, canal.idioma, cfg.whisper)
    d = cerebro.decidir(m, palavras, texto_com_tempos(palavras), nome, canal.idioma,
                        cfg.duracao_min, cfg.duracao_max, cfg.ia_endereco, cfg.ia_modelo)
    log(f"    cérebro ({d['fonte']}): {d['titulo']} | gancho {d['gancho']} | {d['inicio']}-{d['fim']}s")
    if not d["usar"]:
        est.atualizar(m["id"], status="descartado", motivo=d["motivo"])
        log(f"    descartado: {d['motivo']}")
        return False

    final = PASTA_PRONTOS / f"{m['id']}.mp4"
    voz = None
    if m.get("evento"):  # react a trailer: a música da Rockstar faz o YouTube silenciar o Short
        from maquina.voz import tentar_isolar
        voz = tentar_isolar(bruto)
        log(f"    voz isolada: {'sim' if voz else 'não (vai com o áudio original)'}")
    pico = editar.momento_mais_alto(bruto, d["inicio"], d["fim"])
    info = editar.editar_short(bruto, d["inicio"], d["fim"], palavras, final, RAIZ / canal.marca, canal.cor_destaque,
                               chamada=d.get("chamada", ""), pico=pico, audio=voz)
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
    arquivos = entregar(final, capa, m["id"])   # sempre fica uma cópia para baixar (reserva)
    if canal.postar == "automatico" and not m.get("teste") and yt is not None:
        from maquina.youtube import proximo_horario
        ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
        publicar_em = proximo_horario(canal.horarios, canal.fuso, ocupados)
        descricao = descricao_short(canal, titulo, m["streamer"], m.get("plataforma", ""), resumo)
        vid = yt.enviar(final, titulo, descricao, tags, canal.idioma, publicar_em, capa)
        yt.por_na_playlist(vid, canal.playlists.get("shorts", ""))
        est.atualizar(m["id"], status="postado", tipo="short", jogo=m.get("jogo", ""), titulo=titulo,
                      gancho=d["gancho"], descricao=descricao, tags=tags, youtube_id=vid, publicar_em=publicar_em,
                      postado_em=agora(), feito_em=agora(), corte=[d["inicio"], d["fim"]], layout=info["layout"],
                      cerebro=d["fonte"], nome=nome, duracao=round(d["fim"] - d["inicio"], 1), prioridade=False,
                      **arquivos)
        log(f"    ✅ enviado e agendado para {publicar_em}: https://youtu.be/{vid}")
        return True
    est.atualizar(m["id"], status="pronto", tipo="short", jogo=m.get("jogo", ""), titulo=titulo, gancho=d["gancho"],
                  descricao=descricao_short(canal, titulo, m["streamer"], m.get("plataforma", ""), resumo), tags=tags,
                  playlist=canal.playlists.get("shorts", ""), corte=[d["inicio"], d["fim"]], feito_em=agora(),
                  layout=info["layout"], cerebro=d["fonte"], nome=nome,
                  duracao=round(d["fim"] - d["inicio"], 1), prioridade=False, **arquivos)
    log(f"    ✅ pronto para postar: {titulo}")
    log(f"       baixar: {arquivos['video_url']}")
    return True


def fazer_cacada(cfg: Config):
    """Etapa leve: só consulta a Twitch e guarda os momentos novos na fila."""
    from maquina.twitch import Twitch
    tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
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
                    if est.inserir(m):
                        novos += 1
                    est.marcar_clipes(m["clipe_ids"])
            log(f"  {canal.nome} · {ev['nome']}: {sum(len(v) for v in por.values())} clipes de {len(por)} streamers → {novos} reacts na fila")
        est.salvar()


def tem_trabalho(cfg: Config) -> bool:
    """Existe algum canal com momento na fila e meta do dia ainda aberta?"""
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        fila = [m for m in est.por_status("novo") if m["streamer"] not in cfg.bloqueados
                and TESTE == bool(m.get("teste"))]
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
            limite = 1 if TESTE else len(canal.horarios) - postados_hoje(est, canal)
            if limite <= 0:
                log("  meta de Shorts de hoje já cumprida")
                continue
            if not TESTE and canal.postar != "automatico" and esperando(est) >= MAX_ESPERANDO:
                log(f"  já tem {esperando(est)} vídeos prontos esperando você postar — não vou fazer mais agora")
                continue
            yt = None
            if canal.postar == "automatico" and not TESTE:
                from maquina.youtube import YouTube
                yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
            feitos = tentativas = 0
            for m in est.por_status("novo"):
                if TESTE != bool(m.get("teste")):
                    continue
                quantos = int(os.getenv("QUANTOS") or cfg.max_por_rodada)
                if feitos >= (1 if TESTE else min(limite, quantos)) or tentativas >= quantos + 3:
                    break
                if m["streamer"] in cfg.bloqueados:
                    est.atualizar(m["id"], status="descartado", motivo="streamer bloqueado")
                    continue
                tentativas += 1
                try:
                    feitos += produzir_um(cfg, canal, est, m, yt)
                except Exception as e:
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
        assunto = (m.get("titulo") or "").replace(nome, "").strip(" :-–|") or (m.get("evento") or "")
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
        vid = yt.enviar(saida, titulo, descricao, tags, canal.idioma, publicar_em, capa)
        yt.por_na_playlist(vid, playlist)
        envio = {"status": "postado", "youtube_id": vid, "publicar_em": publicar_em, "postado_em": agora()}
        log(f"  ✅ enviado e agendado para {publicar_em}: https://youtu.be/{vid}")
    est.momentos[cid] = {"id": cid, "streamer": "*", "canal": canal.id, "tipo": tipo, "status": "pronto",
                         "titulo": titulo, "descricao": descricao, "tags": tags, "playlist": playlist,
                         "feito_em": agora(), "criado_em": agora(), **extra, **arquivos, **envio}
    est.salvar()
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
        if tipo == "top10":
            escolhidos = list(reversed(escolhidos[:qtd]))  # contagem regressiva: #10 ... #1
        nomes = {s.login: s.nome for s in canal.streamers + canal.kick}
        nomes.update({m["streamer"]: m["nome"] for m in escolhidos if m.get("nome") and m["streamer"] not in nomes})
        data = datetime.now(ZoneInfo(canal.fuso)).strftime("%d/%m" if canal.idioma == "pt" else "%b %d")
        saida = PASTA_PRONTOS / f"{tipo}_{canal.id}_{datetime.now().strftime('%Y%m%d')}.mp4"
        usados = compilado.montar(escolhidos if tipo == "top10" else escolhidos, nomes, tipo, canal.cor_destaque,
                                  RAIZ / canal.marca, saida)
        if tipo != "top10":
            usados = usados[:qtd]
        ordem_nomes = list(dict.fromkeys(nomes.get(m["streamer"], m["streamer"]) for m in reversed(usados)))
        titulo = cerebro.titulo_compilado(canal.idioma, tipo, ordem_nomes, data, evento)

        melhor = usados[-1] if tipo == "top10" else usados[0]
        bruto = Path(compilado.PASTA_BRUTOS / f"{melhor['id']}.mp4")
        pico = editar.momento_mais_alto(bruto, 0, editar.info_video(bruto)[2])
        etiqueta = "TOP 10" if tipo == "top10" else "REACTS" if tipo == "serie" else ("MELHORES DO DIA" if canal.idioma == "pt" else "BEST OF THE DAY")
        capa = thumb.gerar_thumb(editar.frame_em(bruto, pico), saida.with_suffix(".jpg"),
                                 melhor.get("gancho") or cerebro.GANCHOS[canal.idioma][0], canal.cor_destaque,
                                 editar.achar_webcam(bruto, 0, editar.info_video(bruto)[2]), etiqueta)
        from maquina.painel import guardar_thumb
        cid = f"{tipo}_{datetime.now().strftime('%Y%m%d')}" + (f"_{re.sub(r'[^a-z0-9]', '', evento.lower())[:20]}" if evento else "")
        guardar_thumb(capa, cid)
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
                      {"itens": [m["id"] for m in usados], "streamers": sorted({m["streamer"] for m in usados})})


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
                             if m.get("video_id") and m.get("criado_em", "") >= desde and not m.get("teste")
                             and m["status"] in ("novo", "pronto", "postado") and m.get("tipo", "short") == "short"
                             and m["streamer"] not in cfg.bloqueados and "longo" not in m.get("usado_em", [])],
                            key=lambda m: -m.get("score", 0))
        log(f"== {canal.nome}: corte longo ({len(candidatos)} candidatos)")
        for m in candidatos[:3]:
            ini = max(0.0, m["inicio"] - 150)
            fim = min(ini + 9 * 60, m["fim"] + 210)
            destino = compilado.PASTA_BRUTOS / f"longo_{m['id']}.mp4"
            try:
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
            palavras = transcrever(voz, canal.idioma, cfg.whisper)
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
            _postar_longo(cfg, canal, est, saida, capa, cid, "longo", t["titulo"], descricao, tags,
                          canal.playlists.get("compilado", ""), {"itens": [m["id"]], "streamers": [m["streamer"]]})
            break
        else:
            log("  nenhum momento com a live disponível para o corte longo")


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
    p.add_argument("comando", choices=["cacar", "reacts", "fila", "produzir", "numeros", "painel", "sincronizar", "compilado", "bloquear", "apagar", "teste", "simular"])
    p.add_argument("alvo", nargs="?", default="")
    p.add_argument("--canal", default="br")
    p.add_argument("--sem-whisper", action="store_true")
    p.add_argument("--id", default="")
    p.add_argument("--login", default="")
    p.add_argument("--nome", default="")
    p.add_argument("--quando", default="")
    p.add_argument("--evento", default="")
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
    elif a.comando == "simular":
        simular(cfg, a.alvo, a.canal)


if __name__ == "__main__":
    main()
