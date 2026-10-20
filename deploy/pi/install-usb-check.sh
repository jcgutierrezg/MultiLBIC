#!/usr/bin/env bash
# Install (or update) the MultiLBIC USB boot check. Run on the Pi:
#
#   sudo bash ~/MultiLBIC/deploy/pi/install-usb-check.sh
#
# Copies the script to /usr/local/sbin and the systemd unit to
# /etc/systemd/system, then enables it for the next boot. Safe to run
# again after an update. Remove with:
#
#   sudo systemctl disable multilbic-usb-check
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "run with sudo" >&2
    exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uhubctl > /dev/null; then
    echo "uhubctl is missing: sudo apt install uhubctl" >&2
    exit 1
fi

install -m 755 "$HERE/usb-check.sh" /usr/local/sbin/multilbic-usb-check
install -m 644 "$HERE/multilbic-usb-check.service" /etc/systemd/system/multilbic-usb-check.service
systemctl daemon-reload
systemctl enable multilbic-usb-check.service

echo "installed; it runs at every boot. Test now with:"
echo "  sudo multilbic-usb-check --force"
echo "Log: journalctl -t multilbic-usb-check"
