#!/bin/bash
# Instalador do Robô do YouTube da Corte City (roda uma vez no Mac).
# Uso: abra o Terminal e rode:  bash ~/Downloads/instalar_robo_youtube.sh
set -e
PASTA="$HOME/.corte-city"
AQUI="$(cd "$(dirname "$0")" && pwd)"
echo ""
echo "=== Robô do YouTube - Corte City ==="
echo ""

# 1) yt-dlp + ffmpeg prontos (sem Homebrew: ele não suporta mais Mac Intel e tenta compilar tudo)
BIN="$PASTA/bin"
mkdir -p "$BIN"
export PATH="$BIN:/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "Baixando o yt-dlp..."
curl -fsSL -o "$BIN/yt-dlp" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos
chmod +x "$BIN/yt-dlp"
xattr -d com.apple.quarantine "$BIN/yt-dlp" 2>/dev/null || true
if command -v ffmpeg >/dev/null 2>&1 && ffmpeg -version >/dev/null 2>&1; then
  echo "ffmpeg já está instalado: $(command -v ffmpeg)"
else
  echo "Baixando o ffmpeg..."
  if [ "$(uname -m)" = "arm64" ]; then
    curl -fsSL -o /tmp/ffmpeg.zip "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip"
  else
    curl -fsSL -o /tmp/ffmpeg.zip "https://evermeet.cx/ffmpeg/getrelease/zip"
  fi
  unzip -o -q /tmp/ffmpeg.zip -d "$BIN" && rm -f /tmp/ffmpeg.zip
  chmod +x "$BIN/ffmpeg"
  xattr -d com.apple.quarantine "$BIN/ffmpeg" 2>/dev/null || true
fi
"$BIN/yt-dlp" --version >/dev/null && echo "yt-dlp ok"
(command -v ffmpeg >/dev/null && ffmpeg -version >/dev/null 2>&1) && echo "ffmpeg ok"

# 2) Chave do GitHub (fica guardada nas Chaves do macOS, não em arquivo)
if [ "$1" = "--trocar-chave" ]; then
  security delete-generic-password -s corte-city-github >/dev/null 2>&1 || true
fi
if ! security find-generic-password -s corte-city-github -w >/dev/null 2>&1; then
  echo ""
  echo "Cole a mesma chave do GitHub que você usa no painel (ela não aparece enquanto você cola) e aperte Enter:"
  read -rs CHAVE
  echo ""
  case "$CHAVE" in
    github_pat_*|ghp_*) ;;
    *) echo "Isso não parece uma chave do GitHub (começa com github_pat_). Rode de novo."; exit 1 ;;
  esac
  security add-generic-password -a "$USER" -s corte-city-github -w "$CHAVE" -U
  unset CHAVE
  echo "Chave guardada nas Chaves do macOS."
fi

# 3) Escolhe o SSD (onde ficam os vídeos baixados e o registro do robô)
echo ""
echo "Discos conectados:"
DISCOS=()
for d in /Volumes/*; do
  n="$(basename "$d")"
  [ "$n" = "Macintosh HD" ] && continue
  [ -w "$d" ] || continue
  DISCOS+=("$d")
  echo "  ${#DISCOS[@]}) $n"
done
if [ ${#DISCOS[@]} -eq 0 ]; then
  echo "Nenhum SSD encontrado. Conecte o SSD e rode de novo (ou aperte Enter para usar o próprio Mac)."
  read -r _
  SSD="$PASTA"
elif [ ${#DISCOS[@]} -eq 1 ]; then
  SSD="${DISCOS[0]}/CorteCity"
  echo "Usando o único disco conectado: $(basename "${DISCOS[0]}")"
else
  while true; do
    echo "Digite SÓ o número do SSD (ex.: 1) e aperte Enter:"
    read -r N
    if [[ "$N" =~ ^[0-9]+$ ]] && [ "$N" -ge 1 ] && [ "$N" -le ${#DISCOS[@]} ]; then break; fi
    echo "Número inválido."
  done
  SSD="${DISCOS[$((N-1))]}/CorteCity"
fi
mkdir -p "$SSD" "$PASTA"
cp "$AQUI/robo_youtube.py" "$PASTA/robo_youtube.py"   # o robô mora no Mac (30 KB); os vídeos vão pro SSD
echo "Robô instalado em: $SSD"

# 4) Agenda para rodar a cada 15 minutos (enquanto o Mac estiver ligado)
# o launchd chama o python direto (sem bash no meio): assim o Acesso Total ao Disco dado ao python vale
PY="$(/usr/bin/python3 -c 'import sys; print(sys.executable)')"
PLIST="$HOME/Library/LaunchAgents/com.cortecity.robo-youtube.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cortecity.robo-youtube</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$PASTA/robo_youtube.py</string></array>
  <key>EnvironmentVariables</key><dict><key>CC_BASE</key><string>$SSD</string></dict>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$PASTA/saida.log</string>
  <key>StandardErrorPath</key><string>$PASTA/saida.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Pronto! O robô roda a cada 15 minutos enquanto o Mac estiver ligado."
echo "Pra ver o que ele fez:  cat \"$SSD/robo_youtube.log\""
echo "Se o macOS perguntar se o python3 pode acessar o disco removível, clique em Permitir."
echo "Pra desligar:           launchctl unload ~/Library/LaunchAgents/com.cortecity.robo-youtube.plist"
echo ""
