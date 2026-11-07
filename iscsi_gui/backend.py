"""Backend controller for open-iscsi (iscsiadm), sysfs session inspection, lsblk, and Polkit elevation."""

from datetime import datetime
import glob
import json
import math
import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from .models import (
    ActiveSession,
    BlockDeviceInfo,
    ChapConfig,
    CommandLogEntry,
    DiscoveredNode,
    TimeoutConfig,
)
from .monitor import DiskIOMonitor, probe_portal_tcp


SESSION_LINE_RE = re.compile(
    r"^(?P<transport>\S+):\s+\[(?P<sid>\d+)\]\s+(?P<portal>\S+)\s+(?P<iqn>\S+)(?:\s+\((?P<extra>.*)\))?$"
)
NODE_LINE_RE = re.compile(r"^(?P<portal>\S+)\s+(?P<iqn>\S+)$")


def parse_iscsiadm_sessions(output: str) -> List[ActiveSession]:
    """Parse output of `iscsiadm -m session`."""
    sessions: List[ActiveSession] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("iscsiadm:"):
            continue
        m = SESSION_LINE_RE.match(line)
        if m:
            sessions.append(
                ActiveSession(
                    session_id=int(m.group("sid")),
                    target_iqn=m.group("iqn"),
                    portal=m.group("portal"),
                    transport=m.group("transport").rstrip(":"),
                )
            )
    return sessions


def parse_iscsiadm_nodes(output: str) -> List[DiscoveredNode]:
    """Parse output of `iscsiadm -m node`."""
    nodes: List[DiscoveredNode] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("iscsiadm:"):
            continue
        m = NODE_LINE_RE.match(line)
        if m:
            nodes.append(
                DiscoveredNode(
                    target_iqn=m.group("iqn"),
                    portal=m.group("portal"),
                )
            )
    return nodes


def parse_node_kv_config(output: str) -> Dict[str, str]:
    """Parse `key = value` output of `iscsiadm -m node -T <iqn> -p <portal>`."""
    config: Dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        config[key.strip()] = val.strip()
    return config


class ISCSIBackend:
    """Manages real open-iscsi operations with optional Demo/Simulation mode."""

    def __init__(self, force_demo: bool = False) -> None:
        self.iscsiadm_path = shutil.which("iscsiadm") or "/usr/bin/iscsiadm"
        self.pkexec_path = shutil.which("pkexec") or "/usr/bin/pkexec"
        self.has_iscsiadm = shutil.which("iscsiadm") is not None
        self.demo_mode = force_demo or (not self.has_iscsiadm)
        self.io_monitor = DiskIOMonitor()
        self.command_log: List[CommandLogEntry] = []

        # Demo mode state
        self._demo_initiator_iqn = "iqn.2026-04.com.ubuntu:laptop-main-nvme01"
        self._demo_nodes: List[DiscoveredNode] = [
            DiscoveredNode(
                target_iqn="iqn.2026-01.lan.synology:nas-rack01.lun-media",
                portal="192.168.10.20:3260,1",
                startup_mode="automatic",
                chap=ChapConfig(enabled=True, username="dan_laptop", password="********"),
                timeouts=TimeoutConfig(replacement_timeout=15, noop_out_interval=5, noop_out_timeout=5),
                is_connected=True,
                session_id=1,
            ),
            DiscoveredNode(
                target_iqn="iqn.2026-01.lan.truenas:zfs-pool01.vm-datastore",
                portal="192.168.10.25:3260,1",
                startup_mode="manual",
                chap=ChapConfig(enabled=False),
                timeouts=TimeoutConfig(replacement_timeout=15, noop_out_interval=5, noop_out_timeout=5),
                is_connected=True,
                session_id=2,
            ),
            DiscoveredNode(
                target_iqn="iqn.2025-11.corp.san:branch-backup-archive",
                portal="10.80.4.12:3260,1",
                startup_mode="manual",
                chap=ChapConfig(enabled=True, username="backup_init", password="********"),
                timeouts=TimeoutConfig(replacement_timeout=120, noop_out_interval=10, noop_out_timeout=15),
                is_connected=True,
                session_id=3,
            ),
            DiscoveredNode(
                target_iqn="iqn.2026-02.homelab.proxmox:ceph-iscsi-gw01",
                portal="192.168.10.40:3260,1",
                startup_mode="manual",
                chap=ChapConfig(enabled=False),
                timeouts=TimeoutConfig(replacement_timeout=15, noop_out_interval=5, noop_out_timeout=5),
                is_connected=False,
                session_id=None,
            ),
        ]
        self._demo_sessions: List[ActiveSession] = [
            ActiveSession(
                session_id=1,
                target_iqn="iqn.2026-01.lan.synology:nas-rack01.lun-media",
                portal="192.168.10.20:3260,1",
                transport="tcp",
                session_state="LOGGED_IN",
                connection_state="LOGGED_IN",
                portal_reachable=True,
                latency_ms=0.8,
                block_devices=[
                    BlockDeviceInfo(
                        device_name="sdb",
                        device_path="/dev/sdb",
                        size_human="2.0 TB",
                        model="Synology iSCSI Storage",
                        lun_id=0,
                        mountpoints=["/mnt/nas-media"],
                        fstype="ext4",
                        read_bps=42.5 * 1024 * 1024,
                        write_bps=12.1 * 1024 * 1024,
                        read_iops=340.0,
                        write_iops=115.0,
                    )
                ],
            ),
            ActiveSession(
                session_id=2,
                target_iqn="iqn.2026-01.lan.truenas:zfs-pool01.vm-datastore",
                portal="192.168.10.25:3260,1",
                transport="tcp",
                session_state="LOGGED_IN",
                connection_state="LOGGED_IN",
                portal_reachable=True,
                latency_ms=0.4,
                block_devices=[
                    BlockDeviceInfo(
                        device_name="sdc",
                        device_path="/dev/sdc",
                        size_human="500.0 GB",
                        model="TrueNAS iSCSI ZVOL",
                        lun_id=0,
                        multipath_dm="dm-2 (mpatha)",
                        mountpoints=[],
                        fstype="xfs",
                        read_bps=8.2 * 1024 * 1024,
                        write_bps=1.4 * 1024 * 1024,
                        read_iops=95.0,
                        write_iops=22.0,
                    )
                ],
            ),
            ActiveSession(
                session_id=3,
                target_iqn="iqn.2025-11.corp.san:branch-backup-archive",
                portal="10.80.4.12:3260,1",
                transport="tcp",
                session_state="FAILED",
                connection_state="TRANSPORT_WAIT",
                portal_reachable=False,
                latency_ms=None,
                block_devices=[
                    BlockDeviceInfo(
                        device_name="sdd",
                        device_path="/dev/sdd",
                        size_human="4.0 TB",
                        model="LIO-ORG IBLOCK",
                        lun_id=0,
                        mountpoints=["/mnt/corp-archive"],
                        fstype="btrfs",
                        read_bps=0.0,
                        write_bps=0.0,
                        read_iops=0.0,
                        write_iops=0.0,
                    )
                ],
            ),
        ]
        self._next_demo_sid = 4

    def _log(self, command: str, success: bool, output: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.command_log.insert(
            0,
            CommandLogEntry(
                timestamp=ts,
                command=command,
                success=success,
                output=output.strip() or ("OK" if success else "Command failed"),
            ),
        )
        if len(self.command_log) > 100:
            self.command_log.pop()

    def _run_privileged_script(self, script_lines: List[str], description: str) -> Tuple[bool, str]:
        """
        Execute one or more privileged commands in a single Polkit elevation (`pkexec sh -c ...`)
        so the user is only prompted once per action.
        """
        joined = " && ".join(script_lines)
        if os.geteuid() == 0:
            cmd = ["/bin/sh", "-c", joined]
        else:
            cmd = [self.pkexec_path, "/bin/sh", "-c", joined]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            out = (proc.stdout + "\n" + proc.stderr).strip()
            ok = proc.returncode == 0
            self._log(f"[privileged] {description}: {joined}", ok, out)
            return ok, out
        except Exception as exc:
            self._log(f"[privileged] {description}: {joined}", False, str(exc))
            return False, str(exc)

    def _run_cmd(self, args: List[str], privileged: bool = False) -> Tuple[bool, str]:
        """Run a command, optionally via pkexec if root is needed."""
        cmd_str = " ".join(args)
        if privileged and os.geteuid() != 0:
            run_args = [self.pkexec_path] + args
        else:
            run_args = args

        try:
            proc = subprocess.run(
                run_args,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            out = (proc.stdout + "\n" + proc.stderr).strip()
            # Note: `iscsiadm -m session` returns exit code 21 when no active sessions exist
            if proc.returncode == 21 and "No active sessions" in out:
                return True, ""
            ok = proc.returncode == 0
            self._log(cmd_str, ok, out)
            return ok, out
        except Exception as exc:
            self._log(cmd_str, False, str(exc))
            return False, str(exc)

    # -------------------------------------------------------------------------
    # Initiator Name & Service Status
    # -------------------------------------------------------------------------
    def get_initiator_name(self) -> str:
        if self.demo_mode:
            return self._demo_initiator_iqn

        path = "/etc/iscsi/initiatorname.iscsi"
        if os.path.exists(path) and os.access(path, os.R_OK):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("InitiatorName="):
                            return line.split("=", 1)[1].strip()
            except OSError:
                pass
        return "iqn.2026-04.com.ubuntu:initiator-unconfigured"

    def set_initiator_name(self, new_iqn: str) -> Tuple[bool, str]:
        new_iqn = new_iqn.strip()
        if not new_iqn.startswith("iqn.") and not new_iqn.startswith("eui.") and not new_iqn.startswith("naa."):
            return False, "Initiator name must start with 'iqn.', 'eui.', or 'naa.'."

        if self.demo_mode:
            self._demo_initiator_iqn = new_iqn
            self._log(
                f"echo 'InitiatorName={new_iqn}' > /etc/iscsi/initiatorname.iscsi && systemctl restart iscsid",
                True,
                f"Updated InitiatorName to {new_iqn} (Demo Mode)",
            )
            return True, f"Updated InitiatorName to {new_iqn}"

        safe_iqn = new_iqn.replace("'", "").replace('"', "").replace(";", "")
        lines = [
            f"printf '# Generated by iSCSI Pulse\\nInitiatorName=%s\\n' '{safe_iqn}' > /etc/iscsi/initiatorname.iscsi",
            "systemctl restart iscsid",
        ]
        return self._run_privileged_script(lines, "Update Initiator IQN")

    def get_service_status(self) -> Tuple[bool, str]:
        """Return (is_active, status_label) for iscsid."""
        if self.demo_mode:
            return True, "active (running) — Demo Sandbox"

        try:
            proc = subprocess.run(
                ["systemctl", "is-active", "iscsid"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            state = proc.stdout.strip() or "inactive"
            return state == "active", state
        except Exception:
            return False, "unknown"

    # -------------------------------------------------------------------------
    # Sysfs & Block Device Mapping
    # -------------------------------------------------------------------------
    def _get_lsblk_map(self) -> Dict[str, dict]:
        """Run `lsblk -J -o NAME,PATH,SIZE,MODEL,MOUNTPOINTS,FSTYPE,TYPE`."""
        result: Dict[str, dict] = {}
        try:
            proc = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,PATH,SIZE,MODEL,MOUNTPOINTS,FSTYPE,TYPE"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                for dev in data.get("blockdevices", []):
                    result[dev.get("name", "")] = dev
        except Exception:
            pass
        return result

    def _collect_mounts_recursive(self, dev_entry: dict) -> Tuple[List[str], str, Optional[str]]:
        """Collect all mountpoints, fstype, and multipath child names from an lsblk tree entry."""
        mounts: List[str] = []
        fstype = dev_entry.get("fstype") or ""
        multipath_dm: Optional[str] = None

        raw_mps = dev_entry.get("mountpoints") or []
        for mp in raw_mps:
            if mp and mp not in mounts:
                mounts.append(mp)

        for child in dev_entry.get("children") or []:
            c_type = child.get("type") or ""
            c_name = child.get("name") or ""
            if c_type == "mpath" or c_name.startswith("dm-"):
                multipath_dm = c_name
            if not fstype and child.get("fstype"):
                fstype = child.get("fstype")
            c_mounts, c_fs, c_dm = self._collect_mounts_recursive(child)
            for mp in c_mounts:
                if mp not in mounts:
                    mounts.append(mp)
            if not fstype and c_fs:
                fstype = c_fs
            if not multipath_dm and c_dm:
                multipath_dm = c_dm

        return mounts, fstype, multipath_dm

    def _enrich_session_from_sysfs(
        self,
        session: ActiveSession,
        lsblk_map: Dict[str, dict],
        io_rates: Dict[str, Tuple[float, float, float, float]],
    ) -> None:
        """Populate session state, connection state, and block devices from /sys/class/iscsi_session."""
        sid = session.session_id
        sys_session_dir = f"/sys/class/iscsi_session/session{sid}"
        state_file = os.path.join(sys_session_dir, "state")
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    session.session_state = f.read().strip()
            except OSError:
                pass

        conn_state_file = f"/sys/class/iscsi_connection/connection{sid}:0/state"
        if os.path.exists(conn_state_file):
            try:
                with open(conn_state_file, "r", encoding="utf-8") as f:
                    session.connection_state = f.read().strip()
            except OSError:
                pass

        # Find block devices under /sys/class/iscsi_session/session<sid>/device/target*/*/block/*
        block_glob = os.path.join(sys_session_dir, "device", "target*", "*", "block", "*")
        block_devices: List[BlockDeviceInfo] = []
        for path in sorted(glob.glob(block_glob)):
            dev_name = os.path.basename(path)
            scsi_addr = os.path.basename(os.path.dirname(os.path.dirname(path)))
            lun_id = 0
            if ":" in scsi_addr:
                try:
                    lun_id = int(scsi_addr.rsplit(":", 1)[1])
                except ValueError:
                    lun_id = 0

            lsblk_entry = lsblk_map.get(dev_name, {})
            mounts, fstype, mpath = self._collect_mounts_recursive(lsblk_entry)
            r_bps, w_bps, r_iops, w_iops = io_rates.get(dev_name, (0.0, 0.0, 0.0, 0.0))

            block_devices.append(
                BlockDeviceInfo(
                    device_name=dev_name,
                    device_path=f"/dev/{dev_name}",
                    size_human=lsblk_entry.get("size") or "Unknown",
                    model=(lsblk_entry.get("model") or "iSCSI Disk").strip(),
                    lun_id=lun_id,
                    multipath_dm=mpath,
                    mountpoints=mounts,
                    fstype=fstype,
                    read_bps=r_bps,
                    write_bps=w_bps,
                    read_iops=r_iops,
                    write_iops=w_iops,
                )
            )
        session.block_devices = block_devices

    # -------------------------------------------------------------------------
    # Querying Sessions & Nodes
    # -------------------------------------------------------------------------
    def get_active_sessions(self, check_reachability: bool = True) -> List[ActiveSession]:
        """Return all active iSCSI sessions with block device mounts and live I/O."""
        if self.demo_mode:
            # Add smooth sinusoidal jitter to demo I/O numbers so live graphs look realistic
            t = time.time()
            for idx, s in enumerate(self._demo_sessions):
                if s.is_healthy:
                    s.latency_ms = round(0.4 + 0.3 * abs(math.sin(t + idx)), 1)
                    for dev in s.block_devices:
                        factor = 0.7 + 0.5 * abs(math.sin(t * 0.9 + idx))
                        base_r = 38.0 * 1024 * 1024 if idx == 0 else 9.5 * 1024 * 1024
                        base_w = 14.0 * 1024 * 1024 if idx == 0 else 2.2 * 1024 * 1024
                        dev.read_bps = base_r * factor
                        dev.write_bps = base_w * factor
                        dev.read_iops = round((310.0 if idx == 0 else 95.0) * factor, 1)
                        dev.write_iops = round((110.0 if idx == 0 else 28.0) * factor, 1)
            return list(self._demo_sessions)

        # We can read sessions either from sysfs (no root needed!) or `iscsiadm -m session`
        ok, out = self._run_cmd([self.iscsiadm_path, "-m", "session"], privileged=False)
        sessions = parse_iscsiadm_sessions(out) if ok else []

        lsblk_map = self._get_lsblk_map()
        io_rates = self.io_monitor.sample()

        for s in sessions:
            self._enrich_session_from_sysfs(s, lsblk_map, io_rates)
            if check_reachability:
                reachable, latency = probe_portal_tcp(s.portal_host, s.portal_port, timeout=0.4)
                s.portal_reachable = reachable
                s.latency_ms = latency

        return sessions

    def get_discovered_nodes(self) -> List[DiscoveredNode]:
        """Return all discovered iSCSI target nodes and mark active connections."""
        if self.demo_mode:
            active_map = {(s.target_iqn, s.portal): s.session_id for s in self._demo_sessions}
            for node in self._demo_nodes:
                sid = active_map.get((node.target_iqn, node.portal))
                node.is_connected = sid is not None
                node.session_id = sid
            return list(self._demo_nodes)

        ok, out = self._run_cmd([self.iscsiadm_path, "-m", "node"], privileged=False)
        nodes = parse_iscsiadm_nodes(out) if ok else []
        sessions = self.get_active_sessions(check_reachability=False)
        active_map = {(s.target_iqn, s.portal): s.session_id for s in sessions}

        for node in nodes:
            sid = active_map.get((node.target_iqn, node.portal))
            node.is_connected = sid is not None
            node.session_id = sid

            # Try reading node configuration if readable without root
            ok_cfg, cfg_out = self._run_cmd(
                [self.iscsiadm_path, "-m", "node", "-T", node.target_iqn, "-p", node.portal],
                privileged=False,
            )
            if ok_cfg and cfg_out:
                kv = parse_node_kv_config(cfg_out)
                node.startup_mode = kv.get("node.startup", kv.get("node.conn[0].startup", "manual"))
                auth_method = kv.get("node.session.auth.authmethod", "None")
                node.chap.enabled = auth_method.upper() == "CHAP"
                node.chap.username = kv.get("node.session.auth.username", "")
                node.chap.username_in = kv.get("node.session.auth.username_in", "")
                node.chap.mutual_enabled = bool(node.chap.username_in and node.chap.username_in != "<empty>")
                try:
                    node.timeouts.replacement_timeout = int(
                        kv.get("node.session.timeo.replacement_timeout", "120")
                    )
                except ValueError:
                    pass

        return nodes

    # -------------------------------------------------------------------------
    # Discovery & Connection Actions
    # -------------------------------------------------------------------------
    def discover_targets(self, portal_ip: str, port: int = 3260) -> Tuple[bool, str, List[DiscoveredNode]]:
        """Run SendTargets discovery against `portal_ip:port`."""
        portal_str = f"{portal_ip.strip()}:{port}"
        if self.demo_mode:
            new_iqn = f"iqn.2026-04.lan.storage:target-{portal_ip.replace('.', '-')}"
            full_portal = f"{portal_str},1"
            existing = [
                n for n in self._demo_nodes if n.target_iqn == new_iqn and n.portal == full_portal
            ]
            if not existing:
                new_node = DiscoveredNode(
                    target_iqn=new_iqn,
                    portal=full_portal,
                    startup_mode="manual",
                    timeouts=TimeoutConfig(replacement_timeout=15),
                )
                self._demo_nodes.append(new_node)
            cmd_str = f"iscsiadm -m discovery -t sendtargets -p {portal_str}"
            self._log(cmd_str, True, f"{full_portal} {new_iqn}")
            return True, f"Discovered target {new_iqn} at {portal_str}", self.get_discovered_nodes()

        ok, out = self._run_cmd(
            [self.iscsiadm_path, "-m", "discovery", "-t", "sendtargets", "-p", portal_str],
            privileged=True,
        )
        discovered = parse_iscsiadm_nodes(out) if ok else []
        return ok, out, discovered

    def configure_and_connect_node(
        self,
        target_iqn: str,
        portal: str,
        startup_mode: str,
        chap: ChapConfig,
        timeouts: TimeoutConfig,
        connect_now: bool = True,
    ) -> Tuple[bool, str]:
        """Configure node CHAP, startup mode, laptop-safe timeouts, and optionally log in."""
        if self.demo_mode:
            target_node: Optional[DiscoveredNode] = None
            for n in self._demo_nodes:
                if n.target_iqn == target_iqn and n.portal == portal:
                    target_node = n
                    break
            if not target_node:
                target_node = DiscoveredNode(target_iqn=target_iqn, portal=portal)
                self._demo_nodes.append(target_node)

            target_node.startup_mode = startup_mode
            target_node.chap = chap
            target_node.timeouts = timeouts

            if connect_now and not target_node.is_connected:
                sid = self._next_demo_sid
                self._next_demo_sid += 1
                dev_letter = chr(ord("b") + sid)
                self._demo_sessions.append(
                    ActiveSession(
                        session_id=sid,
                        target_iqn=target_iqn,
                        portal=portal,
                        transport="tcp",
                        session_state="LOGGED_IN",
                        connection_state="LOGGED_IN",
                        portal_reachable=True,
                        latency_ms=0.6,
                        block_devices=[
                            BlockDeviceInfo(
                                device_name=f"sd{dev_letter}",
                                device_path=f"/dev/sd{dev_letter}",
                                size_human="1.0 TB",
                                model="Linux iSCSI Target",
                                lun_id=0,
                            )
                        ],
                    )
                )
                target_node.is_connected = True
                target_node.session_id = sid

            self._log(
                f"iscsiadm -m node -T {target_iqn} -p {portal} [configure + {'login' if connect_now else 'save'}]",
                True,
                f"Configured node {target_iqn} (replacement_timeout={timeouts.replacement_timeout}s, startup={startup_mode})",
            )
            return True, f"Successfully configured {'and connected ' if connect_now else ''}{target_iqn}"

        base = f"{self.iscsiadm_path} -m node -T '{target_iqn}' -p '{portal}'"
        cmds = [
            f"{base} -o update -n node.startup -v '{startup_mode}'",
            f"{base} -o update -n node.conn[0].startup -v '{startup_mode}'",
            f"{base} -o update -n node.session.timeo.replacement_timeout -v {int(timeouts.replacement_timeout)}",
            f"{base} -o update -n node.conn[0].timeo.noop_out_interval -v {int(timeouts.noop_out_interval)}",
            f"{base} -o update -n node.conn[0].timeo.noop_out_timeout -v {int(timeouts.noop_out_timeout)}",
        ]
        if chap.enabled:
            cmds.append(f"{base} -o update -n node.session.auth.authmethod -v CHAP")
            cmds.append(f"{base} -o update -n node.session.auth.username -v '{chap.username}'")
            if chap.password and chap.password != "********":
                cmds.append(f"{base} -o update -n node.session.auth.password -v '{chap.password}'")
            if chap.mutual_enabled:
                cmds.append(f"{base} -o update -n node.session.auth.username_in -v '{chap.username_in}'")
                if chap.password_in and chap.password_in != "********":
                    cmds.append(f"{base} -o update -n node.session.auth.password_in -v '{chap.password_in}'")
        else:
            cmds.append(f"{base} -o update -n node.session.auth.authmethod -v None")

        if connect_now:
            cmds.append(f"{base} --login")

        return self._run_privileged_script(cmds, f"Configure & connect {target_iqn}")

    def login_node(self, target_iqn: str, portal: str) -> Tuple[bool, str]:
        """Log in to an existing discovered node."""
        if self.demo_mode:
            for n in self._demo_nodes:
                if n.target_iqn == target_iqn and n.portal == portal:
                    return self.configure_and_connect_node(
                        target_iqn, portal, n.startup_mode, n.chap, n.timeouts, connect_now=True
                    )
            return False, "Node not found"

        return self._run_cmd(
            [self.iscsiadm_path, "-m", "node", "-T", target_iqn, "-p", portal, "--login"],
            privileged=True,
        )

    # -------------------------------------------------------------------------
    # Safe & Force Termination Actions
    # -------------------------------------------------------------------------
    def terminate_session(
        self,
        session: ActiveSession,
        safe_unmount: bool = True,
        force_kill_hung: bool = False,
    ) -> Tuple[bool, str]:
        """
        Terminate an active iSCSI session:
        - If `safe_unmount=True`: syncs and unmounts any mounted filesystems on attached LUNs first.
        - If `force_kill_hung=True`: sets replacement_timeout=0 on sysfs and node, lazy-unmounts
          unreachable mounts (`umount -l`), and forces session logout so laptop I/O unfreezes immediately.
        """
        if self.demo_mode:
            steps: List[str] = []
            if force_kill_hung:
                steps.append(
                    f"echo 0 > /sys/class/iscsi_session/session{session.session_id}/recovery_tmo"
                )
            for dev in session.block_devices:
                for mp in dev.mountpoints:
                    umount_flag = "-l " if force_kill_hung else ""
                    steps.append(f"umount {umount_flag}{mp}")
                if dev.multipath_dm:
                    mpath_name = dev.multipath_dm.split()[0]
                    steps.append(f"multipath -f {mpath_name}")
            steps.append(
                f"iscsiadm -m node -T {session.target_iqn} -p {session.portal} --logout"
            )
            self._demo_sessions = [
                s for s in self._demo_sessions if s.session_id != session.session_id
            ]
            for n in self._demo_nodes:
                if n.target_iqn == session.target_iqn and n.portal == session.portal:
                    n.is_connected = False
                    n.session_id = None
            mode_label = "Force-terminated hung session" if force_kill_hung else "Safely unmounted and disconnected"
            self._log(" && ".join(steps), True, f"{mode_label} {session.target_iqn}")
            return True, f"{mode_label}: {session.target_iqn}"

        cmds: List[str] = []
        if force_kill_hung:
            # Drop kernel recovery timeout to 0 so blocked SCSI commands fail immediately
            sys_tmo = f"/sys/class/iscsi_session/session{session.session_id}/recovery_tmo"
            cmds.append(f"([ -w '{sys_tmo}' ] && echo 0 > '{sys_tmo}' || true)")
            cmds.append(
                f"{self.iscsiadm_path} -m node -T '{session.target_iqn}' -p '{session.portal}' "
                f"-o update -n node.session.timeo.replacement_timeout -v 0 || true"
            )

        if safe_unmount or force_kill_hung:
            if not force_kill_hung:
                cmds.append("sync")
            for dev in session.block_devices:
                for mp in dev.mountpoints:
                    if force_kill_hung:
                        cmds.append(f"umount -l '{mp}' || true")
                    else:
                        cmds.append(f"umount '{mp}'")
                if dev.multipath_dm:
                    mpath_dev = dev.multipath_dm.split()[0]
                    cmds.append(f"(command -v multipath >/dev/null && multipath -f '{mpath_dev}' || true)")

        cmds.append(
            f"{self.iscsiadm_path} -m node -T '{session.target_iqn}' -p '{session.portal}' --logout"
        )
        return self._run_privileged_script(
            cmds,
            f"{'Force terminate' if force_kill_hung else 'Safe disconnect'} {session.target_iqn}",
        )

    def terminate_all_sessions(self, force: bool = False) -> Tuple[bool, str]:
        """Disconnect all active sessions (e.g. before putting laptop to sleep or leaving LAN)."""
        sessions = self.get_active_sessions(check_reachability=False)
        if not sessions:
            return True, "No active iSCSI sessions to terminate."

        if self.demo_mode:
            count = len(self._demo_sessions)
            self._demo_sessions.clear()
            for n in self._demo_nodes:
                n.is_connected = False
                n.session_id = None
            self._log(
                "iscsiadm -m node --logoutall=all",
                True,
                f"Disconnected all {count} active sessions (Demo Mode)",
            )
            return True, f"Safely terminated all {count} iSCSI sessions. Safe to undock/sleep."

        cmds: List[str] = []
        if not force:
            cmds.append("sync")
        for s in sessions:
            if force:
                sys_tmo = f"/sys/class/iscsi_session/session{s.session_id}/recovery_tmo"
                cmds.append(f"([ -w '{sys_tmo}' ] && echo 0 > '{sys_tmo}' || true)")
            for dev in s.block_devices:
                for mp in dev.mountpoints:
                    cmds.append(f"umount {'-l ' if force else ''}'{mp}' || true")
        cmds.append(f"{self.iscsiadm_path} -m node --logoutall=all")
        return self._run_privileged_script(cmds, "Disconnect all iSCSI sessions")

    def delete_node(self, target_iqn: str, portal: str) -> Tuple[bool, str]:
        """Delete a discovered node record from the open-iscsi database."""
        if self.demo_mode:
            for s in self._demo_sessions:
                if s.target_iqn == target_iqn and s.portal == portal:
                    return False, "Cannot delete a node while it has an active session. Terminate it first."
            self._demo_nodes = [
                n for n in self._demo_nodes if not (n.target_iqn == target_iqn and n.portal == portal)
            ]
            self._log(
                f"iscsiadm -m node -T {target_iqn} -p {portal} -o delete",
                True,
                f"Deleted node record {target_iqn}",
            )
            return True, f"Deleted node profile {target_iqn}"

        return self._run_cmd(
            [self.iscsiadm_path, "-m", "node", "-T", target_iqn, "-p", portal, "-o", "delete"],
            privileged=True,
        )

    def rescan_sessions(self) -> Tuple[bool, str]:
        """Rescan all active sessions for new or resized LUNs (`iscsiadm -m session --rescan`)."""
        if self.demo_mode:
            self._log("iscsiadm -m session --rescan", True, "Rescanned all active SCSI hosts and LUNs.")
            return True, "Rescanned all active iSCSI sessions for new or resized LUNs."

        return self._run_cmd([self.iscsiadm_path, "-m", "session", "--rescan"], privileged=True)
