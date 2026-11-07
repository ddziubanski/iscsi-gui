"""GTK4 / Libadwaita modal dialogs for Target Discovery, Node Auth/Timeout Config, and Safe/Force Termination."""

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .models import ActiveSession, ChapConfig, DiscoveredNode, TimeoutConfig


class DiscoveryDialog(Adw.Window):
    """Modal dialog to discover iSCSI targets via SendTargets."""

    def __init__(
        self,
        parent: Gtk.Window,
        on_discover: Callable[[str, int], None],
    ) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Discover iSCSI Targets (SendTargets)",
            default_width=480,
            default_height=340,
        )
        self._on_discover = on_discover

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        clamp = Adw.Clamp(maximum_size=440, margin_top=16, margin_bottom=20, margin_start=16, margin_end=16)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        group = Adw.PreferencesGroup(
            title="Portal Connection",
            description="Enter the IP address or hostname of your NAS / SAN iSCSI portal to query available targets via SendTargets.",
        )

        self.host_row = Adw.EntryRow(title="Portal IP or Hostname")
        self.host_row.set_text("192.168.10.50")
        group.add(self.host_row)

        adj = Gtk.Adjustment(value=3260, lower=1, upper=65535, step_increment=1, page_increment=10)
        self.port_row = Adw.SpinRow(title="TCP Port", subtitle="Standard iSCSI port is 3260", adjustment=adj)
        group.add(self.port_row)

        box.append(group)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())

        discover_btn = Gtk.Button(label="Discover Targets")
        discover_btn.add_css_class("suggested-action")
        discover_btn.add_css_class("pill")
        discover_btn.connect("clicked", self._on_submit)

        btn_box.append(cancel_btn)
        btn_box.append(discover_btn)
        box.append(btn_box)

        clamp.set_child(box)
        toolbar_view.set_content(clamp)
        self.set_content(toolbar_view)

    def _on_submit(self, _btn: Gtk.Button) -> None:
        host = self.host_row.get_text().strip()
        port = int(self.port_row.get_value())
        if not host:
            return
        self.close()
        self._on_discover(host, port)


class NodeConfigDialog(Adw.Window):
    """Modal dialog for configuring CHAP authentication, laptop-safe timeouts, and startup policy."""

    STARTUP_OPTIONS = ["manual", "automatic", "onboot"]

    def __init__(
        self,
        parent: Gtk.Window,
        node: DiscoveredNode,
        on_save: Callable[[DiscoveredNode, bool], None],
    ) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Configure & Connect Target",
            default_width=560,
            default_height=640,
        )
        self.node = node
        self._on_save = on_save

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=520, margin_top=16, margin_bottom=24, margin_start=16, margin_end=16)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        # Target Identity Group
        id_group = Adw.PreferencesGroup(
            title="Target Identity",
            description=f"Portal: {node.portal}",
        )
        iqn_row = Adw.ActionRow(title="Target IQN", subtitle=node.target_iqn)
        iqn_row.set_subtitle_selectable(True)
        id_group.add(iqn_row)

        startup_model = Gtk.StringList.new([
            "manual (Recommended for Laptops — connect on demand)",
            "automatic (Connect at service startup)",
            "onboot (Connect during early boot)",
        ])
        self.startup_row = Adw.ComboRow(
            title="Startup Mode",
            subtitle="Avoid 'automatic' on roaming laptops to prevent boot delays off-network",
            model=startup_model,
        )
        idx = self.STARTUP_OPTIONS.index(node.startup_mode) if node.startup_mode in self.STARTUP_OPTIONS else 0
        self.startup_row.set_selected(idx)
        id_group.add(self.startup_row)
        box.append(id_group)

        # Laptop Anti-Freeze & Timeout Tuning Group
        tmo_group = Adw.PreferencesGroup(
            title="Laptop Anti-Freeze and Session Timeouts",
            description="Linux open-iscsi defaults to a 120s replacement_timeout, which freezes file managers when Wi-Fi or VPN drops. Lowering it to 15s fails stalled I/O fast.",
        )

        preset_btn = Gtk.Button(label="Apply 15s Laptop Safe Preset", valign=Gtk.Align.CENTER)
        preset_btn.add_css_class("accent")
        preset_btn.connect("clicked", self._apply_laptop_preset)
        tmo_group.set_header_suffix(preset_btn)

        repl_adj = Gtk.Adjustment(
            value=node.timeouts.replacement_timeout,
            lower=0,
            upper=600,
            step_increment=5,
            page_increment=15,
        )
        self.repl_tmo_row = Adw.SpinRow(
            title="Replacement Timeout (seconds)",
            subtitle="node.session.timeo.replacement_timeout (15s recommended for laptops)",
            adjustment=repl_adj,
        )
        tmo_group.add(self.repl_tmo_row)

        noop_int_adj = Gtk.Adjustment(
            value=node.timeouts.noop_out_interval,
            lower=1,
            upper=60,
            step_increment=1,
            page_increment=5,
        )
        self.noop_interval_row = Adw.SpinRow(
            title="NOP-Out Ping Interval (seconds)",
            subtitle="node.conn[0].timeo.noop_out_interval",
            adjustment=noop_int_adj,
        )
        tmo_group.add(self.noop_interval_row)

        noop_tmo_adj = Gtk.Adjustment(
            value=node.timeouts.noop_out_timeout,
            lower=1,
            upper=60,
            step_increment=1,
            page_increment=5,
        )
        self.noop_timeout_row = Adw.SpinRow(
            title="NOP-Out Timeout (seconds)",
            subtitle="node.conn[0].timeo.noop_out_timeout",
            adjustment=noop_tmo_adj,
        )
        tmo_group.add(self.noop_timeout_row)
        box.append(tmo_group)

        # CHAP Authentication Group
        chap_group = Adw.PreferencesGroup(
            title="CHAP Authentication",
            description="Configure initiator-to-target and optional mutual CHAP credentials.",
        )
        self.chap_switch = Adw.SwitchRow(
            title="Enable CHAP Authentication",
            subtitle="node.session.auth.authmethod = CHAP",
            active=node.chap.enabled,
        )
        chap_group.add(self.chap_switch)

        self.user_row = Adw.EntryRow(title="Initiator CHAP Username")
        self.user_row.set_text(node.chap.username)
        chap_group.add(self.user_row)

        self.pass_row = Adw.PasswordEntryRow(title="Initiator CHAP Secret")
        self.pass_row.set_text(node.chap.password)
        chap_group.add(self.pass_row)

        self.mutual_switch = Adw.SwitchRow(
            title="Enable Mutual (Bidirectional) CHAP",
            subtitle="Verify target identity with reverse CHAP credentials",
            active=node.chap.mutual_enabled,
        )
        chap_group.add(self.mutual_switch)

        self.user_in_row = Adw.EntryRow(title="Mutual CHAP Target Username")
        self.user_in_row.set_text(node.chap.username_in)
        chap_group.add(self.user_in_row)

        self.pass_in_row = Adw.PasswordEntryRow(title="Mutual CHAP Target Secret")
        self.pass_in_row.set_text(node.chap.password_in)
        chap_group.add(self.pass_in_row)
        box.append(chap_group)

        # Action Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())

        save_only_btn = Gtk.Button(label="Save Profile Only")
        save_only_btn.connect("clicked", lambda *_: self._submit(connect_now=False))

        connect_btn = Gtk.Button(
            label="Save & Reconnect" if node.is_connected else "Save & Connect Now"
        )
        connect_btn.add_css_class("suggested-action")
        connect_btn.add_css_class("pill")
        connect_btn.connect("clicked", lambda *_: self._submit(connect_now=True))

        btn_box.append(cancel_btn)
        btn_box.append(save_only_btn)
        btn_box.append(connect_btn)
        box.append(btn_box)

        clamp.set_child(box)
        scrolled.set_child(clamp)
        toolbar_view.set_content(scrolled)
        self.set_content(toolbar_view)

    def _apply_laptop_preset(self, _btn: Gtk.Button) -> None:
        self.repl_tmo_row.set_value(15)
        self.noop_interval_row.set_value(5)
        self.noop_timeout_row.set_value(5)
        self.startup_row.set_selected(0)

    def _submit(self, connect_now: bool) -> None:
        sel = self.startup_row.get_selected()
        startup = self.STARTUP_OPTIONS[sel] if 0 <= sel < len(self.STARTUP_OPTIONS) else "manual"

        updated = DiscoveredNode(
            target_iqn=self.node.target_iqn,
            portal=self.node.portal,
            startup_mode=startup,
            chap=ChapConfig(
                enabled=self.chap_switch.get_active(),
                username=self.user_row.get_text().strip(),
                password=self.pass_row.get_text(),
                mutual_enabled=self.mutual_switch.get_active(),
                username_in=self.user_in_row.get_text().strip(),
                password_in=self.pass_in_row.get_text(),
            ),
            timeouts=TimeoutConfig(
                replacement_timeout=int(self.repl_tmo_row.get_value()),
                noop_out_interval=int(self.noop_interval_row.get_value()),
                noop_out_timeout=int(self.noop_timeout_row.get_value()),
            ),
            is_connected=self.node.is_connected,
            session_id=self.node.session_id,
        )
        self.close()
        self._on_save(updated, connect_now)


class TerminateSessionDialog(Adw.Window):
    """Modal dialog for safely unmounting & disconnecting OR force-terminating a stuck iSCSI session."""

    def __init__(
        self,
        parent: Gtk.Window,
        session: ActiveSession,
        on_confirm: Callable[[ActiveSession, bool, bool], None],
    ) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Terminate iSCSI Session",
            default_width=540,
            default_height=480,
        )
        self.session = session
        self._on_confirm = on_confirm

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        clamp = Adw.Clamp(maximum_size=500, margin_top=16, margin_bottom=20, margin_start=16, margin_end=16)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        if not session.is_healthy:
            banner = Adw.Banner(
                title="Target portal is unreachable or session is in FAILED/TRANSPORT_WAIT state. Use Force Terminate to immediately unfreeze blocked I/O.",
                revealed=True,
            )
            banner.add_css_class("error")
            box.append(banner)

        info_group = Adw.PreferencesGroup(
            title=f"Session [{session.session_id}] — {session.portal}",
            description=session.target_iqn,
        )

        state_row = Adw.ActionRow(
            title="Session / Connection State",
            subtitle=f"{session.session_state} / {session.connection_state} "
            f"({'Reachable' if session.portal_reachable else 'UNREACHABLE'})",
        )
        info_group.add(state_row)

        if session.block_devices:
            for dev in session.block_devices:
                mps = ", ".join(dev.mountpoints) if dev.mountpoints else "Not mounted"
                mpath = f" • Multipath: {dev.multipath_dm}" if dev.multipath_dm else ""
                dev_row = Adw.ActionRow(
                    title=f"{dev.device_path} ({dev.size_human} {dev.model})",
                    subtitle=f"Mountpoints: {mps}{mpath}",
                )
                info_group.add(dev_row)
        else:
            no_dev = Adw.ActionRow(
                title="Attached Block Devices",
                subtitle="No block LUNs currently mapped",
            )
            info_group.add(no_dev)

        box.append(info_group)

        opts_group = Adw.PreferencesGroup(
            title="Termination Options",
            description="Prevent filesystem corruption and hung mounts before logging out of the target.",
        )
        self.unmount_switch = Adw.SwitchRow(
            title="Sync and Unmount Attached Filesystems First",
            subtitle="Flushes disk buffers (sync), unmounts partitions, and flushes multipath maps before logout",
            active=True,
        )
        opts_group.add(self.unmount_switch)
        box.append(opts_group)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())

        safe_btn = Gtk.Button(label="Safe Disconnect")
        safe_btn.add_css_class("suggested-action")
        safe_btn.connect("clicked", self._on_safe)

        force_btn = Gtk.Button(label="Force Terminate (Unfreeze Hung I/O)")
        force_btn.add_css_class("destructive-action")
        force_btn.connect("clicked", self._on_force)

        btn_box.append(cancel_btn)
        btn_box.append(safe_btn)
        btn_box.append(force_btn)
        box.append(btn_box)

        clamp.set_child(box)
        toolbar_view.set_content(clamp)
        self.set_content(toolbar_view)

    def _on_safe(self, _btn: Gtk.Button) -> None:
        unmount = self.unmount_switch.get_active()
        self.close()
        self._on_confirm(self.session, unmount, False)

    def _on_force(self, _btn: Gtk.Button) -> None:
        self.close()
        self._on_confirm(self.session, True, True)
