"""Unit tests for open-iscsi output parsers, session termination logic, and backend operations."""

import unittest

from iscsi_gui.backend import (
    ISCSIBackend,
    parse_iscsiadm_nodes,
    parse_iscsiadm_sessions,
    parse_node_kv_config,
)
from iscsi_gui.models import ChapConfig, TimeoutConfig


class TestISCSIParsersAndBackend(unittest.TestCase):
    def test_parse_iscsiadm_sessions(self) -> None:
        sample = (
            "tcp: [1] 192.168.10.20:3260,1 iqn.2026-01.lan.synology:nas-rack01.lun-media (non-flash)\n"
            "tcp: [2] 10.80.4.12:3260,1 iqn.2025-11.corp.san:branch-backup-archive (non-flash)\n"
        )
        sessions = parse_iscsiadm_sessions(sample)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].session_id, 1)
        self.assertEqual(sessions[0].portal_host, "192.168.10.20")
        self.assertEqual(sessions[0].portal_port, 3260)
        self.assertEqual(sessions[0].target_iqn, "iqn.2026-01.lan.synology:nas-rack01.lun-media")
        self.assertEqual(sessions[1].session_id, 2)

    def test_parse_iscsiadm_nodes(self) -> None:
        sample = (
            "192.168.10.20:3260,1 iqn.2026-01.lan.synology:nas-rack01.lun-media\n"
            "192.168.10.40:3260,1 iqn.2026-02.homelab.proxmox:ceph-iscsi-gw01\n"
        )
        nodes = parse_iscsiadm_nodes(sample)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0].portal_address, "192.168.10.20:3260")
        self.assertEqual(nodes[1].target_iqn, "iqn.2026-02.homelab.proxmox:ceph-iscsi-gw01")

    def test_parse_node_kv_config(self) -> None:
        sample = """
        # BEGIN RECORD 2.1.9
        node.name = iqn.2026-01.lan.synology:nas-rack01.lun-media
        node.startup = manual
        node.session.timeo.replacement_timeout = 15
        node.session.auth.authmethod = CHAP
        node.session.auth.username = dan_laptop
        # END RECORD
        """
        kv = parse_node_kv_config(sample)
        self.assertEqual(kv["node.startup"], "manual")
        self.assertEqual(kv["node.session.timeo.replacement_timeout"], "15")
        self.assertEqual(kv["node.session.auth.authmethod"], "CHAP")
        self.assertEqual(kv["node.session.auth.username"], "dan_laptop")

    def test_demo_backend_lifecycle(self) -> None:
        backend = ISCSIBackend(force_demo=True)
        sessions = backend.get_active_sessions()
        self.assertEqual(len(sessions), 3)

        # Force-terminate the hung session (#3)
        hung = [s for s in sessions if not s.is_healthy][0]
        ok, msg = backend.terminate_session(hung, safe_unmount=True, force_kill_hung=True)
        self.assertTrue(ok)
        self.assertIn("Force-terminated", msg)
        self.assertEqual(len(backend.get_active_sessions()), 2)

        # Discover a new target
        ok, msg, nodes = backend.discover_targets("192.168.10.99", 3260)
        self.assertTrue(ok)
        self.assertTrue(any("192-168-10-99" in n.target_iqn for n in nodes))

        # Configure and connect a disconnected target
        disconnected = [n for n in nodes if not n.is_connected][0]
        ok, msg = backend.configure_and_connect_node(
            target_iqn=disconnected.target_iqn,
            portal=disconnected.portal,
            startup_mode="manual",
            chap=ChapConfig(enabled=True, username="admin", password="secret"),
            timeouts=TimeoutConfig(replacement_timeout=15),
            connect_now=True,
        )
        self.assertTrue(ok)
        self.assertEqual(len(backend.get_active_sessions()), 3)

        # Terminate all sessions
        ok, msg = backend.terminate_all_sessions(force=False)
        self.assertTrue(ok)
        self.assertEqual(len(backend.get_active_sessions()), 0)


if __name__ == "__main__":
    unittest.main()
