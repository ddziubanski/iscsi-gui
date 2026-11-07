"""Live I/O throughput, IOPS, and portal TCP reachability monitoring."""

import socket
import time
from typing import Dict, Optional, Tuple


class DiskIOMonitor:
    """Reads /proc/diskstats to compute per-device Read/Write B/s and IOPS."""

    SECTOR_SIZE = 512

    def __init__(self) -> None:
        # Map device_name -> (timestamp, reads_completed, sectors_read, writes_completed, sectors_written)
        self._prev: Dict[str, Tuple[float, int, int, int, int]] = {}

    def sample(self) -> Dict[str, Tuple[float, float, float, float]]:
        """
        Sample /proc/diskstats and return a dict:
        device_name -> (read_bps, write_bps, read_iops, write_iops)
        """
        now = time.monotonic()
        results: Dict[str, Tuple[float, float, float, float]] = {}
        try:
            with open("/proc/diskstats", "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return results

        for line in lines:
            parts = line.split()
            if len(parts) < 14:
                continue
            dev_name = parts[2]
            try:
                reads_completed = int(parts[3])
                sectors_read = int(parts[5])
                writes_completed = int(parts[7])
                sectors_written = int(parts[9])
            except ValueError:
                continue

            if dev_name in self._prev:
                prev_t, prev_rc, prev_sr, prev_wc, prev_sw = self._prev[dev_name]
                dt = max(now - prev_t, 0.001)
                read_iops = max(0.0, (reads_completed - prev_rc) / dt)
                write_iops = max(0.0, (writes_completed - prev_wc) / dt)
                read_bps = max(0.0, (sectors_read - prev_sr) * self.SECTOR_SIZE / dt)
                write_bps = max(0.0, (sectors_written - prev_sw) * self.SECTOR_SIZE / dt)
                results[dev_name] = (read_bps, write_bps, read_iops, write_iops)
            else:
                results[dev_name] = (0.0, 0.0, 0.0, 0.0)

            self._prev[dev_name] = (
                now,
                reads_completed,
                sectors_read,
                writes_completed,
                sectors_written,
            )

        return results


def probe_portal_tcp(host: str, port: int = 3260, timeout: float = 0.75) -> Tuple[bool, Optional[float]]:
    """
    Perform a fast TCP connect probe to an iSCSI portal to detect network drops
    before kernel replacement_timeout hangs I/O.
    Returns (reachable, latency_ms).
    """
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = (time.monotonic() - t0) * 1000.0
            return True, round(latency_ms, 1)
    except OSError:
        return False, None


def format_bytes_rate(bps: float) -> str:
    """Format bytes/sec into human-readable string."""
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    if bps < 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / (1024 * 1024 * 1024):.2f} GB/s"
