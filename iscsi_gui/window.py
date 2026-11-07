"""Main GTK4 + Libadwaita window for iSCSI Pulse."""

from collections import deque
from typing import Deque, List
import uuid

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from . import __app_id__, __app_name__, __version__
from .backend import ISCSIBackend
from .dialogs import DiscoveryDialog, NodeConfigDialog, TerminateSessionDialog
from .models import ActiveSession, DiscoveredNode
from .monitor import format_bytes_rate


CUSTOM_CSS = """
.status-badge {
    padding: 3px 10px;
    border-radius: 999px;
    font-weight: 700;
    font-size: 0.82em;
}
.badge-healthy {
    background-color: rgba(46, 194, 126, 0.18);
    color: #2ec27e;
}
.badge-danger {
    background-color: rgba(224, 27, 36, 0.22);
    color: #ff6b6b;
}
.badge-warning {
    background-color: rgba(245, 194, 17, 0.20);
    color: #f5c211;
}
.badge-neutral {
    background-color: rgba(150, 150, 150, 0.18);
}
.metric-card {
    padding: 14px 18px;
    border-radius: 12px;
    background-color: alpha(@card_bg_color, 0.85);
    border: 1px solid alpha(@borders, 0.5);
}
.metric-title {
    font-size: 0.82em;
    opacity: 0.72;
    font-weight: 600;
}
.metric-value {
    font-size: 1.45em;
    font-weight: 800;
}
"""


class ThroughputChart(Gtk.DrawingArea):
    """Cairo-rendered live 60-second Read/Write throughput graph."""

    def __init__(self) -> None:
        super().__init__()
        self.set_content_height(190)
        self.set_hexpand(True)
        self.read_history: Deque[float] = deque([0.0] * 60, maxlen=60)
        self.write_history: Deque[float] = deque([0.0] * 60, maxlen=60)
        self.set_draw_func(self._on_draw)

    def push_sample(self, read_bps: float, write_bps: float) -> None:
        self.read_history.append(read_bps / (1024.0 * 1024.0))
        self.write_history.append(write_bps / (1024.0 * 1024.0))
        self.queue_draw()

    def _on_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        pad_l, pad_r, pad_t, pad_b = 48.0, 16.0, 18.0, 26.0
        plot_w = max(10.0, width - pad_l - pad_r)
        plot_h = max(10.0, height - pad_t - pad_b)

        # Background
        cr.set_source_rgba(0.12, 0.14, 0.18, 0.45)
        cr.rectangle(pad_l, pad_t, plot_w, plot_h)
        cr.fill()

        max_val = max(max(self.read_history, default=1.0), max(self.write_history, default=1.0), 10.0) * 1.15

        # Grid lines
        cr.set_line_width(1.0)
        for i in range(5):
            y = pad_t + plot_h * (i / 4.0)
            cr.set_source_rgba(0.5, 0.55, 0.62, 0.22)
            cr.move_to(pad_l, y)
            cr.line_to(pad_l + plot_w, y)
            cr.stroke()

            val = max_val * (1.0 - i / 4.0)
            cr.set_source_rgba(0.75, 0.78, 0.82, 0.85)
            cr.set_font_size(10.0)
            cr.move_to(4.0, y + 4.0)
            cr.show_text(f"{val:.0f}M")

        def draw_series(series: Deque[float], r: float, g: float, b: float) -> None:
            pts = list(series)
            if len(pts) < 2:
                return
            step_x = plot_w / (len(pts) - 1)

            # Fill area
            cr.move_to(pad_l, pad_t + plot_h)
            for idx, v in enumerate(pts):
                x = pad_l + idx * step_x
                y = pad_t + plot_h - (min(v, max_val) / max_val) * plot_h
                cr.line_to(x, y)
            cr.line_to(pad_l + plot_w, pad_t + plot_h)
            cr.close_path()
            cr.set_source_rgba(r, g, b, 0.18)
            cr.fill()

            # Stroke line
            cr.set_line_width(2.2)
            for idx, v in enumerate(pts):
                x = pad_l + idx * step_x
                y = pad_t + plot_h - (min(v, max_val) / max_val) * plot_h
                if idx == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.set_source_rgba(r, g, b, 0.95)
            cr.stroke()

        # Read (Cyan/Green) & Write (Amber/Orange)
        draw_series(self.read_history, 0.18, 0.76, 0.50)
        draw_series(self.write_history, 0.96, 0.58, 0.18)

        # Legend
        cr.set_font_size(11.0)
        cr.set_source_rgba(0.18, 0.76, 0.50, 0.95)
        cr.move_to(pad_l + 10, pad_t + 16)
        cr.show_text("■ Read (MB/s)")

        cr.set_source_rgba(0.96, 0.58, 0.18, 0.95)
        cr.move_to(pad_l + 120, pad_t + 16)
        cr.show_text("■ Write (MB/s)")


class ISCSIMainWindow(Adw.ApplicationWindow):
    """Primary application window for iSCSI Pulse."""

    def __init__(self, app: Adw.Application, backend: ISCSIBackend) -> None:
        super().__init__(
            application=app,
            title=f"{__app_name__} — open-iscsi Termination & Connection Manager",
            default_width=1060,
            default_height=760,
        )
        self.backend = backend
        self._load_css()

        self.toast_overlay = Adw.ToastOverlay()
        toolbar_view = Adw.ToolbarView()

        # Header Bar with ViewSwitcher
        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        # Header Left Actions
        discover_btn = Gtk.Button(label="Discover Target", icon_name="network-server-symbolic")
        discover_btn.set_tooltip_text("Discover iSCSI targets via SendTargets")
        discover_btn.add_css_class("suggested-action")
        discover_btn.connect("clicked", lambda *_: self.open_discovery_dialog())
        header.pack_start(discover_btn)

        rescan_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        rescan_btn.set_tooltip_text("Rescan active iSCSI sessions for new/resized LUNs")
        rescan_btn.connect("clicked", self._on_rescan_clicked)
        header.pack_start(rescan_btn)

        # Header Right Actions: Undock / Disconnect All & Demo Mode Switch
        disconnect_all_btn = Gtk.Button(label="Undock / Terminate All")
        disconnect_all_btn.add_css_class("destructive-action")
        disconnect_all_btn.set_tooltip_text(
            "Safely sync, unmount, and disconnect all active iSCSI sessions before laptop sleep or roaming"
        )
        disconnect_all_btn.connect("clicked", self._on_terminate_all_clicked)
        header.pack_end(disconnect_all_btn)

        toolbar_view.add_top_bar(header)

        # Demo mode info banner if active
        self.demo_banner = Adw.Banner(
            title="Sandbox Demo Mode Active — Simulating live NAS/SAN sessions, hung target recovery, and disk I/O. Toggle in System tab.",
            button_label="Switch to Live System" if self.backend.has_iscsiadm else "",
            revealed=self.backend.demo_mode,
        )
        self.demo_banner.connect("button-clicked", self._toggle_demo_from_banner)
        toolbar_view.add_top_bar(self.demo_banner)

        # Build the 4 pages
        self._build_sessions_page()
        self._build_nodes_page()
        self._build_telemetry_page()
        self._build_system_page()

        toolbar_view.set_content(self.view_stack)
        self.toast_overlay.set_child(toolbar_view)
        self.set_content(self.toast_overlay)

        # Initial data load + 1.5s live refresh timer
        self.refresh_all()
        GLib.timeout_add(1500, self._on_periodic_tick)

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CUSTOM_CSS.encode("utf-8"))
        display = self.get_display()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def show_toast(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)

    def _make_badge(self, text: str, style_class: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
        lbl.add_css_class("status-badge")
        lbl.add_css_class(style_class)
        return lbl

    def _clear_box(self, box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            box.remove(child)
            child = next_child

    # -------------------------------------------------------------------------
    # Page 1: Active Sessions & Termination Control
    # -------------------------------------------------------------------------
    def _build_sessions_page(self) -> None:
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=940, margin_top=18, margin_bottom=28, margin_start=16, margin_end=16)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)

        # Top KPI metric cards row
        kpi_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)

        self.kpi_active_lbl = Gtk.Label(label="0", xalign=0)
        self.kpi_active_lbl.add_css_class("metric-value")
        kpi_grid.append(self._wrap_metric_card("ACTIVE SESSIONS", self.kpi_active_lbl))

        self.kpi_health_lbl = Gtk.Label(label="All Healthy", xalign=0)
        self.kpi_health_lbl.add_css_class("metric-value")
        kpi_grid.append(self._wrap_metric_card("SESSION HEALTH", self.kpi_health_lbl))

        self.kpi_mounts_lbl = Gtk.Label(label="0 Mounted", xalign=0)
        self.kpi_mounts_lbl.add_css_class("metric-value")
        kpi_grid.append(self._wrap_metric_card("MOUNTED VOLUMES", self.kpi_mounts_lbl))

        self.kpi_io_lbl = Gtk.Label(label="0 B/s", xalign=0)
        self.kpi_io_lbl.add_css_class("metric-value")
        kpi_grid.append(self._wrap_metric_card("LIVE THROUGHPUT", self.kpi_io_lbl))

        root.append(kpi_grid)

        # Container for dynamic session cards
        self.sessions_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.append(self.sessions_list_box)

        clamp.set_child(root)
        scrolled.set_child(clamp)
        self.view_stack.add_titled_with_icon(
            scrolled, "sessions", "Active Sessions", "drive-harddisk-ieee1394-symbolic"
        )

    def _wrap_metric_card(self, title: str, value_widget: Gtk.Widget) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("metric-card")
        t_lbl = Gtk.Label(label=title, xalign=0)
        t_lbl.add_css_class("metric-title")
        card.append(t_lbl)
        card.append(value_widget)
        return card

    # -------------------------------------------------------------------------
    # Page 2: Discovered Targets & Profiles
    # -------------------------------------------------------------------------
    def _build_nodes_page(self) -> None:
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=940, margin_top=18, margin_bottom=28, margin_start=16, margin_end=16)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        self.nodes_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.append(self.nodes_list_box)

        clamp.set_child(root)
        scrolled.set_child(clamp)
        self.view_stack.add_titled_with_icon(
            scrolled, "nodes", "Targets & Profiles", "network-server-symbolic"
        )

    # -------------------------------------------------------------------------
    # Page 3: Live I/O & Health Telemetry
    # -------------------------------------------------------------------------
    def _build_telemetry_page(self) -> None:
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=940, margin_top=18, margin_bottom=28, margin_start=16, margin_end=16)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        chart_group = Adw.PreferencesGroup(
            title="Aggregate iSCSI Block Throughput (Last 60 Seconds)",
            description="Live Read/Write bandwidth across all attached iSCSI LUNs (/proc/diskstats).",
        )
        self.chart = ThroughputChart()
        chart_frame = Gtk.Frame(child=self.chart)
        chart_group.add(chart_frame)
        root.append(chart_group)

        self.telemetry_devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.append(self.telemetry_devices_box)

        clamp.set_child(root)
        scrolled.set_child(clamp)
        self.view_stack.add_titled_with_icon(
            scrolled, "telemetry", "Live I/O & Health", "utilities-system-monitor-symbolic"
        )

    # -------------------------------------------------------------------------
    # Page 4: Initiator & Audit Log
    # -------------------------------------------------------------------------
    def _build_system_page(self) -> None:
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=940, margin_top=18, margin_bottom=28, margin_start=16, margin_end=16)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        init_group = Adw.PreferencesGroup(
            title="Host iSCSI Initiator Identity",
            description="Configured in /etc/iscsi/initiatorname.iscsi. Must match ACLs on your SAN/NAS targets.",
        )
        self.iqn_entry_row = Adw.EntryRow(title="Initiator IQN")
        self.iqn_entry_row.set_text(self.backend.get_initiator_name())

        gen_btn = Gtk.Button(label="Generate IQN", valign=Gtk.Align.CENTER)
        gen_btn.connect("clicked", self._on_generate_iqn)
        self.iqn_entry_row.add_suffix(gen_btn)

        save_iqn_btn = Gtk.Button(label="Save & Restart iscsid", valign=Gtk.Align.CENTER)
        save_iqn_btn.add_css_class("suggested-action")
        save_iqn_btn.connect("clicked", self._on_save_initiator_iqn)
        self.iqn_entry_row.add_suffix(save_iqn_btn)
        init_group.add(self.iqn_entry_row)

        self.service_row = Adw.ActionRow(
            title="open-iscsi Daemon (iscsid.service)",
            subtitle="Checking status...",
        )
        init_group.add(self.service_row)

        self.demo_switch_row = Adw.SwitchRow(
            title="Interactive Sandbox / Demo Mode",
            subtitle="Simulate targets, hung sessions, and live I/O without modifying system open-iscsi state",
            active=self.backend.demo_mode,
        )
        self.demo_switch_row.connect("notify::active", self._on_demo_switch_changed)
        init_group.add(self.demo_switch_row)
        root.append(init_group)

        # Command Audit Log
        self.audit_group = Adw.PreferencesGroup(
            title="Privileged Command and iscsiadm Audit Log",
            description="Every command executed by iSCSI Pulse (or simulated in Demo Mode) is logged below for transparency.",
        )
        self.audit_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.audit_group.add(self.audit_list_box)
        root.append(self.audit_group)

        clamp.set_child(root)
        scrolled.set_child(clamp)
        self.view_stack.add_titled_with_icon(
            scrolled, "system", "Initiator & Audit Log", "preferences-system-symbolic"
        )

    # -------------------------------------------------------------------------
    # Rendering & Periodic Refresh
    # -------------------------------------------------------------------------
    def _on_periodic_tick(self) -> bool:
        self.refresh_sessions_and_telemetry()
        return True

    def refresh_all(self) -> None:
        self.refresh_sessions_and_telemetry()
        self.refresh_nodes()
        self.refresh_system_tab()

    def refresh_sessions_and_telemetry(self) -> None:
        sessions = self.backend.get_active_sessions(check_reachability=True)
        self._render_sessions(sessions)
        self._render_telemetry(sessions)

    def _render_sessions(self, sessions: List[ActiveSession]) -> None:
        self._clear_box(self.sessions_list_box)

        unhealthy_count = sum(1 for s in sessions if not s.is_healthy)
        mounted_count = sum(len(d.mountpoints) for s in sessions for d in s.block_devices)
        total_r = sum(d.read_bps for s in sessions for d in s.block_devices)
        total_w = sum(d.write_bps for s in sessions for d in s.block_devices)

        self.kpi_active_lbl.set_text(str(len(sessions)))
        if not sessions:
            self.kpi_health_lbl.set_text("Idle")
        elif unhealthy_count > 0:
            self.kpi_health_lbl.set_text(f"{unhealthy_count} Hung / Unreachable!")
        else:
            self.kpi_health_lbl.set_text("100% Healthy")

        self.kpi_mounts_lbl.set_text(f"{mounted_count} Mounted")
        self.kpi_io_lbl.set_text(format_bytes_rate(total_r + total_w))

        if not sessions:
            status_page = Adw.StatusPage(
                icon_name="network-Checks-symbolic",
                title="No Active iSCSI Sessions",
                description="All iSCSI targets are currently disconnected. It is safe to put your laptop to sleep or switch networks.",
            )
            btn = Gtk.Button(label="Connect a Target Profile", halign=Gtk.Align.CENTER)
            btn.add_css_class("suggested-action")
            btn.add_css_class("pill")
            btn.connect("clicked", lambda *_: self.view_stack.set_visible_child_name("nodes"))
            status_page.set_child(btn)
            self.sessions_list_box.append(status_page)
            return

        for session in sessions:
            group = Adw.PreferencesGroup(
                title=f"Session [{session.session_id}] • {session.target_iqn}",
                description=f"Portal: {session.portal} ({session.transport.upper()})",
            )

            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, valign=Gtk.Align.CENTER)
            if session.is_healthy:
                lat_str = f" • {session.latency_ms:.1f} ms" if session.latency_ms is not None else ""
                header_box.append(
                    self._make_badge(f"LOGGED_IN{lat_str}", "badge-healthy")
                )
            else:
                header_box.append(
                    self._make_badge(
                        f"{session.session_state} / UNREACHABLE", "badge-danger"
                    )
                )
                force_btn = Gtk.Button(label="Force Unfreeze Now")
                force_btn.add_css_class("destructive-action")
                force_btn.set_tooltip_text(
                    "Set kernel recovery_tmo=0, lazy-unmount dead mounts, and kill hung session immediately"
                )
                force_btn.connect(
                    "clicked",
                    lambda _b, s=session: self._execute_termination(s, safe_unmount=True, force_kill=True),
                )
                header_box.append(force_btn)

            term_btn = Gtk.Button(label="Terminate Session...")
            if session.is_healthy:
                term_btn.add_css_class("destructive-action")
            term_btn.connect("clicked", lambda _b, s=session: self.open_terminate_dialog(s))
            header_box.append(term_btn)

            group.set_header_suffix(header_box)

            if session.block_devices:
                for dev in session.block_devices:
                    mount_txt = (
                        f"Mounted: {', '.join(dev.mountpoints)} ({dev.fstype})"
                        if dev.mountpoints
                        else f"Unmounted ({dev.fstype or 'raw block'})"
                    )
                    mpath_txt = f" • Multipath: {dev.multipath_dm}" if dev.multipath_dm else ""
                    io_txt = (
                        f"R: {format_bytes_rate(dev.read_bps)} ({dev.read_iops:.0f} IOPS)  |  "
                        f"W: {format_bytes_rate(dev.write_bps)} ({dev.write_iops:.0f} IOPS)"
                    )
                    row = Adw.ActionRow(
                        title=f"{dev.device_path} — {dev.size_human} {dev.model} (LUN {dev.lun_id})",
                        subtitle=f"{mount_txt}{mpath_txt}\n{io_txt}",
                    )
                    if dev.is_mounted:
                        row.add_suffix(self._make_badge("MOUNTED", "badge-warning"))
                    else:
                        row.add_suffix(self._make_badge("UNMOUNTED", "badge-neutral"))
                    group.add(row)
            else:
                group.add(
                    Adw.ActionRow(
                        title="No Block Devices Attached",
                        subtitle="Session is connected, but no SCSI block LUNs are exposed.",
                    )
                )

            self.sessions_list_box.append(group)

    def _render_telemetry(self, sessions: List[ActiveSession]) -> None:
        total_r = sum(d.read_bps for s in sessions for d in s.block_devices)
        total_w = sum(d.write_bps for s in sessions for d in s.block_devices)
        self.chart.push_sample(total_r, total_w)

        self._clear_box(self.telemetry_devices_box)
        dev_group = Adw.PreferencesGroup(
            title="Per-LUN I/O and Portal Latency Diagnostics",
            description="Real-time disk statistics and portal TCP reachability probes.",
        )
        any_devs = False
        for s in sessions:
            for d in s.block_devices:
                any_devs = True
                row = Adw.ActionRow(
                    title=f"{d.device_path} ({d.model} • {d.size_human}) → {s.portal_host}",
                    subtitle=(
                        f"Read: {format_bytes_rate(d.read_bps)} ({d.read_iops:.0f} IOPS)   •   "
                        f"Write: {format_bytes_rate(d.write_bps)} ({d.write_iops:.0f} IOPS)"
                    ),
                )
                if s.portal_reachable:
                    row.add_suffix(
                        self._make_badge(f"Portal OK ({s.latency_ms or 0.5} ms)", "badge-healthy")
                    )
                else:
                    row.add_suffix(self._make_badge("Portal TIMEOUT", "badge-danger"))
                dev_group.add(row)

        if not any_devs:
            dev_group.add(
                Adw.ActionRow(
                    title="No Active Block Devices",
                    subtitle="Connect to an iSCSI target to monitor live LUN IOPS and throughput.",
                )
            )
        self.telemetry_devices_box.append(dev_group)

    def refresh_nodes(self) -> None:
        self._clear_box(self.nodes_list_box)
        nodes = self.backend.get_discovered_nodes()

        group = Adw.PreferencesGroup(
            title=f"Discovered Target Profiles ({len(nodes)})",
            description="Manage target authentication (CHAP), laptop-safe replacement timeouts, and connection state.",
        )

        add_btn = Gtk.Button(label="Discover New Portal...", valign=Gtk.Align.CENTER)
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", lambda *_: self.open_discovery_dialog())
        group.set_header_suffix(add_btn)

        if not nodes:
            group.add(
                Adw.ActionRow(
                    title="No Discovered Targets in Database",
                    subtitle="Click 'Discover New Portal...' to query an iSCSI server via SendTargets.",
                )
            )
        else:
            for node in nodes:
                chap_txt = f"CHAP ({node.chap.username})" if node.chap.enabled else "No Auth"
                tmo_s = node.timeouts.replacement_timeout
                tmo_txt = (
                    f"{tmo_s}s Laptop-Safe Timeout"
                    if tmo_s <= 30
                    else f"{tmo_s}s Timeout (High Freeze Risk on Wi-Fi/VPN)"
                )
                row = Adw.ActionRow(
                    title=node.target_iqn,
                    subtitle=f"Portal: {node.portal}  •  Startup: {node.startup_mode}  •  {chap_txt}  •  {tmo_txt}",
                )

                # Badges & Buttons
                if tmo_s > 30:
                    row.add_suffix(self._make_badge(f"{tmo_s}s tmo", "badge-warning"))
                else:
                    row.add_suffix(self._make_badge(f"{tmo_s}s safe", "badge-healthy"))

                cfg_btn = Gtk.Button(label="Configure", valign=Gtk.Align.CENTER)
                cfg_btn.connect("clicked", lambda _b, n=node: self.open_node_config_dialog(n))
                row.add_suffix(cfg_btn)

                if node.is_connected:
                    row.add_suffix(self._make_badge("CONNECTED", "badge-healthy"))
                else:
                    conn_btn = Gtk.Button(label="Connect", valign=Gtk.Align.CENTER)
                    conn_btn.add_css_class("suggested-action")
                    conn_btn.connect("clicked", lambda _b, n=node: self._on_connect_node(n))
                    row.add_suffix(conn_btn)

                    del_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                    del_btn.add_css_class("flat")
                    del_btn.set_tooltip_text("Delete target node record")
                    del_btn.connect("clicked", lambda _b, n=node: self._on_delete_node(n))
                    row.add_suffix(del_btn)

                group.add(row)

        self.nodes_list_box.append(group)

    def refresh_system_tab(self) -> None:
        active, status_txt = self.backend.get_service_status()
        self.service_row.set_subtitle(f"Status: {status_txt}")
        self.demo_banner.set_revealed(self.backend.demo_mode)

        self._clear_box(self.audit_list_box)
        if not self.backend.command_log:
            self.audit_list_box.append(
                Adw.ActionRow(
                    title="No commands executed yet",
                    subtitle="Actions such as discovery, login, CHAP updates, and session terminations will appear here.",
                )
            )
            return

        for entry in self.backend.command_log[:25]:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(f"[{entry.timestamp}]  {entry.command}"),
                subtitle=GLib.markup_escape_text(entry.output),
            )
            row.add_suffix(
                self._make_badge(
                    "OK" if entry.success else "ERR",
                    "badge-healthy" if entry.success else "badge-danger",
                )
            )
            self.audit_list_box.append(row)

    # -------------------------------------------------------------------------
    # User Action Handlers
    # -------------------------------------------------------------------------
    def open_discovery_dialog(self) -> None:
        dlg = DiscoveryDialog(self, self._handle_discover)
        dlg.present()

    def _handle_discover(self, host: str, port: int) -> None:
        ok, msg, _nodes = self.backend.discover_targets(host, port)
        self.show_toast(msg if ok else f"Discovery failed: {msg}")
        self.refresh_all()
        if ok:
            self.view_stack.set_visible_child_name("nodes")

    def open_node_config_dialog(self, node: DiscoveredNode) -> None:
        dlg = NodeConfigDialog(self, node, self._handle_node_save)
        dlg.present()

    def _handle_node_save(self, updated: DiscoveredNode, connect_now: bool) -> None:
        ok, msg = self.backend.configure_and_connect_node(
            target_iqn=updated.target_iqn,
            portal=updated.portal,
            startup_mode=updated.startup_mode,
            chap=updated.chap,
            timeouts=updated.timeouts,
            connect_now=connect_now,
        )
        self.show_toast(msg)
        self.refresh_all()
        if ok and connect_now:
            self.view_stack.set_visible_child_name("sessions")

    def _on_connect_node(self, node: DiscoveredNode) -> None:
        ok, msg = self.backend.login_node(node.target_iqn, node.portal)
        self.show_toast(msg if ok else f"Login failed: {msg}")
        self.refresh_all()
        if ok:
            self.view_stack.set_visible_child_name("sessions")

    def _on_delete_node(self, node: DiscoveredNode) -> None:
        ok, msg = self.backend.delete_node(node.target_iqn, node.portal)
        self.show_toast(msg)
        self.refresh_all()

    def open_terminate_dialog(self, session: ActiveSession) -> None:
        dlg = TerminateSessionDialog(self, session, self._execute_termination)
        dlg.present()

    def _execute_termination(
        self, session: ActiveSession, safe_unmount: bool, force_kill: bool
    ) -> None:
        ok, msg = self.backend.terminate_session(
            session, safe_unmount=safe_unmount, force_kill_hung=force_kill
        )
        self.show_toast(msg)
        self.refresh_all()

    def _on_terminate_all_clicked(self, _btn: Gtk.Button) -> None:
        sessions = self.backend.get_active_sessions(check_reachability=False)
        any_unhealthy = any(not s.is_healthy for s in sessions)
        ok, msg = self.backend.terminate_all_sessions(force=any_unhealthy)
        self.show_toast(msg)
        self.refresh_all()

    def _on_rescan_clicked(self, _btn: Gtk.Button) -> None:
        ok, msg = self.backend.rescan_sessions()
        self.show_toast(msg)
        self.refresh_all()

    def _on_generate_iqn(self, _btn: Gtk.Button) -> None:
        short_id = uuid.uuid4().hex[:8]
        new_iqn = f"iqn.2026-04.com.ubuntu:laptop-{short_id}"
        self.iqn_entry_row.set_text(new_iqn)

    def _on_save_initiator_iqn(self, _btn: Gtk.Button) -> None:
        ok, msg = self.backend.set_initiator_name(self.iqn_entry_row.get_text())
        self.show_toast(msg)
        self.refresh_system_tab()

    def _on_demo_switch_changed(self, switch_row: Adw.SwitchRow, _pspec) -> None:
        self.backend.demo_mode = switch_row.get_active()
        self.iqn_entry_row.set_text(self.backend.get_initiator_name())
        self.refresh_all()

    def _toggle_demo_from_banner(self, _banner: Adw.Banner) -> None:
        self.demo_switch_row.set_active(False)
