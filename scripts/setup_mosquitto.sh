#!/usr/bin/env bash
# ULTRON VISION — install + configure the Mosquitto broker ON the Jetson.
# Listens on 0.0.0.0:1883 so the Mother backend on the LAN can reach it.
# Run:  sudo bash scripts/setup_mosquitto.sh
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo bash scripts/setup_mosquitto.sh"
  exit 1
fi

echo ">>> Installing mosquitto + clients..."
apt-get update
apt-get install -y mosquitto mosquitto-clients

echo ">>> Writing /etc/mosquitto/conf.d/ultron.conf..."
cat > /etc/mosquitto/conf.d/ultron.conf <<'EOF'
# ULTRON VISION — LAN listener for Mother
# Home-LAN setup: anonymous is fine to start. To add auth later:
#   mosquitto_passwd -c /etc/mosquitto/passwd ultron
#   then set: allow_anonymous false / password_file /etc/mosquitto/passwd
# and fill mqtt.username/password in jetson/config.yaml + Mother's config.
listener 1883 0.0.0.0
allow_anonymous true
EOF

echo ">>> Enabling + restarting mosquitto..."
systemctl enable mosquitto
systemctl restart mosquitto

# Open the firewall if ufw is active
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  echo ">>> Opening 1883/tcp in ufw..."
  ufw allow 1883/tcp
fi

echo ">>> Smoke test (pub/sub round-trip)..."
( mosquitto_sub -h 127.0.0.1 -t 'ultron/selftest' -C 1 -W 5 > /tmp/mqtt_selftest & )
sleep 1
mosquitto_pub -h 127.0.0.1 -t 'ultron/selftest' -m 'ok'
sleep 1
if grep -q ok /tmp/mqtt_selftest 2>/dev/null; then
  echo "    Broker OK."
else
  echo "    WARNING: self-test failed — check: journalctl -u mosquitto"
fi

IP=$(hostname -I | awk '{print $1}')
echo
echo "============================================"
echo " Mosquitto ready on ${IP}:1883"
echo " Point Mother at mqtt://${IP}:1883 and watch events with:"
echo "   mosquitto_sub -h ${IP} -t 'mother/vision/#' -v"
echo "============================================"
