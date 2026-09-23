"""Editor for the autoseg-import color palette (Series > Options > View).

Autoseg import colors each imported trace from a curated whitelist, mapped
deterministically from the label id (see modules/backend/autoseg/palette.py).
The whitelist ships CVD-safe by default, but issue #96 asks that the user be
able to adjust it. This widget backs the ``autoseg_color_palette`` option.

The page, top to bottom: the seed with a Shuffle button; the swatches on a
mid-gray ground (the ground the colors will be judged on), each labeled with
its hex; one color picker embedded in the page, live on the selected swatch;
an "Add colors" field that takes pasted hex or r,g,b tokens; Duplicate,
Remove, Copy, Revert and Reset buttons; and a preview strip of sixteen sample
labels colored the way import will color them, with a status line that says
when a length change has reassigned every label.

The picker is a child widget, not a window (his call, 2026-09-14, after two
design passes). The old page opened a modal color dialog per swatch, so
recoloring twelve colors was twelve open-adjust-OK cycles. Now a click on a
swatch retargets the one picker, every slider move repaints that swatch, and
Esc or Revert puts it back to what it was when it was selected. Nothing is
written until the outer dialog's OK: the page still exposes
``accept(close=False)`` (validate) and ``set()`` (commit), which
AllOptionsDialog calls, and outer Cancel drops every live edit.

Note on determinism: import indexes the palette by ``hash(id) % len(palette)``,
so changing the *number* of colors reshuffles every id -> color assignment (not
just the colors that changed). The status line under the preview says so the
moment the count differs from what was loaded.
"""

import re

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QColorDialog,
    QApplication,
    QAbstractItemView,
)
from PySide6.QtGui import (
    QColor, QPixmap, QIcon, QPainter, QPalette, QKeySequence, QShortcut,
)
from PySide6.QtCore import QSize, Qt, Signal

from .helper import resizeLineEdit
from PyReconstruct.modules.backend.autoseg.palette import (
    DEFAULT_AUTOSEG_PALETTE, palette_color, next_shuffle_seed,
)
from PyReconstruct.modules.gui.utils import notify

# A palette of one color makes every label id the same color and leaves the seed
# and "Shuffle colors" button with nothing to reshuffle (next_shuffle_seed no-ops
# below two colors). Two is the smallest palette for which the whole color
# machinery is still meaningful, so it is the enforced floor. Distinctness beyond
# that (avoiding near-duplicate or hard-to-see colors) is left to the user, per
# the maintainer's intent.
MIN_PALETTE_COLORS = 2

_SWATCH_SIZE = QSize(56, 28)
_GROUND = "#808080"          # the gray the colors are judged on
PREVIEW_IDS = list(range(1, 17))


def normalize_palette(colors):
    """Return the value to persist for ``autoseg_color_palette``.

    Store ``[]`` (meaning "use the shipped default") when the edited list matches
    DEFAULT_AUTOSEG_PALETTE exactly, so a user who never customizes keeps
    tracking the curated default even if it changes in a future release.
    Otherwise store the explicit list of ``[R, G, B]`` integer lists -- the
    format ``palette_color`` and the preview already consume.

        Params:
            colors (list): list of (R, G, B) sequences
        Returns:
            (list): [] when equal to the default, else a list of [R, G, B] lists
    """
    as_tuples = [tuple(int(v) for v in c) for c in colors]
    if as_tuples == [tuple(c) for c in DEFAULT_AUTOSEG_PALETTE]:
        return []
    return [[int(v) for v in c] for c in as_tuples]


def hex_of(rgb) -> str:
    """``#RRGGBB`` for an (R, G, B) triple."""
    return "#{:02X}{:02X}{:02X}".format(*(int(v) for v in rgb))


_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_RGB = re.compile(r"^(\d{1,3}),(\d{1,3}),(\d{1,3})$")


def parse_colors(text: str):
    """Split pasted text into colors.

    Accepts ``#RRGGBB``, ``RRGGBB`` and ``r,g,b`` tokens, separated by
    whitespace, semicolons or newlines. Commas separate the parts of an r,g,b
    token, so they do not separate tokens.

        Params:
            text (str): what the user typed or pasted
        Returns:
            (list, int): the parsed [R, G, B] lists, and how many tokens were
                skipped as unreadable
    """
    colors, skipped = [], 0
    for token in re.split(r"[\s;]+", text.strip()):
        if not token:
            continue
        m = _HEX.match(token)
        if m:
            h = m.group(1)
            colors.append([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])
            continue
        m = _RGB.match(token)
        if m and all(0 <= int(v) <= 255 for v in m.groups()):
            colors.append([int(v) for v in m.groups()])
            continue
        skipped += 1
    return colors, skipped


def _swatch_icon(rgb):
    """Build a filled color-swatch icon for a palette entry."""
    pixmap = QPixmap(_SWATCH_SIZE)
    pixmap.fill(QColor(int(rgb[0]), int(rgb[1]), int(rgb[2])))
    return QIcon(pixmap)


class _EmbeddedColorDialog(QColorDialog):
    """A QColorDialog living inside a page as an ordinary widget.

    NoButtons and DontUseNativeDialog are set before any color (the cocoa
    seed-loss ordering ColorButton.selectColor documents), and the window
    flag is stripped BEFORE the layout takes the widget: QColorDialog(parent)
    already has the page as parent, so addWidget alone would not strip
    Qt.Dialog and a separate window would appear. Esc means "put this swatch
    back", not "hide"; Return is left for the outer dialog's OK; and done()
    is a no-op so nothing can ever hide the widget.
    """

    revert_requested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        self.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setSizeGripEnabled(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.revert_requested.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def done(self, result):
        """Never hide: the picker is part of the page."""
        return

    def reject(self):
        self.revert_requested.emit()


class AutosegColorsWidget(QWidget):

    def __init__(self, parent, series, use_defaults=False):
        """Create the autoseg import-colors editor.

            Params:
                parent (QWidget): the parent widget
                series (Series): the series whose options are edited
                use_defaults (bool): show the shipped defaults instead of the
                    stored values (Reset Defaults in the options dialog)
        """
        super().__init__(parent)
        self.series = series

        stored = series.getOption("autoseg_color_palette", use_defaults) or []
        # An empty option means "use the built-in default"; show that default so
        # the user edits a concrete starting palette rather than a blank list.
        source = stored if stored else DEFAULT_AUTOSEG_PALETTE
        self.colors = [[int(v) for v in c] for c in source]
        self._loaded_len = len(self.colors)

        seed = series.getOption("autoseg_color_seed", use_defaults) or 0
        self._seed = int(seed)

        # live-picker state
        self._editing_row = None     # the swatch the picker is bound to
        self._edit_origin = None     # its color when it was selected
        self._syncing = False        # True while WE set the picker's color
        self._undo = []              # snapshots of self.colors

        vlayout = QVBoxLayout()

        header = QLabel("Autoseg import colors", self)
        f = header.font()
        f.setBold(True)
        header.setFont(f)
        vlayout.addWidget(header)

        desc = QLabel(
            "Imported autoseg traces are colored from this palette, chosen\n"
            "deterministically per label id. The default palette is color-blind\n"
            "safe and readable on grayscale images.",
            self,
        )
        vlayout.addWidget(desc)

        # seed row
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Color seed (same seed gives the same colors):", self))
        self.seed_edit = QLineEdit(str(self._seed), self)
        resizeLineEdit(self.seed_edit, "000000")
        self.seed_edit.textChanged.connect(lambda _: self._refresh_preview())
        seed_row.addWidget(self.seed_edit)
        self.shuffle_btn = QPushButton("Shuffle", self)
        self.shuffle_btn.setToolTip("Pick a seed that changes the arrangement")
        self.shuffle_btn.clicked.connect(self._shuffle)
        seed_row.addWidget(self.shuffle_btn)
        seed_row.addStretch()
        vlayout.addLayout(seed_row)

        # swatch grid on the gray the colors will be seen on; click a swatch to
        # bind the picker below to it
        self.list = QListWidget(self)
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(_SWATCH_SIZE)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMaximumHeight(210)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {_GROUND}; color: white; }}"
            "QListWidget::item:selected { background: rgba(255,255,255,60); }"
        )
        self.list.currentRowChanged.connect(self._on_row_changed)
        vlayout.addWidget(self.list)

        # the picker, part of the page
        self.picker = _EmbeddedColorDialog(self)
        self.picker.currentColorChanged.connect(self._apply_live)
        self.picker.revert_requested.connect(self._revert_current)
        vlayout.addWidget(self.picker)

        # add-colors row: type or paste, as many as you like
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Add colors:", self))
        self.add_edit = QLineEdit(self)
        self.add_edit.setPlaceholderText("#1B9E77 D95F02 27,158,119")
        self.add_edit.returnPressed.connect(self._add_from_text)
        add_row.addWidget(self.add_edit, 1)
        self.add_btn = QPushButton("Add", self)
        self.add_btn.clicked.connect(self._add_from_text_or_copy)
        add_row.addWidget(self.add_btn)
        vlayout.addLayout(add_row)

        # controls
        btn_row = QHBoxLayout()
        self.edit_btn = QPushButton("Duplicate", self)
        self.edit_btn.clicked.connect(self._duplicate_selected)
        self.remove_btn = QPushButton("Remove", self)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.copy_btn = QPushButton("Copy", self)
        self.copy_btn.setToolTip("Copy the palette to the clipboard, one hex color per line")
        self.copy_btn.clicked.connect(self._copy_palette)
        self.revert_btn = QPushButton("Revert", self)
        self.revert_btn.setToolTip("Put the selected swatch back to what it was when you selected it")
        self.revert_btn.clicked.connect(self._revert_current)
        reset_btn = QPushButton("Reset to default", self)
        reset_btn.clicked.connect(self._reset_default)
        for b in (self.edit_btn, self.remove_btn, self.copy_btn, self.revert_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        btn_row.addWidget(reset_btn)
        vlayout.addLayout(btn_row)

        # preview: sixteen sample labels, colored as import will color them
        self.preview = QLabel(self)
        self.preview.setToolTip(
            "Labels 1 to 16 as import will color them with this palette and seed"
        )
        vlayout.addWidget(self.preview)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        vlayout.addWidget(self.status)

        self.setLayout(vlayout)

        # keys, scoped to the swatch grid
        for keys, slot in (
            (QKeySequence(QKeySequence.StandardKey.Delete), self._remove_selected),
            (QKeySequence(Qt.Key.Key_Backspace), self._remove_selected),
            (QKeySequence("Ctrl+D"), self._duplicate_selected),
            (QKeySequence(QKeySequence.StandardKey.Copy), self._copy_selected),
            (QKeySequence(QKeySequence.StandardKey.Undo), self._undo_last),
        ):
            sc = QShortcut(keys, self.list)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self._rebuild()

    # --- the swatch grid -----------------------------------------------------

    def _rebuild(self, select=None):
        """Repopulate the swatch grid from self.colors and rebind the picker."""
        self._editing_row = None
        self.list.clear()
        for rgb in self.colors:
            item = QListWidgetItem(self.list)
            self._paint_item(item, rgb)
        if select is None:
            select = 0 if self.colors else -1
        self.list.setCurrentRow(select)
        self._on_row_changed(self.list.currentRow())
        self._refresh_preview()

    def _paint_item(self, item, rgb):
        item.setIcon(_swatch_icon(rgb))
        item.setText(hex_of(rgb))
        item.setToolTip("rgb({}, {}, {})".format(*rgb))

    def _selected_rows(self):
        return sorted(i.row() for i in self.list.selectedIndexes())

    def _update_buttons(self):
        rows = self._selected_rows()
        self.edit_btn.setEnabled(bool(rows))
        # keep the palette at or above the floor
        self.remove_btn.setEnabled(
            bool(rows) and len(self.colors) - len(rows) >= MIN_PALETTE_COLORS
        )
        changed = (
            self._editing_row is not None
            and self._edit_origin is not None
            and self.colors[self._editing_row] != self._edit_origin
        )
        self.revert_btn.setEnabled(changed)

    # --- the live picker -----------------------------------------------------

    def _on_row_changed(self, row):
        if row is None or row < 0 or row >= len(self.colors):
            self._editing_row = None
            self._edit_origin = None
            self.picker.setEnabled(False)
        else:
            self._target(row)
        self._update_buttons()

    def _target(self, row):
        """Bind the picker to swatch `row` without writing anything."""
        self._editing_row = row
        self._edit_origin = list(self.colors[row])
        self.picker.setEnabled(True)
        self._set_picker(self.colors[row])

    def _set_picker(self, rgb):
        # a programmatic setCurrentColor emits currentColorChanged; the guard
        # keeps _apply_live from writing it into the (old or new) swatch
        self._syncing = True
        try:
            self.picker.setCurrentColor(QColor(*rgb))
        finally:
            self._syncing = False

    def _apply_live(self, color):
        """Every picker change lands on the bound swatch, and only there."""
        row = self._editing_row
        if self._syncing or row is None or not color.isValid():
            return
        rgb = [color.red(), color.green(), color.blue()]
        if rgb == self.colors[row]:
            return
        if self.colors[row] == self._edit_origin:
            self._snapshot()          # first change to this swatch: one undo step
        self.colors[row] = rgb
        item = self.list.item(row)
        if item is not None:
            self._paint_item(item, rgb)   # never _rebuild mid-drag
        self._refresh_preview()
        self._update_buttons()

    def _revert_current(self):
        row = self._editing_row
        if row is None or self._edit_origin is None:
            return
        self.colors[row] = list(self._edit_origin)
        item = self.list.item(row)
        if item is not None:
            self._paint_item(item, self.colors[row])
        self._set_picker(self.colors[row])
        self._refresh_preview()
        self._update_buttons()

    # --- editing -------------------------------------------------------------

    def _snapshot(self):
        self._undo.append([list(c) for c in self.colors])
        del self._undo[:-50]

    def _undo_last(self):
        if not self._undo:
            return
        self.colors = self._undo.pop()
        self._rebuild(select=min(max(self.list.currentRow(), 0), len(self.colors) - 1))

    def _add_colors(self, new_colors):
        if not new_colors:
            return
        self._snapshot()
        self.colors.extend([list(c) for c in new_colors])
        self._rebuild(select=len(self.colors) - 1)

    def _add_from_text(self):
        """Parse the Add colors field; report what was added and skipped."""
        colors, skipped = parse_colors(self.add_edit.text())
        self._add_colors(colors)
        if colors or skipped:
            self.add_edit.clear()
            note = f"Added {len(colors)}"
            if skipped:
                note += f", skipped {skipped} unreadable"
            self._refresh_preview(note)

    def _add_from_text_or_copy(self):
        if self.add_edit.text().strip():
            self._add_from_text()
        else:
            self._add_color()

    def _add_color(self):
        """Add one swatch: a copy of the selected color, or white."""
        row = self.list.currentRow()
        base = self.colors[row] if 0 <= row < len(self.colors) else [255, 255, 255]
        self._add_colors([base])

    def _duplicate_selected(self, *args):
        rows = self._selected_rows()
        if rows:
            self._add_colors([self.colors[r] for r in rows])

    def _edit_selected(self, *args):
        """Kept for callers of the old API: focus the picker on the selection."""
        if self.list.currentRow() >= 0:
            self.picker.setFocus()

    def _remove_selected(self):
        rows = self._selected_rows()
        if not rows:
            return
        if len(self.colors) - len(rows) < MIN_PALETTE_COLORS:
            notify(f"The palette must keep at least {MIN_PALETTE_COLORS} colors.")
            return
        self._snapshot()
        for r in reversed(rows):
            del self.colors[r]
        self._rebuild(select=min(rows[0], len(self.colors) - 1))

    def _reset_default(self):
        self._snapshot()
        self.colors = [[int(v) for v in c] for c in DEFAULT_AUTOSEG_PALETTE]
        self._rebuild()

    def _copy_palette(self):
        QApplication.clipboard().setText("\n".join(hex_of(c) for c in self.colors))
        self._refresh_preview(f"Copied {len(self.colors)} colors")

    def _copy_selected(self):
        rows = self._selected_rows() or list(range(len(self.colors)))
        QApplication.clipboard().setText("\n".join(hex_of(self.colors[r]) for r in rows))
        self._refresh_preview(f"Copied {len(rows)} colors")

    def _current_seed(self):
        text = self.seed_edit.text().strip()
        try:
            return int(text) if text else 0
        except ValueError:
            return None

    def _shuffle(self):
        seed = self._current_seed()
        if seed is None:
            notify("Please enter a whole number for the color seed.")
            return
        self.seed_edit.setText(str(next_shuffle_seed(seed, self.colors, PREVIEW_IDS)))

    # --- preview and status --------------------------------------------------

    def _preview_colors(self):
        seed = self._current_seed() or 0
        return [palette_color(i, self.colors, seed) for i in PREVIEW_IDS]

    def _refresh_preview(self, note=None):
        chip, gap, h = 30, 6, 26
        pixmap = QPixmap(len(PREVIEW_IDS) * (chip + gap) + gap, h + 2 * gap)
        pixmap.fill(QColor(_GROUND))
        painter = QPainter(pixmap)
        painter.setPen(Qt.PenStyle.NoPen)
        for i, rgb in enumerate(self._preview_colors()):
            painter.setBrush(QColor(*rgb))
            painter.drawRect(gap + i * (chip + gap), gap, chip, h)
        painter.end()
        self.preview.setPixmap(pixmap)

        n = len(self.colors)
        parts = [f"{n} colors" + (" (default)" if not normalize_palette(self.colors) else "")]
        if n != self._loaded_len:
            parts.append(
                f"Palette length changed {self._loaded_len} to {n}: every label "
                "gets a new color on future imports. Existing objects keep theirs; "
                "use Recolor all objects from palette to update them."
            )
        if note:
            parts.insert(0, note + ".")
        self.status.setText(" ".join(parts))

    # --- options-dialog protocol (accept -> set) -----------------------------

    def accept(self, close=True):
        """Validate the inputs. Called by AllOptionsDialog before set()."""
        text = self.seed_edit.text().strip()
        if not text:
            self._seed = 0
        else:
            try:
                self._seed = int(text)
            except ValueError:
                notify("Please enter a whole number for the color seed.")
                return False
        if len(self.colors) < MIN_PALETTE_COLORS:
            notify(f"The palette must keep at least {MIN_PALETTE_COLORS} colors.")
            return False
        return True

    def set(self):
        """Commit the seed and palette to the series options."""
        self.series.setOption("autoseg_color_seed", self._seed)
        self.series.setOption("autoseg_color_palette", normalize_palette(self.colors))

    # --- cosmetic border, matching the sibling OptionWidgets -----------------

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QApplication.palette().color(QPalette.WindowText))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
