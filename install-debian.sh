#!/usr/bin/env bash
# Installer for iSCSI Pulse on Debian 13+ (and derivatives such as Ubuntu 24.04+).
#
# Builds the iscsi-pulse .deb from this source tree and installs it with apt,
# which pulls in every dependency. The app is then managed like any package:
#     sudo apt remove iscsi-pulse
#
# Usage: ./install-debian.sh [--with-multipath] [--uninstall]
#   --with-multipath  also install multipath-tools (needed only for DM-Multipath setups)
#   --uninstall       remove the iscsi-pulse package
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="iscsi-pulse"
MIN_ADW="1.4"

WITH_MULTIPATH=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --with-multipath) WITH_MULTIPATH=1 ;;
        --uninstall)      UNINSTALL=1 ;;
        -h|--help)        sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
elif command -v sudo >/dev/null 2>&1; then
    SUDO=(sudo)
else
    die "run as root, or install sudo"
fi

command -v apt-get >/dev/null 2>&1 && command -v dpkg >/dev/null 2>&1 \
    || die "apt/dpkg not found; this installer is for Debian and its derivatives"

if [ "$UNINSTALL" -eq 1 ]; then
    say "Removing ${PKG_NAME}"
    "${SUDO[@]}" apt-get remove -y "$PKG_NAME"
    exit 0
fi

. /etc/os-release 2>/dev/null || true
say "Installing iSCSI Pulse on ${PRETTY_NAME:-unknown system}"

say "Refreshing package lists"
"${SUDO[@]}" apt-get update -qq

# Libadwaita 1.4+ is required. Debian 12 (bookworm) only has 1.2, so check
# the version apt would install before going any further.
adw_candidate="$(apt-cache policy gir1.2-adw-1 | awk '/Candidate:/ {print $2}')"
if [ -z "$adw_candidate" ] || [ "$adw_candidate" = "(none)" ]; then
    die "package gir1.2-adw-1 (Libadwaita) is not available from your apt sources"
fi
if ! dpkg --compare-versions "$adw_candidate" ge "$MIN_ADW"; then
    die "Libadwaita ${adw_candidate} is too old; iSCSI Pulse needs ${MIN_ADW} or newer.
       Debian 13 (trixie) or later is required (Debian 12 ships 1.2)."
fi

say "Building ${PKG_NAME} package"
"${SCRIPT_DIR}/debian/build-deb.sh"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${SCRIPT_DIR}/iscsi_gui/__init__.py")"
DEB="${SCRIPT_DIR}/dist/${PKG_NAME}_${VERSION}_all.deb"
[ -f "$DEB" ] || die "package was not built: $DEB"

say "Installing ${PKG_NAME} ${VERSION} and its dependencies"
apt_opts=(-y)
[ "$WITH_MULTIPATH" -eq 1 ] || apt_opts+=(--no-install-recommends)
# Copy to /tmp so the _apt sandbox user can read it even if $HOME is private.
tmp_deb="$(mktemp --tmpdir "${PKG_NAME}_XXXXXX.deb")"
trap 'rm -f "$tmp_deb"' EXIT
cp "$DEB" "$tmp_deb"
chmod 0644 "$tmp_deb"
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install "${apt_opts[@]}" "$tmp_deb"

# open-iscsi's daemon is socket-activated on Debian; make sure it is enabled.
if [ -d /run/systemd/system ]; then
    say "Enabling iscsid"
    "${SUDO[@]}" systemctl enable --now iscsid.socket >/dev/null 2>&1 \
        || "${SUDO[@]}" systemctl enable --now iscsid.service >/dev/null 2>&1 \
        || echo "warning: could not enable iscsid; start it with: sudo systemctl start iscsid" >&2
fi

say "Checking the install"
python3 - <<'EOF'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
v = (Adw.get_major_version(), Adw.get_minor_version())
assert v >= (1, 4), f"Libadwaita {v} is too old"
print(f"  GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}, Libadwaita {v[0]}.{v[1]}")
EOF
command -v iscsiadm >/dev/null 2>&1 || PATH="$PATH:/usr/sbin:/sbin"
command -v iscsiadm >/dev/null 2>&1 && echo "  $(iscsiadm --version)"
command -v iscsi-gui >/dev/null 2>&1 && echo "  iscsi-gui -> $(command -v iscsi-gui)"

say "Done. Launch \"iSCSI Pulse\" from your app menu, or run: iscsi-gui"
echo "    Remove it later with: sudo apt remove ${PKG_NAME}"
