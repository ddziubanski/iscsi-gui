#!/usr/bin/env bash
# Installer for iSCSI Pulse on Ubuntu 26.04 (and Debian/Ubuntu derivatives)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing iSCSI Pulse (open-iscsi GTK4/Libadwaita GUI) ==="

if command -v apt-get >/dev/null 2>&1; then
    echo "[1/4] Installing Ubuntu 26.04 dependencies (open-iscsi, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, policykit-1)..."
    sudo apt-get update -qq
    sudo apt-get install -y open-iscsi python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 pkexec
fi

echo "[2/4] Installing application files to /opt/iscsi-gui and /usr/local/bin/iscsi-gui..."
sudo mkdir -p /opt/iscsi-gui
sudo cp -r "${SCRIPT_DIR}/iscsi_gui" "${SCRIPT_DIR}/bin" "${SCRIPT_DIR}/data" /opt/iscsi-gui/
sudo chmod +x /opt/iscsi-gui/bin/iscsi-gui
sudo ln -sf /opt/iscsi-gui/bin/iscsi-gui /usr/local/bin/iscsi-gui

echo "[3/4] Installing Polkit policy and desktop integration..."
if [ -d /usr/share/polkit-1/actions ]; then
    sudo cp "${SCRIPT_DIR}/data/io.github.iscsigui.iSCSIManager.policy" /usr/share/polkit-1/actions/
fi
sudo mkdir -p /usr/share/applications /usr/share/icons/hicolor/scalable/apps
sudo cp "${SCRIPT_DIR}/data/io.github.iscsigui.iSCSIManager.desktop" /usr/share/applications/
sudo cp "${SCRIPT_DIR}/data/io.github.iscsigui.iSCSIManager.svg" /usr/share/icons/hicolor/scalable/apps/

echo "[4/4] Done! Run 'iscsi-gui' from terminal or launch 'iSCSI Pulse' from your Ubuntu App Grid."
