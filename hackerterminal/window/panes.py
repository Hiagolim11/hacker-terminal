"""Split panes inside a tab: layout, focus, broadcast, bell and closing."""

from __future__ import annotations

from pathlib import Path

from ..runtime import GLib, Gtk
from ..session import MAX_PANES_PER_TAB
from ..terminal import TerminalPane


class PanesMixin:
    """Part of HackerTerminal: split panes inside a tab: layout, focus, broadcast, bell and closing."""

    def focus_other_pane(self) -> None:
        frame = self.active_frame()
        panes = self.leaves(frame.get_child()) if frame is not None else []
        active = self.get_active_terminal()
        if len(panes) > 1 and active in panes:
            target = panes[(panes.index(active) + 1) % len(panes)]
            target.terminal.grab_focus()

    def split_horizontal(self) -> None:
        self.split_active(Gtk.Orientation.HORIZONTAL)

    def rebuild_layout(self, frame: Gtk.Frame, pane: TerminalPane, node, directories) -> None:
        """Replay a saved split tree; ``pane`` already shows its first leaf."""
        if not isinstance(node, list):
            return
        kind, first, second = node[:3]
        ratio = node[3] if len(node) == 4 else 0.5
        orientation = Gtk.Orientation.HORIZONTAL if kind == "horizontal" else Gtk.Orientation.VERTICAL
        second_pane = self.split_pane(frame, pane, orientation, directories[self.first_leaf(second)], ratio)
        self.rebuild_layout(frame, pane, first, directories)
        self.rebuild_layout(frame, second_pane, second, directories)

    @staticmethod
    def first_leaf(node) -> int:
        while isinstance(node, list):
            node = node[1]
        return node

    def toggle_broadcast(self, frame: Gtk.Frame | None = None) -> None:
        frame = frame or self.active_frame()
        if frame is None:
            return
        if frame in self.broadcast_frames:
            self.broadcast_frames.discard(frame)
            self.show_toast("Transmissão desligada: cada painel recebe só a própria digitação.")
        else:
            panes = self.page_panes.get(frame, [])
            if len(panes) < 2:
                self.show_toast("Divida a aba (Ctrl+Shift+D ou E) para transmitir a digitação a vários painéis.")
                return
            self.broadcast_frames.add(frame)
            self.show_toast(f"Transmitindo: o que você digitar vai para os {len(panes)} painéis desta aba.")
        self.update_broadcast(frame)

    def update_broadcast(self, frame: Gtk.Frame) -> None:
        panes = self.page_panes.get(frame, [])
        if len(panes) < 2:
            self.broadcast_frames.discard(frame)
        active = frame in self.broadcast_frames
        for pane in panes:
            pane.broadcast_peers = [peer for peer in panes if peer is not pane] if active else []
        context = frame.get_style_context()
        if active:
            context.add_class("broadcast")
        else:
            context.remove_class("broadcast")
        label = self.tab_labels.get(panes[0]) if panes else None
        if label is not None:
            box_context = label.get_parent().get_style_context()
            if active:
                box_context.add_class("tab-broadcast")
            else:
                box_context.remove_class("tab-broadcast")
        self.update_status()

    def on_pane_bell(self, pane: TerminalPane) -> None:
        if self.is_active() and pane is self.get_active_terminal():
            pane.bell_pending = False
            return
        if not self.is_active():
            self.set_urgency_hint(True)
        label = self.tab_labels.get(pane)
        if label is not None:
            label.get_parent().get_style_context().add_class("tab-bell")

    def clear_bell(self, pane: TerminalPane | None) -> None:
        self.set_urgency_hint(False)
        if pane is None:
            return
        pane.bell_pending = False
        label = self.tab_labels.get(pane)
        frame = self.frame_for_pane(pane)
        others = [item for item in self.page_panes.get(frame, []) if item is not pane and item.bell_pending]
        if label is not None and not others:
            label.get_parent().get_style_context().remove_class("tab-bell")
        if label is not None:
            label.get_parent().get_style_context().remove_class("tab-done")
        application = self.get_application()
        if application is not None:
            application.withdraw_notification(f"command-{pane.pane_id}")

    def update_pane_highlight(self, frame: Gtk.Frame) -> None:
        panes = self.page_panes.get(frame, [])
        active = self.active_panes.get(frame)
        for item in panes:
            context = item.get_style_context()
            if len(panes) > 1 and item is not active:
                context.add_class("pane-inactive")
            else:
                context.remove_class("pane-inactive")

    def split_active(
        self,
        orientation: Gtk.Orientation,
        working_directory: Path | None = None,
    ) -> TerminalPane | None:
        frame = self.active_frame()
        pane = self.get_active_terminal()
        if frame is None or pane is None or self.config.command:
            return None
        if len(self.page_panes.get(frame, [])) >= MAX_PANES_PER_TAB:
            self.show_info(f"Cada aba comporta até {MAX_PANES_PER_TAB} painéis. Abra uma nova aba com Ctrl+Shift+T.")
            return None
        return self.split_pane(frame, pane, orientation, working_directory or pane.current_working_directory())

    def split_pane(
        self, frame: Gtk.Frame, pane: TerminalPane, orientation: Gtk.Orientation, directory: Path,
        ratio: float = 0.5,
    ) -> TerminalPane:
        """Replace ``pane`` by a split holding it and a new pane."""
        allocation = pane.get_allocation()
        parent = pane.get_parent()
        new_pane = self.create_terminal((), directory)
        split = Gtk.Paned(orientation=orientation)
        if isinstance(parent, Gtk.Paned):
            first_slot = parent.get_child1() is pane
            parent.remove(pane)
            if first_slot:
                parent.pack1(split, resize=True, shrink=True)
            else:
                parent.pack2(split, resize=True, shrink=True)
        else:
            frame.remove(pane)
            frame.add(split)
        split.pack1(pane, resize=True, shrink=True)
        split.pack2(new_pane, resize=True, shrink=True)
        self.page_panes[frame].append(new_pane)
        self.active_panes[frame] = new_pane
        self.tab_labels[new_pane] = self.tab_labels[pane]
        frame.show_all()
        size = allocation.width if orientation == Gtk.Orientation.HORIZONTAL else allocation.height
        if size > 1:
            split.set_position(round(size * ratio))
        else:
            self.position_when_allocated(split, ratio)
        self.update_pane_highlight(frame)
        new_pane.spawn()
        self.update_broadcast(frame)
        return new_pane

    @staticmethod
    def position_when_allocated(split: Gtk.Paned, ratio: float = 0.5) -> None:
        """Apply the split ratio once the paned has a real size (restored layouts).

        Until then the ratio stays on the paned, so saving a tab that was
        never shown keeps its sizes instead of forgetting them.
        """
        split.pending_ratio = ratio

        def on_allocate(widget, allocation) -> None:
            size = allocation.width if widget.get_orientation() == Gtk.Orientation.HORIZONTAL else allocation.height
            if size <= 1:
                return
            widget.disconnect(handler[0])

            def apply() -> bool:
                widget.set_position(round(size * ratio))
                widget.pending_ratio = None
                return False

            # Changing the position inside size-allocate would re-queue a resize.
            GLib.idle_add(apply)

        handler = [split.connect("size-allocate", on_allocate)]

    @staticmethod
    def leaves(widget: Gtk.Widget) -> list[TerminalPane]:
        """Panes of a split tree, left-to-right / top-to-bottom."""
        if isinstance(widget, TerminalPane):
            return [widget]
        if isinstance(widget, Gtk.Paned):
            return [*PanesMixin.leaves(widget.get_child1()), *PanesMixin.leaves(widget.get_child2())]
        return []

    @staticmethod
    def layout_of(widget: Gtk.Widget, order: list[TerminalPane]):
        if isinstance(widget, Gtk.Paned):
            kind = "horizontal" if widget.get_orientation() == Gtk.Orientation.HORIZONTAL else "vertical"
            node = [kind, PanesMixin.layout_of(widget.get_child1(), order),
                    PanesMixin.layout_of(widget.get_child2(), order)]
            allocation = widget.get_allocation()
            size = allocation.width if kind == "horizontal" else allocation.height
            pending = getattr(widget, "pending_ratio", None)
            if pending is not None:
                node.append(pending)
            elif size > 1:
                ratio = widget.get_position() / size
                node.append(round(min(0.95, max(0.05, ratio)), 3))
            return node
        return order.index(widget)

    def close_active_pane(self, force: bool = False) -> bool:
        viewer = self.active_viewer()
        if viewer is not None:
            self.close_viewer(viewer)
            return True
        pane = self.get_active_terminal()
        frame = self.active_frame()
        if pane is None or frame is None:
            return False
        if not force and pane.has_active_process() and not self.confirm_close("Há um processo ativo nesta aba."):
            return False
        panes = self.page_panes.get(frame, [])
        if len(panes) == 1:
            return self.close_page(frame, force=force)
        pane.prepare_close()
        split = pane.get_parent()
        sibling = split.get_child2() if split.get_child1() is pane else split.get_child1()
        holder = split.get_parent()
        first_slot = isinstance(holder, Gtk.Paned) and holder.get_child1() is split
        split.remove(pane)
        split.remove(sibling)
        if isinstance(holder, Gtk.Paned):
            holder.remove(split)
            if first_slot:
                holder.pack1(sibling, resize=True, shrink=True)
            else:
                holder.pack2(sibling, resize=True, shrink=True)
        else:
            frame.remove(split)
            frame.add(sibling)
        split.destroy()
        self.tab_labels.pop(pane, None)
        pane.destroy()
        panes.remove(pane)
        survivor = self.leaves(sibling)[0]
        self.active_panes[frame] = survivor
        self.update_broadcast(frame)
        frame.show_all()
        self.update_pane_highlight(frame)
        survivor.terminal.grab_focus()
        self.update_status()
        return True

    def close_page(self, frame: Gtk.Frame | None = None, force: bool = False) -> bool:
        frame = frame or self.active_frame()
        if frame is None:
            return False
        panes = self.page_panes.get(frame, [])
        active = [pane for pane in panes if pane.has_active_process()]
        if not force and active and not self.confirm_close("Há processos ativos nesta aba."):
            return False
        for pane in panes:
            pane.prepare_close()
            self.tab_labels.pop(pane, None)
        page = self.notebook.page_num(frame)
        if page >= 0:
            self.notebook.remove_page(page)
        self.page_panes.pop(frame, None)
        self.active_panes.pop(frame, None)
        self.broadcast_frames.discard(frame)
        frame.destroy()
        for viewer, origin in list(self.viewers.items()):
            if origin in panes:
                self.viewers[viewer] = None  # its terminal is gone
        self.update_status()
        if not self.page_panes:
            # Viewers alone do not keep the window open.
            for viewer in list(self.viewers):
                self.close_viewer(viewer)
            self.session_store.clear()
            self.closing_window = True
            self.close()
        return True
