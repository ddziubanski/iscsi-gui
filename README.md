# iSCSI Pulse (`iscsi-gui`)

A GTK4 + Libadwaita desktop app for managing [open-iscsi](https://github.com/open-iscsi/open-iscsi) on Linux. It wraps `iscsiadm` so you can discover targets, connect, set up CHAP, and log out safely without typing long commands.

## Features

- **Discover and connect**: SendTargets discovery against a portal, then log in to a target.
- **CHAP**: one-way and mutual CHAP, set from a single dialog.
- **Laptop-friendly timeouts**: a preset that sets `replacement_timeout` to 15s and `noop_out_interval` to 5s, with manual startup, so a dropped network doesn't hang the machine for two minutes.
- **Safe logout**: runs `sync`, unmounts the session's filesystems, flushes any multipath map (`multipath -f`), then logs out.
- **Hung session recovery**: sets `recovery_tmo` to 0 in sysfs, lazy-unmounts (`umount -l`) and forces the logout.
- **Terminate all**: disconnects every active session in one step.
- **Live I/O**: read/write throughput and IOPS per LUN from `/proc/diskstats`, plus TCP latency to each portal.
- **One password prompt per action**: privileged steps are batched into a single `pkexec` call, and every command run is shown in a log.
- **Demo mode**: simulated sessions (including a hung one) for trying the app without any iSCSI setup.

## Requirements

- Linux with `open-iscsi`
- Python 3.10+
- PyGObject with GTK 4 and Libadwaita 1 (`python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`)
- `pkexec` (polkit)
- Optional: `multipath-tools`

On Debian or Ubuntu:

```bash
sudo apt install open-iscsi python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 pkexec
```

## Running

From the source tree:

```bash
./bin/iscsi-gui          # use the live system; falls back to demo mode if open-iscsi isn't found
./bin/iscsi-gui --demo   # force demo mode
```

## Installing

**Install script** (Debian/Ubuntu). Installs dependencies and copies the app to `/opt/iscsi-gui`, with a link at `/usr/local/bin/iscsi-gui`, plus the desktop entry, icon and polkit policy:

```bash
./install-ubuntu.sh
```

**Debian package:**

```bash
./debian/build-deb.sh
sudo apt install ./dist/iscsi-pulse_1.0.0_all.deb
```

## Project layout

```
bin/iscsi-gui        launcher
iscsi_gui/
  app.py             application entry point and --demo flag
  window.py          main window
  dialogs.py         discovery, connect and CHAP dialogs
  backend.py         iscsiadm / sysfs / pkexec calls, demo data, command log
  monitor.py         /proc/diskstats sampling and portal latency checks
  models.py          data classes
data/                desktop entry, icon, polkit policy
debian/build-deb.sh  .deb builder
tests/               unit tests
```

## Tests

```bash
python3 -m unittest
```

## License

MIT. See [LICENSE](LICENSE).
