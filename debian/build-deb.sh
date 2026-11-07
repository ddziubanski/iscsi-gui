#!/usr/bin/env bash
# Builds the iscsi-pulse .deb package (Debian 13+ / Ubuntu 24.04+).
# Output: dist/iscsi-pulse_<version>_all.deb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${ROOT_DIR}/iscsi_gui/__init__.py")"
PKG_NAME="iscsi-pulse"
BUILD_DIR="${ROOT_DIR}/dist/${PKG_NAME}_${VERSION}_all"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "error: dpkg-deb not found (this script must run on Debian or a derivative)" >&2
    exit 1
fi

rm -rf "${BUILD_DIR}" "${BUILD_DIR}.deb"
install -d "${BUILD_DIR}/DEBIAN" \
           "${BUILD_DIR}/opt/iscsi-gui" \
           "${BUILD_DIR}/usr/bin" \
           "${BUILD_DIR}/usr/share/applications" \
           "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps" \
           "${BUILD_DIR}/usr/share/polkit-1/actions"

# Libadwaita >= 1.4 is required (Adw.ToolbarView, Adw.SpinRow, Adw.SwitchRow).
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.4), open-iscsi, util-linux, pkexec | policykit-1
Recommends: multipath-tools
Maintainer: Dan Dziubanski <ddziubanski@users.noreply.github.com>
Homepage: https://github.com/ddziubanski/iscsi-gui
Description: GTK4/Libadwaita GUI for open-iscsi
 iSCSI Pulse manages open-iscsi targets: discovery, login, CHAP,
 laptop-safe timeouts, safe unmount before logout, hung session
 recovery, and live per-LUN I/O monitoring.
EOF

# Application files, without bytecode caches.
tar -C "${ROOT_DIR}" --exclude='__pycache__' --exclude='*.pyc' -cf - iscsi_gui bin data \
    | tar -C "${BUILD_DIR}/opt/iscsi-gui" -xf -
find "${BUILD_DIR}/opt" -type d -exec chmod 0755 {} +
find "${BUILD_DIR}/opt" -type f -exec chmod 0644 {} +
chmod 0755 "${BUILD_DIR}/opt/iscsi-gui/bin/iscsi-gui"
ln -sf /opt/iscsi-gui/bin/iscsi-gui "${BUILD_DIR}/usr/bin/iscsi-gui"

install -m 0644 "${ROOT_DIR}/data/io.github.iscsigui.iSCSIManager.desktop" "${BUILD_DIR}/usr/share/applications/"
install -m 0644 "${ROOT_DIR}/data/io.github.iscsigui.iSCSIManager.svg" "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 "${ROOT_DIR}/data/io.github.iscsigui.iSCSIManager.policy" "${BUILD_DIR}/usr/share/polkit-1/actions/"

dpkg-deb --build --root-owner-group "${BUILD_DIR}" >/dev/null
echo "Built ${BUILD_DIR}.deb"
