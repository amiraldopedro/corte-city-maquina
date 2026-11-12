"""Máquina de cortes GTA 6 — comandos:

  python main.py cacar                   consulta a Twitch e enche a fila de momentos
  python main.py fila                    responde "sim" se há Short para produzir agora
  python main.py produzir                monta os Shorts da fila e posta
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
    return novos


# ====================================================================== produzir
def postados_hoje(est: Estado, canal: Canal) -> int:
    tz = ZoneInfo(canal.fuso)
    hoje = datetime.now(tz).date()
    n = 0
    for m in est.momentos.values():
        if m["status"] == "postado" and m.get("tipo", "short") == "short" and m.get("postado_em"):
            if datetime.fromisoformat(m["postado_em"]).astimezone(tz).date() == hoje:
                n += 1
    return n


def descricao_short(canal: Canal, titulo: str, login: str) -> str:
    return (f"{titulo}\n\n{LIVE[canal.idioma]}: https://twitch.tv/{login}\n\n{AVISO[canal.idioma]}\n\n"
            + " ".join(canal.hashtags))


def produzir_um(cfg: Config, canal: Canal, est: Estado, m: dict, yt) -> bool:
    from maquina import cerebro, compilado, editar, thumb
    from maquina.baixar import baixar_momento
    from maquina.transcrever import texto_com_tempos, transcrever
    nome = cfg.nome_streamer(m["streamer"])
    log(f"  produzindo {m['id']} ({nome}, {m['n_clipes']} clipes, {m['views']} views)")
    bruto = baixar_momento(m)
    palavras = transcrever(bruto, canal.idioma, cfg.whisper)
    d = cerebro.decidir(m, palavras, texto_com_tempos(palavras), nome, canal.idioma,
                        cfg.duracao_min, cfg.duracao_max, cfg.ia_endereco, cfg.ia_modelo)
    log(f"    cérebro ({d['fonte']}): {d['titulo']} | gancho {d['gancho']} | {d['inicio']}-{d['fim']}s")
    if not d["usar"]:
        est.atualizar(m["id"], status="descartado", motivo=d["motivo"])
        log(f"    descartado: {d['motivo']}")
        return False

    final = PASTA_PRONTOS / f"{m['id']}.mp4"
    info = editar.editar_short(bruto, d["inicio"], d["fim"], palavras, final, RAIZ / canal.marca, canal.cor_destaque)
    pico = editar.momento_mais_alto(bruto, d["inicio"], d["fim"])
    capa = thumb.gerar_thumb(editar.frame_em(bruto, pico), final.with_suffix(".jpg"), d["gancho"],
                             canal.cor_destaque, info["webcam"])
    from maquina.painel import guardar_thumb
    guardar_thumb(capa, m["id"])

    titulo = ("[TESTE] " if m.get("teste") else "") + d["titulo"]
    publicar_em = None
    if canal.modo == "automatico" and not m.get("teste"):
        from maquina.youtube import proximo_horario
        ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
        publicar_em = proximo_horario(canal.horarios, canal.fuso, ocupados)
    tags = ["gta 6", "gta vi", "gta 6 clips", nome.lower(), f"{nome.lower()} gta 6"]
    vid = yt.enviar(final, titulo, descricao_short(canal, titulo, m["streamer"]), tags, canal.idioma,
                    publicar_em, capa)
    yt.por_na_playlist(vid, canal.playlists.get("shorts", ""))
    est.atualizar(m["id"], status="postado", tipo="short", youtube_id=vid, titulo=titulo, gancho=d["gancho"],
                  corte=[d["inicio"], d["fim"]], publicar_em=publicar_em, postado_em=agora(),
                  layout=info["layout"], cerebro=d["fonte"], nome=nome,
                  duracao=round(d["fim"] - d["inicio"], 1), prioridade=False)
    quando = f"agendado para {publicar_em}" if publicar_em else "PRIVADO (aguardando sua revisão)"
    log(f"    ✅ https://youtu.be/{vid} — {quando}")
    return True


def fazer_cacada(cfg: Config):
    """Etapa leve: só consulta a Twitch e guarda os momentos novos na fila."""
    from maquina.twitch import Twitch
    tw = Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)
    for canal in cfg.canais_ativos():
        log(f"== {canal.nome}: caçando clipes")
        est = Estado(canal.id)
        if TESTE:
            for x in est.momentos.values():
                if x.get("teste") and x["status"] in ("erro", "descartado") and not x.get("youtube_id"):
                    x["status"] = "novo"
        try:
            log(f"  {cacar(cfg, canal, est, tw)} momentos novos na fila")
        finally:
            est.salvar()


def tem_trabalho(cfg: Config) -> bool:
    """Existe algum canal com momento na fila e meta do dia ainda aberta?"""
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        fila = [m for m in est.por_status("novo") if m["streamer"] not in cfg.bloqueados]
        if fila and (TESTE or postados_hoje(est, canal) < len(canal.horarios)):
            return True
    return False


def produzir(cfg: Config):
    """Etapa pesada: baixa, transcreve, edita e posta (até a meta diária de cada canal)."""
    from maquina.youtube import YouTube
    falhou = False
    for canal in cfg.canais_ativos():
        log(f"== {canal.nome} ({canal.modo})")
        est = Estado(canal.id)
        try:
            limite = 1 if TESTE else len(canal.horarios) - postados_hoje(est, canal)
            if limite <= 0:
                log("  meta de Shorts de hoje já cumprida")
                continue
            yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
            feitos = tentativas = 0
            for m in est.por_status("novo"):
                if TESTE and not m.get("teste"):
                    continue
                if feitos >= (1 if TESTE else min(limite, cfg.max_por_rodada)) or tentativas >= 4:
                    break
                if m["streamer"] in cfg.bloqueados:
                    est.atualizar(m["id"], status="descartado", motivo="streamer bloqueado")
                    continue
                tentativas += 1
                try:
                    feitos += produzir_um(cfg, canal, est, m, yt)
                except Exception as e:
                    est.atualizar(m["id"], status="erro", erro=str(e)[:300])
                    log(f"    ❌ erro: {str(e)[:300]}")
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
def fazer_compilado(cfg: Config, tipo: str):
    from maquina import cerebro, compilado, editar, thumb
    from maquina.baixar import baixar_momento
    from maquina.transcrever import texto_com_tempos, transcrever
    from maquina.youtube import YouTube, proximo_horario
    for canal in cfg.canais_ativos():
        est = Estado(canal.id)
        dias = 7 if tipo == "top10" else 1
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
        candidatos = [m for m in est.momentos.values()
                      if m.get("criado_em", "") >= desde and m["status"] in ("novo", "postado")
                      and m.get("tipo", "short") == "short" and m["streamer"] not in cfg.bloqueados]
        candidatos.sort(key=lambda m: -m.get("score", 0))
        qtd = 10 if tipo == "top10" else 12
        escolhidos = candidatos[:qtd]
        log(f"== {canal.nome}: compilado {tipo} com {len(escolhidos)} momentos")
        if len(escolhidos) < 5:
            log("  poucos momentos, fica para a próxima")
            continue
        if tipo == "top10":
            escolhidos = list(reversed(escolhidos))  # contagem regressiva: #10 ... #1
        nomes = {s.login: s.nome for s in canal.streamers}
        data = datetime.now(ZoneInfo(canal.fuso)).strftime("%d/%m" if canal.idioma == "pt" else "%b %d")
        saida = PASTA_PRONTOS / f"{tipo}_{canal.id}_{datetime.now().strftime('%Y%m%d')}.mp4"
        usados = compilado.montar(escolhidos, nomes, tipo, canal.cor_destaque, RAIZ / canal.marca, saida)
        ordem_nomes = list(dict.fromkeys(nomes.get(m["streamer"], m["streamer"]) for m in reversed(usados)))
        titulo = cerebro.titulo_compilado(canal.idioma, tipo, ordem_nomes, data)

        melhor = usados[-1] if tipo == "top10" else usados[0]
        bruto = Path(compilado.PASTA_BRUTOS / f"{melhor['id']}.mp4")
        pico = editar.momento_mais_alto(bruto, 0, editar.info_video(bruto)[2])
        etiqueta = "TOP 10" if tipo == "top10" else ("MELHORES DO DIA" if canal.idioma == "pt" else "BEST OF THE DAY")
        capa = thumb.gerar_thumb(editar.frame_em(bruto, pico), saida.with_suffix(".jpg"),
                                 melhor.get("gancho") or cerebro.GANCHOS[canal.idioma][0], canal.cor_destaque,
                                 editar.achar_webcam(bruto, 0, editar.info_video(bruto)[2]), etiqueta)
        from maquina.painel import guardar_thumb
        cid = f"{tipo}_{datetime.now().strftime('%Y%m%d')}"
        guardar_thumb(capa, cid)
        creditos = "\n".join(f"• {n}: https://twitch.tv/{l}" for l, n in nomes.items()
                             if any(m["streamer"] == l for m in usados))
        descricao = f"{titulo}\n\n{LIVE[canal.idioma]}:\n{creditos}\n\n{AVISO[canal.idioma]}\n\n#gta6 #gtavi"
        publicar_em = None
        if canal.modo == "automatico":
            tz = ZoneInfo(canal.fuso)
            ocupados = {x.get("publicar_em") for x in est.momentos.values() if x.get("publicar_em")}
            publicar_em = proximo_horario([canal.horario_compilado], canal.fuso, ocupados)
        yt = YouTube(cfg.yt_client_id, cfg.yt_client_secret, canal.refresh_token)
        vid = yt.enviar(saida, titulo, descricao, ["gta 6", "gta vi", "gta 6 best moments", *ordem_nomes[:5]],
                        canal.idioma, publicar_em, capa)
        yt.por_na_playlist(vid, canal.playlists.get("top10" if tipo == "top10" else "compilado", ""))
        est.momentos[cid] = {"id": cid, "streamer": "*", "canal": canal.id, "tipo": tipo, "status": "postado",
                             "youtube_id": vid, "titulo": titulo, "itens": [m["id"] for m in usados],
                             "streamers": sorted({m["streamer"] for m in usados}),
                             "publicar_em": publicar_em, "postado_em": agora(), "criado_em": agora()}
        est.salvar()
        log(f"  ✅ https://youtu.be/{vid}")


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
    if acao == "publicar":
        painel.publicar(cfg, a.id, a.quando)
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
    p.add_argument("comando", choices=["cacar", "fila", "produzir", "numeros", "painel", "compilado", "bloquear", "apagar", "teste", "simular"])
    p.add_argument("alvo", nargs="?", default="")
    p.add_argument("--canal", default="br")
    p.add_argument("--sem-whisper", action="store_true")
    p.add_argument("--id", default="")
    p.add_argument("--login", default="")
    p.add_argument("--nome", default="")
    p.add_argument("--quando", default="")
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
    elif a.comando == "compilado":
        fazer_compilado(cfg, a.alvo or "dia")
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
