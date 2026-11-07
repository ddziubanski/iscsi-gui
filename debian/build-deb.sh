#!/usr/bin/env bash
# Builds a native Debian/Ubuntu .deb package (iscsi-pulse_1.0.0_all.deb) for Ubuntu 26.04+
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION="1.0.0"
PKG_NAME="iscsi-pulse"
BUILD_DIR="${ROOT_DIR}/dist/${PKG_NAME}_${VERSION}_all"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/opt/iscsi-gui"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${BUILD_DIR}/usr/share/polkit-1/actions"

cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, open-iscsi, pkexec | policykit-1
Recommends: multipath-tools
Maintainer: Dan <dan@localhost>
Description: Modern GTK4/Libadwaita GUI for open-iscsi terminations and connections
 iSCSI Pulse makes managing open-iscsi targets, CHAP authentication,
 laptop-safe replacement timeouts, safe filesystem unmounting prior to session
 logout, hung session force-termination, and live LUN I/O monitoring easy.
EOF

cp -r "${ROOT_DIR}/iscsi_gui" "${ROOT_DIR}/bin" "${ROOT_DIR}/data" "${BUILD_DIR}/opt/iscsi-gui/"
chmod 0755 "${BUILD_DIR}/opt/iscsi-gui/bin/iscsi-gui"
ln -sf /opt/iscsi-gui/bin/iscsi-gui "${BUILD_DIR}/usr/bin/iscsi-gui"

cp "${ROOT_DIR}/data/io.github.iscsigui.iSCSIManager.desktop" "${BUILD_DIR}/usr/share/applications/"
cp "${ROOT_DIR}/data/io.github.iscsigui.iSCSIManager.svg" "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps/"
cp "${ROOT_DIR}/data/io.github.iscsigui.iSCSIManager.policy" "${BUILD_DIR}/usr/share/polkit-1/actions/"

if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --build --root-owner-group "${BUILD_DIR}"
    echo "Built Debian package: ${BUILD_DIR}.deb"
else
    echo "Staging directory prepared at: ${BUILD_DIR} (install dpkg-deb to build .deb archive)"
fi
