# Máquina de Cortes GTA 6 — Corte City / Clip City

Robô 100% gratuito que roda sozinho no GitHub Actions:

1. **Caça** os clipes que o público fez na Twitch dos streamers da lista (a cada 4 horas).
2. Junta clipes do mesmo instante num **momento** e dá nota (muita gente clipando = momento bom).
3. **Baixa o trecho real da live** (VOD), **transcreve** a fala (faster-whisper) e a **IA gratuita** (Ollama, modelo `qwen2.5:3b`) escolhe o corte, o título e a palavra da thumb.
4. **Edita o Short** 1080x1920: webcam em cima e jogo embaixo (ou fundo desfocado quando não acha a webcam), legenda palavra por palavra, marca d'água do canal.
5. Faz a **thumb** automática e **posta** no YouTube, já na playlist certa.
6. Todo dia monta o **Melhores do Dia** (vídeo longo) e, no domingo, o **Top 10 da Semana**.

Se o Ollama falhar, a máquina usa regras simples e continua funcionando.

## Ritmo

| O quê | Quando |
|---|---|
| Shorts | 3 por dia em cada canal ativo (horários no `config.yaml`) |
| Melhores do Dia | todo dia ~17:40 (Brasília) |
| Top 10 da Semana | domingo ~10:20 (Brasília) |

## Modo revisão x automático

No `config.yaml`, cada canal tem `modo:`
- `revisao` → o vídeo sobe **privado**. Você assiste no YouTube Studio e publica/agenda se gostar. **(Fase 1)**
- `automatico` → o vídeo sobe já **agendado** nos horários do canal.

O Clip City começa com `ativo: false`. Para ligar, troque para `true`.

## Botões (aba **Actions** do GitHub)

- **Rodada (caçar + Shorts)** → roda sozinho a cada 4h. Dá para rodar na mão em *Run workflow*.
- **Compilado** → roda sozinho; na mão você escolhe `dia` ou `top10`.
- **Controle** → `testar conexões`, `bloquear streamer` ou `bloquear e apagar os vídeos dele` (digite o login da Twitch).

## Chaves que precisam ser colocadas (uma vez só)

Em **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | De onde vem |
|---|---|
| `TWITCH_CLIENT_ID` | dev.twitch.tv/console/apps → *Register Your Application* |
| `TWITCH_CLIENT_SECRET` | mesma página → *New Secret* |
| `YT_CLIENT_ID` | Google Cloud Console → Credenciais → ID do cliente OAuth (tipo *Aplicativo da Web*) |
| `YT_CLIENT_SECRET` | mesma tela |
| `YT_REFRESH_TOKEN_BR` | autorização do canal **Corte City** (OAuth Playground, passo abaixo) |
| `YT_REFRESH_TOKEN_EN` | autorização do canal **Clip City** (só na Fase 2) |

### Twitch
1. Entre em dev.twitch.tv/console/apps e clique em **Register Your Application**.
2. Nome: `corte-city-maquina` · OAuth Redirect URL: `http://localhost` · Categoria: *Application Integration* · Tipo: *Confidential*.
3. Copie o **Client ID** e gere um **New Secret**.

### YouTube
1. No Google Cloud Console (pode ser o mesmo projeto do Descifre), em **APIs e serviços → Credenciais**, crie um **ID do cliente OAuth** do tipo **Aplicativo da Web** com o URI de redirecionamento `https://developers.google.com/oauthplayground`.
2. Na **Tela de consentimento OAuth**, deixe o app **Em produção**. Em "Teste", a autorização vence em 7 dias.
3. Abra developers.google.com/oauthplayground → engrenagem ⚙️ → marque *Use your own OAuth credentials* e cole o ID e o segredo.
4. Na lista da esquerda, escreva os escopos `https://www.googleapis.com/auth/youtube.upload` e `https://www.googleapis.com/auth/youtube` → **Authorize APIs**.
5. Entre com sua conta e **escolha o canal Corte City** quando o Google perguntar qual canal.
6. Clique em **Exchange authorization code for tokens** e copie o **Refresh token** → secret `YT_REFRESH_TOKEN_BR`.
7. Repita os passos 4 a 6 escolhendo o **Clip City** para gerar o `YT_REFRESH_TOKEN_EN`.

Depois rode **Controle → testar conexões**. Ele mostra o nome do canal conectado a cada chave.

> Projetos do Google Cloud que ainda não passaram pela auditoria do YouTube só conseguem subir vídeos **privados**. Para a Fase 1 isso não atrapalha (você publica na mão). Para o modo automático, peça a auditoria em *YouTube API Services – Audit and Quota Extension*.

## Mudar coisas sem mexer em código

Tudo fica no `config.yaml`: streamers de cada canal, horários, quantos Shorts por dia, duração, modelo da IA, modo revisão/automático.

## Testar no computador (opcional)

```
pip install -r requirements.txt
python main.py simular meu_video.mp4      # edita um vídeo local e gera Short + thumb em trabalho/prontos/
```

## Custo

Zero, dentro dos 2.000 minutos/mês grátis do GitHub Actions para repositório privado (só o Corte City cabe folgado). Com os dois canais ativos pode passar um pouco, e o GitHub só cobra se você aumentar o limite de gastos.
