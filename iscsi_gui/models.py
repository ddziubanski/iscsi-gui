"""Data models for iSCSI sessions, nodes, block devices, authentication, and telemetry."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChapConfig:
    """CHAP and Mutual CHAP authentication settings for an iSCSI node."""
    enabled: bool = False
    username: str = ""
    password: str = ""
    mutual_enabled: bool = False
    username_in: str = ""
    password_in: str = ""


@dataclass
class TimeoutConfig:
    """Session and laptop-friendly recovery timeout configuration."""
    replacement_timeout: int = 15  # Default open-iscsi is 120s; 15s prevents laptop freezes
    noop_out_interval: int = 5
    noop_out_timeout: int = 5
    login_timeout: int = 15


@dataclass
class BlockDeviceInfo:
    """Block device (LUN) attached to an active iSCSI session."""
    device_name: str               # e.g., "sdb"
    device_path: str               # e.g., "/dev/sdb"
    size_human: str = "Unknown"    # e.g., "500.0 GB"
    model: str = "Virtual Disk"
    lun_id: int = 0
    multipath_dm: Optional[str] = None  # e.g., "dm-2 (mpatha)"
    mountpoints: List[str] = field(default_factory=list)
    fstype: str = ""
    read_bps: float = 0.0          # Bytes/sec
    write_bps: float = 0.0         # Bytes/sec
    read_iops: float = 0.0
    write_iops: float = 0.0

    @property
    def is_mounted(self) -> bool:
        return len(self.mountpoints) > 0


@dataclass
class ActiveSession:
    """Represents a currently connected or hung iSCSI session."""
    session_id: int
    target_iqn: str
    portal: str                    # e.g., "192.168.1.50:3260,1"
    transport: str = "tcp"
    session_state: str = "LOGGED_IN"   # e.g., LOGGED_IN, FAILED, FREE
    connection_state: str = "LOGGED_IN"
    portal_reachable: bool = True
    latency_ms: Optional[float] = None
    block_devices: List[BlockDeviceInfo] = field(default_factory=list)

    @property
    def portal_host(self) -> str:
        addr = self.portal.split(",")[0]
        if ":" in addr:
            return addr.rsplit(":", 1)[0].strip("[]")
        return addr

    @property
    def portal_port(self) -> int:
        addr = self.portal.split(",")[0]
        if ":" in addr:
            try:
                return int(addr.rsplit(":", 1)[1])
            except ValueError:
                return 3260
        return 3260

    @property
    def is_healthy(self) -> bool:
        return (
            self.session_state == "LOGGED_IN"
            and self.connection_state == "LOGGED_IN"
            and self.portal_reachable
        )

    @property
    def has_mounted_volumes(self) -> bool:
        return any(dev.is_mounted for dev in self.block_devices)


@dataclass
class DiscoveredNode:
    """Represents an iSCSI target node stored in the local open-iscsi database."""
    target_iqn: str
    portal: str                    # e.g., "192.168.1.50:3260,1"
    startup_mode: str = "manual"   # manual, automatic, onboot
    chap: ChapConfig = field(default_factory=ChapConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    is_connected: bool = False
    session_id: Optional[int] = None

    @property
    def portal_address(self) -> str:
        return self.portal.split(",")[0]


@dataclass
class CommandLogEntry:
    """Audit log entry of executed iscsiadm / system operations."""
    timestamp: str
    command: str
    success: bool
    output: str
