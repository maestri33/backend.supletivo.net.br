#!/usr/bin/env bash
# ==============================================================================
# Script de Instalação Automatizada do Cloudflare Tunnel no Proxmox LXC
# ==============================================================================
set -euo pipefail

echo "==> [1/5] Atualizando repositórios e dependências..."
apt-get update -qq && apt-get install -y -qq curl wget ca-certificates logrotate

echo "==> [2/5] Criando usuário de sistema restrito cloudflared..."
if ! id -u cloudflared >/dev/null 2>&1; then
    useradd -r -s /usr/sbin/nologin -d /etc/cloudflared -m -c "Cloudflare Tunnel Service" cloudflared
fi

echo "==> [3/5] Baixando binário oficial .deb do cloudflared..."
ARCH=$(dpkg --print-architecture)
case "$ARCH" in
    amd64) DEB_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb" ;;
    arm64) DEB_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb" ;;
    *) echo "Arquitetura $ARCH não suportada." ; exit 1 ;;
esac

wget -q -O /tmp/cloudflared.deb "$DEB_URL"
dpkg -i /tmp/cloudflared.deb
rm -f /tmp/cloudflared.deb

echo "==> [4/5] Configurando diretórios /etc/cloudflared e /var/log/cloudflared..."
mkdir -p /etc/cloudflared /var/log/cloudflared
chown -R cloudflared:cloudflared /etc/cloudflared /var/log/cloudflared
chmod 750 /etc/cloudflared /var/log/cloudflared

echo "==> [5/5] Configurando rotação diária de logs (logrotate)..."
cat << 'EOF' > /etc/logrotate.d/cloudflared
/var/log/cloudflared/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 cloudflared cloudflared
    postrotate
        /bin/systemctl kill -s HUP --kill-who=main cloudflared.service 2>/dev/null || true
    endscript
}
EOF

echo "==> Instalação do cloudflared concluída com sucesso!"
cloudflared --version
