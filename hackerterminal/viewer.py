"""Image and spreadsheet viewer tab, loaded on first use only."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from .documents import DocumentError, Sheet, column_name, kind_of, load_spreadsheet  # noqa: E402
from .runtime import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

LOGGER = logging.getLogger(__name__)
MAX_DECODE_SIDE = 4096       # huge photos are decoded downscaled
MAX_RENDER_SIDE = 12_000     # cap for zoomed pixbufs
ROWS_PER_IDLE = 400          # table rows inserted per main-loop turn
ZOOM_STEPS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def toolbar_button(icon: str, tooltip: str, callback: Callable[[], None]) -> Gtk.Button:
    button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_tooltip_text(tooltip)
    button.set_focus_on_click(False)
    button.get_style_context().add_class("viewer-button")
    button.connect("clicked", lambda *_: callback())
    return button


class FileViewer(Gtk.Box):
    """Shows one image or spreadsheet; reloads on demand."""

    def __init__(self, path: Path, on_close: Callable[["FileViewer"], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.path = path
        self.kind = kind_of(path) or "unknown"
        self.on_close = on_close
        self.alive = True
        self.generation = 0
        self.zoom = 1.0
        self.fit = True
        self.source: GdkPixbuf.Pixbuf | None = None
        self.animation: GdkPixbuf.PixbufAnimation | None = None
        self.image_info = ""
        self.fill_sources: list[int] = []
        self.tables: list[Gtk.TreeView] = []
        self.get_style_context().add_class("viewer")
        self.connect("destroy", self.on_destroy)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.get_style_context().add_class("viewer-bar")
        icon = "image-x-generic-symbolic" if self.kind == "image" else "x-office-spreadsheet-symbolic"
        bar.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 2)
        title = Gtk.Label(label=path.name, xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title.set_tooltip_text(str(path))
        title.get_style_context().add_class("viewer-title")
        bar.pack_start(title, False, True, 0)
        self.info = Gtk.Label(xalign=0)
        self.info.set_ellipsize(Pango.EllipsizeMode.END)
        self.info.get_style_context().add_class("viewer-info")
        bar.pack_start(self.info, True, True, 6)
        if self.kind == "image":
            for icon_name, tooltip, callback in (
                ("zoom-out-symbolic", "Diminuir zoom (-)", lambda: self.step_zoom(-1)),
                ("zoom-fit-best-symbolic", "Ajustar à janela (F)", self.zoom_fit),
                ("zoom-original-symbolic", "Tamanho real (0)", lambda: self.set_zoom(1.0)),
                ("zoom-in-symbolic", "Aumentar zoom (+)", lambda: self.step_zoom(1)),
            ):
                bar.pack_start(toolbar_button(icon_name, tooltip, callback), False, False, 0)
        else:
            bar.pack_start(toolbar_button("edit-copy-symbolic", "Copiar linhas selecionadas (Ctrl+C)", self.copy), False, False, 0)
        bar.pack_start(toolbar_button("view-refresh-symbolic", "Recarregar", self.load), False, False, 0)
        bar.pack_start(toolbar_button("document-open-symbolic", "Abrir com o aplicativo padrão", self.open_external), False, False, 0)
        bar.pack_start(toolbar_button("window-close-symbolic", "Fechar visualização (Esc)", lambda: self.on_close(self)), False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        spinner = Gtk.Spinner()
        spinner.start()
        self.stack.add_named(spinner, "loading")
        self.error = Gtk.Label()
        self.error.set_line_wrap(True)
        self.error.get_style_context().add_class("viewer-info")
        self.stack.add_named(self.error, "error")
        self.pack_start(self.stack, True, True, 0)

        self.add_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.set_can_focus(True)
        self.connect("key-press-event", self.on_key_press)
        self.load()

    # ------------------------------------------------------------- loading

    def load(self) -> None:
        self.generation += 1
        generation = self.generation
        self._cancel_fill()
        self.stack.set_visible_child_name("loading")
        self.info.set_text("carregando…")
        threading.Thread(target=self._load_worker, args=(generation,), name="viewer-load", daemon=True).start()

    def _load_worker(self, generation: int) -> None:
        try:
            if self.kind == "image":
                result = self._read_image()
            elif self.kind == "spreadsheet":
                result = load_spreadsheet(self.path)
            else:
                raise DocumentError("tipo de arquivo não suportado pelo visualizador")
            error = None
        except (DocumentError, GLib.Error, OSError) as failure:
            result, error = None, getattr(failure, "message", None) or str(failure)
        except Exception as failure:  # noqa: BLE001 - corrupt files must not crash the UI
            LOGGER.exception("falha ao ler %s", self.path)
            result, error = None, f"não foi possível ler o arquivo ({failure.__class__.__name__})"
        GLib.idle_add(self._loaded, generation, result, error)

    def _read_image(self):
        info = GdkPixbuf.Pixbuf.get_file_info(str(self.path))
        if info is None or info[0] is None:
            raise DocumentError("formato de imagem não reconhecido")
        _format, width, height = info
        animation = GdkPixbuf.PixbufAnimation.new_from_file(str(self.path))
        if not animation.is_static_image():
            return ("animation", animation, width, height)
        if max(width, height) > MAX_DECODE_SIDE:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(self.path), MAX_DECODE_SIDE, MAX_DECODE_SIDE, True)
        else:
            pixbuf = animation.get_static_image()
        # Respect the camera's orientation tag.
        return ("still", pixbuf.apply_embedded_orientation() or pixbuf, width, height)

    def _loaded(self, generation: int, result, error: str | None) -> bool:
        if not self.alive or generation != self.generation:
            return False
        if error is not None:
            self.error.set_text(f"Não foi possível mostrar {self.path.name}\n\n{error}")
            self.stack.set_visible_child_name("error")
            self.info.set_text("")
            return False
        try:
            size = human_size(self.path.stat().st_size)
        except OSError:
            size = ""
        if self.kind == "image":
            self._show_image(result, size)
        else:
            self._show_sheets(result, size)
        return False

    # --------------------------------------------------------------- image

    def _show_image(self, result, size: str) -> None:
        mode, data, width, height = result
        old = self.stack.get_child_by_name("image")
        if old is not None:
            old.destroy()
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.get_style_context().add_class("viewer-canvas")
        self.picture = Gtk.Image()
        self.scroller.add(self.picture)
        self.scroller.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.scroller.connect("scroll-event", self.on_image_scroll)
        self.scroller.connect("size-allocate", self.on_canvas_resized)
        self.stack.add_named(self.scroller, "image")
        self.scroller.show_all()
        self.stack.set_visible_child_name("image")
        self.image_info = f"{width} × {height} px · {size}"
        if mode == "animation":
            self.animation, self.source = data, None
            self.picture.set_from_animation(data)
            self.info.set_text(self.image_info + " · animação")
        else:
            self.animation, self.source = None, data
            self.fit = True
            self.info.set_text(self.image_info)
            GLib.idle_add(self.render)

    def on_canvas_resized(self, _widget, _allocation) -> None:
        if self.fit and self.source is not None:
            GLib.idle_add(self.render)

    def fit_scale(self) -> float:
        if self.source is None:
            return 1.0
        allocation = self.scroller.get_allocation()
        width = max(1, allocation.width - 4)
        height = max(1, allocation.height - 4)
        return min(1.0, width / self.source.get_width(), height / self.source.get_height())

    def render(self) -> bool:
        if not self.alive or self.source is None:
            return False
        scale = self.fit_scale() if self.fit else self.zoom
        largest = max(self.source.get_width(), self.source.get_height())
        scale = min(scale, MAX_RENDER_SIDE / largest)
        self.zoom = scale
        width = max(1, round(self.source.get_width() * scale))
        height = max(1, round(self.source.get_height() * scale))
        if (width, height) == (self.source.get_width(), self.source.get_height()):
            scaled = self.source
        else:
            interpolation = GdkPixbuf.InterpType.BILINEAR if scale < 1 else GdkPixbuf.InterpType.NEAREST
            scaled = self.source.scale_simple(width, height, interpolation)
        current = self.picture.get_pixbuf()
        if current is None or (current.get_width(), current.get_height()) != (width, height):
            self.picture.set_from_pixbuf(scaled)
        mode = "ajustado" if self.fit else "zoom"
        self.info.set_text(f"{self.image_info} · {mode} {scale * 100:.0f}%")
        return False

    def set_zoom(self, value: float) -> None:
        if self.source is None:
            return
        self.fit = False
        self.zoom = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], value))
        self.render()

    def step_zoom(self, direction: int) -> None:
        if self.source is None:
            return
        current = self.zoom
        if direction > 0:
            target = next((step for step in ZOOM_STEPS if step > current + 1e-6), ZOOM_STEPS[-1])
        else:
            target = next((step for step in reversed(ZOOM_STEPS) if step < current - 1e-6), ZOOM_STEPS[0])
        self.set_zoom(target)

    def zoom_fit(self) -> None:
        self.fit = True
        self.render()

    def on_image_scroll(self, _widget, event) -> bool:
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        delta = -1 if event.direction == Gdk.ScrollDirection.UP else 1 if event.direction == Gdk.ScrollDirection.DOWN else 0
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            delta = event.get_scroll_deltas()[2]
        if delta:
            self.step_zoom(1 if delta < 0 else -1)
        return True

    # --------------------------------------------------------- spreadsheet

    def _show_sheets(self, sheets: list[Sheet], size: str) -> None:
        old = self.stack.get_child_by_name("table")
        if old is not None:
            old.destroy()
        self.tables = []
        self.sheets = sheets
        if len(sheets) == 1:
            container: Gtk.Widget = self._sheet_view(sheets[0])
        else:
            container = Gtk.Notebook()
            container.set_tab_pos(Gtk.PositionType.BOTTOM)
            container.set_scrollable(True)
            container.get_style_context().add_class("viewer-sheets")
            for sheet in sheets:
                container.append_page(self._sheet_view(sheet), Gtk.Label(label=sheet.name))
            container.connect("switch-page", lambda _nb, _page, index: self._describe(index, size))
        self.stack.add_named(container, "table")
        container.show_all()
        self.stack.set_visible_child_name("table")
        self._describe(0, size)

    def _describe(self, index: int, size: str = "") -> None:
        if not getattr(self, "sheets", None):
            return
        self.size_text = size or getattr(self, "size_text", "")
        sheet = self.sheets[index]
        rows_text = f"{sheet.total_rows:,}".replace(",", ".")
        if sheet.total_prefix == ">":
            rows_text = f"mais de {len(sheet.rows):,}".replace(",", ".")
        elif sheet.total_prefix:
            rows_text = sheet.total_prefix + rows_text
        parts = [f"{rows_text} linhas × {sheet.total_columns} colunas"]
        if len(self.sheets) > 1:
            parts.insert(0, f"{len(self.sheets)} planilhas")
        if sheet.truncated:
            parts.append(f"mostrando {len(sheet.rows)} × {sheet.width}")
        if self.size_text:
            parts.append(self.size_text)
        self.info.set_text(" · ".join(parts))

    def _sheet_view(self, sheet: Sheet) -> Gtk.Widget:
        width = sheet.width
        scroller = Gtk.ScrolledWindow()
        scroller.get_style_context().add_class("viewer-canvas")
        if not sheet.rows:
            empty = Gtk.Label(label="Planilha vazia")
            empty.get_style_context().add_class("viewer-info")
            scroller.add(empty)
            return scroller
        store = Gtk.ListStore(*([str] * (width + 1)))
        view = Gtk.TreeView(model=store)
        view.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
        view.set_enable_search(False)
        view.set_fixed_height_mode(True)
        view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        view.get_style_context().add_class("viewer-table")
        view.connect("key-press-event", self.on_key_press)
        sample = sheet.rows[:200]
        for column in range(width + 1):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            title = "" if column == 0 else column_name(column - 1)
            tree_column = Gtk.TreeViewColumn(title, renderer, text=column)
            tree_column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            tree_column.set_resizable(True)
            if column == 0:
                tree_column.set_fixed_width(max(36, 9 * len(str(len(sheet.rows))) + 16))
                renderer.set_property("xalign", 1.0)
                renderer.set_property("family", "monospace")
                renderer.set_property("foreground-rgba", self.muted_color())
            else:
                longest = max((len(row[column - 1]) for row in sample if len(row) >= column), default=0)
                tree_column.set_fixed_width(max(60, min(320, 8 * max(longest, len(title)) + 18)))
            view.append_column(tree_column)
        self.tables.append(view)
        scroller.add(view)
        rows = iter(enumerate(sheet.rows, start=1))
        holder: list[int] = []

        def fill() -> bool:
            if not self.alive:
                return False
            for _ in range(ROWS_PER_IDLE):
                try:
                    number, row = next(rows)
                except StopIteration:
                    if holder and holder[0] in self.fill_sources:
                        self.fill_sources.remove(holder[0])
                    return False
                cells = [cell.replace("\n", " ⏎ ") for cell in row] + [""] * (width - len(row))
                store.append([str(number), *cells])
            return True

        if fill():  # first screenful immediately, the rest while idle
            holder.append(GLib.idle_add(fill))
            self.fill_sources.append(holder[0])
        return scroller

    def muted_color(self) -> Gdk.RGBA:
        color = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        color.alpha = 0.55
        return color

    def _cancel_fill(self) -> None:
        # Only sources still running are tracked, so removing them is safe.
        for source in self.fill_sources:
            GLib.source_remove(source)
        self.fill_sources = []

    def copy(self) -> None:
        """Copy the selected rows (or everything shown) as tab-separated text."""
        view = next((table for table in self.tables if table.get_mapped()), None)
        if view is None:
            return
        model, paths = view.get_selection().get_selected_rows()
        if not paths:
            paths = [Gtk.TreePath.new_from_indices([index]) for index in range(len(model))]
        lines = []
        for path in paths:
            row = model[path]
            values = [row[index] for index in range(1, model.get_n_columns())]
            while values and not values[-1]:
                values.pop()
            lines.append("\t".join(values))
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("\n".join(lines), -1)
        self.info.set_text(f"{len(lines)} linha(s) copiada(s)")

    # ---------------------------------------------------------------- misc

    def open_external(self) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(self.path.as_uri(), None)
        except GLib.Error as error:
            self.info.set_text(f"nenhum aplicativo padrão: {error.message}")

    def on_key_press(self, _widget, event) -> bool:
        keyval = event.keyval
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if keyval == Gdk.KEY_Escape:
            self.on_close(self)
            return True
        if self.kind == "image" and not control:
            actions = {
                Gdk.KEY_plus: lambda: self.step_zoom(1), Gdk.KEY_equal: lambda: self.step_zoom(1),
                Gdk.KEY_KP_Add: lambda: self.step_zoom(1), Gdk.KEY_minus: lambda: self.step_zoom(-1),
                Gdk.KEY_KP_Subtract: lambda: self.step_zoom(-1), Gdk.KEY_0: lambda: self.set_zoom(1.0),
                Gdk.KEY_f: self.zoom_fit, Gdk.KEY_F: self.zoom_fit,
            }
            if keyval in actions:
                actions[keyval]()
                return True
        if control and keyval in (Gdk.KEY_c, Gdk.KEY_C) and self.kind == "spreadsheet":
            self.copy()
            return True
        return False

    def on_destroy(self, _widget) -> None:
        self.alive = False
        self._cancel_fill()
        self.source = None
        self.animation = None
