"""Carrega config.yaml + segredos (variáveis de ambiente / Secrets do GitHub)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
PASTA_TRABALHO = Path(os.getenv("PASTA_TRABALHO", RAIZ / "trabalho"))
PASTA_BRUTOS = PASTA_TRABALHO / "brutos"
PASTA_PRONTOS = PASTA_TRABALHO / "prontos"
PASTA_ESTADO = RAIZ / "estado"
FONTES = RAIZ / "assets" / "fonts"


@dataclass
class Streamer:
    login: str
    nome: str
    canal_id: str = ""


@dataclass
class Canal:
    id: str
    nome: str
    ativo: bool
    modo: str
    idioma: str
    marca: str
    cor_destaque: str
    fuso: str
    horarios: list[str]
    horario_compilado: str
    hashtags: list[str]
    playlists: dict
    streamers: list[Streamer] = field(default_factory=list)
    postar: str = "manual"
    descobrir: dict = field(default_factory=dict)
    kick: list[Streamer] = field(default_factory=list)
    horario_longo: str = "15:00"
    gringos: dict = field(default_factory=dict)
    horarios_longos: list[str] = field(default_factory=list)

    @property
    def refresh_token(self) -> str:
        return os.getenv(f"YT_REFRESH_TOKEN_{self.id.upper()}", "")


@dataclass
class Config:
    jogos: list[str]
    jogos_com_palavra: list[str]
    palavras: list[str]
    janela_busca_horas: int
    minimo_clipes: int
    minimo_views: int
    duracao_min: int
    duracao_max: int
    max_por_rodada: int
    ia_modelo: str
    ia_endereco: str
    whisper: str
    canais: list[Canal]
    bloqueados: set[str]

    um_clipe_views: int = 300
    clipes_quentes: int = 6
    nota_minima: int = 5
    max_por_streamer_dia: int = 2
    lancado: bool = False
    noticias: dict = field(default_factory=dict)
    youtube_auto: dict = field(default_factory=dict)
    modelar: dict = field(default_factory=dict)
    apelidos: dict = field(default_factory=dict)
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    yt_client_id: str = ""
    yt_client_secret: str = ""

    def canais_ativos(self) -> list[Canal]:
        return [c for c in self.canais if c.ativo]

    def canal(self, canal_id: str) -> Canal:
        for c in self.canais:
            if c.id == canal_id:
                return c
        raise KeyError(f"Canal '{canal_id}' não existe no config.yaml")

    def streamers_do(self, canal: Canal) -> list[Streamer]:
        return [s for s in canal.streamers if s.login not in self.bloqueados]

    def nome_streamer(self, login: str, padrao: str = "") -> str:
        for c in self.canais:
            for s in c.streamers + c.kick:
                if s.login == login:
                    return s.nome
        for chave in (login, padrao):
            if chave and chave.lower() in self.apelidos:
                return self.apelidos[chave.lower()]
        return limpar_nome(padrao or login)


_SOBRAS = r"(?:oficial|official|lives?|cortes|clipes|clips|tv|gta\s?6|gta\s?vi|gameplays?)"


def limpar_nome(nome: str) -> str:
    """'Cortes do Davy Jones [OFICIAL]' -> 'Davy Jones'; 'BisteconeLive' -> 'Bistecone'."""
    import re
    original = (nome or "").strip()
    t = re.sub(r"[\[(（【].*?[\])）】]", " ", original)                     # [OFICIAL], (Oficial)
    t = re.sub(r"^\s*(?:cortes|canal|clipes|melhores momentos)\s+d[oae]s?\s+", "", t, flags=re.I)
    t = re.sub(r"^\s*cortesd[oa](?=[A-Z])", "", t)                         # CortesdoDavyJones
    t = re.sub(rf"\b{_SOBRAS}\b", " ", t, flags=re.I)                      # palavra solta
    if " " not in t.strip():                                               # nome colado: BisteconeLive, DavyJonesGTA6
        colado = re.sub(r"(?<=[A-Za-zà-ú]{4})(?:Lives?|Official|Oficial|oficial|official|GTA6|TV|Cortes)$", "", t.strip())
        t = colado
    t = re.sub(r"\s+", " ", t).strip(" -|:·")
    return t if len(t) >= 3 else original


def carregar(caminho: str | Path = RAIZ / "config.yaml") -> Config:
    bruto = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    canais = []
    for c in bruto.get("canais", []):
        canal = Canal(
            id=c["id"], nome=c.get("nome", c["id"]), ativo=bool(c.get("ativo", True)),
            modo=c.get("modo", "revisao"), idioma=c.get("idioma", "pt"),
            marca=c.get("marca", ""), cor_destaque=c.get("cor_destaque", "#C8FF2E"),
            fuso=c.get("fuso", "America/Sao_Paulo"),
            horarios=list(c.get("horarios", ["12:00", "18:00", "21:00"])),
            horario_compilado=c.get("horario_compilado", "19:30"),
            horario_longo=c.get("horario_longo", "15:00"),
            hashtags=list(c.get("hashtags", [])), playlists=dict(c.get("playlists", {})),
            postar=c.get("postar", "manual"), descobrir=dict(c.get("descobrir") or {}),
            gringos=dict(c.get("gringos") or {}),
            horarios_longos=list(c.get("horarios_longos") or []),
        )
        for s in c.get("streamers", []):
            canal.streamers.append(Streamer(login=s["login"].lower(), nome=s.get("nome", s["login"]), canal_id=canal.id))
        for s in c.get("kick", []) or []:
            canal.kick.append(Streamer(login=s["login"].lower(), nome=s.get("nome", s["login"]), canal_id=canal.id))
        canais.append(canal)

    for p in (PASTA_BRUTOS, PASTA_PRONTOS, PASTA_ESTADO):
        p.mkdir(parents=True, exist_ok=True)

    # Modo lançamento: do dia do lançamento em diante, os valores do bloco "lancamento" substituem os normais
    lancado = False
    lanc = bruto.get("lancamento") or {}
    if lanc.get("data"):
        from datetime import date, datetime
        from zoneinfo import ZoneInfo
        hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        forcado = os.getenv("MODO_LANCAMENTO", "")
        lancado = forcado == "1" or (forcado != "0" and hoje >= date.fromisoformat(str(lanc["data"])))
    if lancado:
        for chave in ("janela_busca_horas", "max_por_rodada", "momento_minimo", "jogos", "nota_minima",
                      "max_por_streamer_dia"):
            if chave in lanc:
                bruto[chave] = lanc[chave]
        for canal in canais:
            extra = (lanc.get("canais") or {}).get(canal.id) or {}
            if extra.get("horarios"):
                canal.horarios = list(extra["horarios"])
            if extra.get("horarios_longos"):
                canal.horarios_longos = list(extra["horarios_longos"])
            if extra.get("descobrir_jogos"):
                canal.descobrir["jogos"] = list(extra["descobrir_jogos"])
            if extra.get("descobrir_min_views"):
                canal.descobrir["min_views"] = int(extra["descobrir_min_views"])

    # canal sem a chave do YouTube (ex.: Clip City antes de autorizar): faz tudo, mas deixa pronto no Studio
    # em vez de tentar postar e quebrar a rodada inteira
    if os.getenv("GITHUB_ACTIONS"):
        for canal in canais:
            if canal.postar == "automatico" and not canal.refresh_token:
                canal.postar = "revisao"
    mm, du, ia = bruto.get("momento_minimo", {}), bruto.get("duracao", {}), bruto.get("ia", {})
    return Config(
        jogos=list(bruto.get("jogos", ["Grand Theft Auto VI"])),
        jogos_com_palavra=list((bruto.get("jogos_com_palavra") or {}).get("jogos", [])),
        palavras=[p.lower() for p in (bruto.get("jogos_com_palavra") or {}).get("palavras", [])],
        janela_busca_horas=int(bruto.get("janela_busca_horas", 24)),
        noticias=dict(bruto.get("noticias") or {}),
        youtube_auto=dict(bruto.get("youtube_auto") or {}),
        modelar=dict(bruto.get("modelar") or {}),
        apelidos={str(k).lower(): str(v) for k, v in (bruto.get("apelidos") or {}).items()},
        minimo_clipes=int(mm.get("clipes", 2)), minimo_views=int(mm.get("views", 150)),
        um_clipe_views=int(mm.get("um_clipe_views", 3 * int(mm.get("views", 150)))), lancado=lancado,
        clipes_quentes=int(mm.get("quentes", 6)),
        nota_minima=int(bruto.get("nota_minima", 5)), max_por_streamer_dia=int(bruto.get("max_por_streamer_dia", 2)),
        duracao_min=int(du.get("minimo", 15)), duracao_max=int(du.get("maximo", 58)),
        max_por_rodada=int(bruto.get("max_por_rodada", 1)),
        ia_modelo=ia.get("modelo", "qwen2.5:3b"), ia_endereco=ia.get("endereco", "http://127.0.0.1:11434"),
        whisper=str(bruto.get("whisper", "small")),
        canais=canais,
        bloqueados={b.lower() for b in (bruto.get("bloqueados") or [])},
        twitch_client_id=os.getenv("TWITCH_CLIENT_ID", ""),
        twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
        yt_client_id=os.getenv("YT_CLIENT_ID", ""),
        yt_client_secret=os.getenv("YT_CLIENT_SECRET", ""),
    )
