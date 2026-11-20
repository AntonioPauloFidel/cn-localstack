#!/usr/bin/env bash
# Instala o necessário para as atividades de LocalStack (rodar com sudo)
set -euo pipefail
dpkg --configure -a
apt-get update
apt-get install -y docker.io docker-compose-v2 python3-venv python3-pip zip unzip curl jq
systemctl enable --now docker
usermod -aG docker "${SUDO_USER:-fidel}"
docker --version
docker compose version
echo "OK - Docker instalado."
