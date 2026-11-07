"""GTK4 / Libadwaita Application entrypoint for iSCSI Pulse."""

import argparse
import sys
from typing import List, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from . import __app_id__
from .backend import ISCSIBackend
from .window import ISCSIMainWindow


class ISCSIApplication(Adw.Application):
    """Libadwaita application wrapper."""

    def __init__(self, force_demo: bool = False) -> None:
        super().__init__(
            application_id=__app_id__,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.force_demo = force_demo
        self.backend = ISCSIBackend(force_demo=force_demo)
        self.window: Optional[ISCSIMainWindow] = None

    def do_activate(self) -> None:
        if not self.window:
            self.window = ISCSIMainWindow(self, self.backend)
        self.window.present()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="iscsi-gui",
        description="iSCSI Pulse — Modern GTK4/Libadwaita GUI for open-iscsi terminations, connections, CHAP & live I/O.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Start in interactive Sandbox Demo Mode (simulating active & hung sessions and live IOPS)",
    )
    args, gtk_args = parser.parse_known_args(argv)

    app = ISCSIApplication(force_demo=args.demo)
    return app.run([sys.argv[0]] + gtk_args)


if __name__ == "__main__":
    raise SystemExit(main())
