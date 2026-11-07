# iSCSI Pulse (`iscsi-gui`)

**Modern GTK4 + Libadwaita GUI for managing `open-iscsi` terminations, target connections, CHAP authentication, laptop anti-freeze timeouts, and live LUN I/O telemetry on Ubuntu 26.04 and Linux.**

---

## Why iSCSI Pulse?

Managing `open-iscsi` (`iscsiadm`) on a Linux laptop or workstation has traditionally been painful for three reasons:
1. **Stale / Hung Sessions Freeze Laptops**: When a laptop sleeps, switches Wi-Fi networks, or drops VPN while an iSCSI target is still logged in, `open-iscsi` defaults to a **120-second `replacement_timeout`**, freezing `df`, file managers (`Nautilus`), and processes waiting on I/O.
2. **Unsafe Terminations Corrupt Mounts**: Running `iscsiadm -m node -u` without first syncing buffers, unmounting filesystems, and flushing multipath maps causes orphaned mountpoints and kernel buffer I/O errors.
3. **Verbose CLI Configuration**: Configuring CHAP / Mutual CHAP, startup modes, and timeouts takes 6–10 separate `iscsiadm -m node -T <iqn> -p <portal> -o update -n ... -v ...` commands per target.

**iSCSI Pulse** solves all three in a native GNOME / Ubuntu 26.04 GTK4 + Libadwaita desktop app:
- **Safe Graceful Termination**: One-click workflow that runs `sync`, unmounts attached partitions (`/dev/sdX`), flushes DM-Multipath maps (`multipath -f`), and logs out of the iSCSI session.
- **Force Unfreeze / Hung Session Recovery**: Immediately sets kernel `/sys/class/iscsi_session/session<N>/recovery_tmo = 0`, lazy-unmounts dead mountpoints (`umount -l`), and force-terminates unreachable targets so your laptop unfreezes immediately.
- **1-Click "Undock / Terminate All"**: Safely disconnects all active iSCSI targets before closing your laptop lid or leaving the LAN.
- **15s Laptop Anti-Freeze Timeout Preset**: Applies `replacement_timeout = 15s` and `noop_out_interval = 5s` with `manual` startup so roaming laptops never hang at boot or on network transitions.
- **SendTargets Discovery & CHAP / Mutual CHAP Editor**: Discover portals and configure unidirectional or bidirectional CHAP in one modal.
- **Live LUN I/O & Health Telemetry**: Real-time 60-second Read/Write MB/s Cairo chart, per-LUN IOPS from `/proc/diskstats`, and TCP portal latency probes.
- **Single-Prompt Polkit (`pkexec`) Elevation + Full Command Audit Log**: Batches privileged `iscsiadm` operations per action and logs every command executed.

---

## Quick Start on Ubuntu 26.04

### Option 1: One-Command Install
```bash
cd /home/dan/Projects/iscsi-gui
chmod +x install-ubuntu.sh
./install-ubuntu.sh
```

### Option 2: Build a `.deb` Package for Ubuntu 26.04
```bash
cd /home/dan/Projects/iscsi-gui
chmod +x debian/build-deb.sh
./debian/build-deb.sh
sudo apt install ./dist/iscsi-pulse_1.0.0_all.deb
```

### Option 3: Run Directly from Source (or in Interactive Demo Mode)
```bash
# Run against live system (or auto-fallback to Demo Mode if open-iscsi isn't installed yet)
./bin/iscsi-gui

# Explicitly launch in Sandbox Demo Mode to test hung session recovery & live IOPS graphs
./bin/iscsi-gui --demo
```
