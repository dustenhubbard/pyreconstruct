"""Every scale bar option, built once for two places.

Series > Options > View has a Scale Bar group, and the bar's right-click menu
opens "Scale bar settings...". Both are built here, from the same structure,
the same reader, the same writer and the same wiring, so the two cannot drift
apart.

The response tuple keeps the layout the options page has always had, which
other tests index by number (see test_scale_bar_mode_toggle.py):

    0  show numbers / show ticks   (check pairs)
    1  the sizing mode             (radio pairs)
    2  size, percent of the field  (int)
    3  fixed length in µm          (float, or None when blank)
    4  thickness in pixels         (int)

The size slider stays enabled in both modes. In fixed-length mode it is the
widest the bar may grow before its length steps down a decade (see
scale_bar.pinnedLength), so it still does something; its label says which.
The length field does nothing in share-of-field mode, so it is disabled there.
"""
from PySide6.QtWidgets import QDialog, QLabel

from .quick_dialog import QuickDialog
from PyReconstruct.modules.constants.settings_domain import user_action
from PyReconstruct.modules.datatypes.default_settings import (
    MAX_SCALE_BAR_THICKNESS,
    MIN_SCALE_BAR_THICKNESS,
    clampScaleBarThickness,
    validPinnedLength,
)

TITLE = "Scale Bar Settings"

SHARE_LABEL = "Share of the field width (the µm figure changes as you zoom)"
FIXED_LABEL = "Fixed length in µm (the bar's width changes as you zoom)"
SIZE_LABEL_SHARE = "Size (percent of field width):"
SIZE_LABEL_FIXED = "Largest size (percent of field width):"
LENGTH_LABEL = "Fixed length (µm):"
LENGTH_NOTE = "If it does not fit, the bar steps by tens, so 5 µm becomes 0.5 or 50 µm."
LENGTH_TIP = (
    "Zoomed far enough out or in that this length will not fit the size above, "
    "the bar steps by whole decades and its label follows, so it always "
    "measures what it says."
)
THICKNESS_LABEL = "Thickness (pixels):"

KEYS = (
    "show_scale_bar_text",
    "show_scale_bar_ticks",
    "scale_bar_mode",
    "scale_bar_width",
    "scale_bar_length_um",
    "scale_bar_thickness",
)


def scaleBarStructure(series, use_defaults=False):
    """The QuickDialog structure for every scale bar option, filled from
    `series` (or from the defaults)."""
    def get(key):
        return series.getOption(key, use_defaults)

    pinned = get("scale_bar_mode") == "micron_pinned"
    return [
        [("check",
          ("show numbers", get("show_scale_bar_text")),
          ("show ticks", get("show_scale_bar_ticks")),
        )],
        [],
        ["Sizing:"],
        [("radio", (SHARE_LABEL, not pinned), (FIXED_LABEL, pinned))],
        [SIZE_LABEL_FIXED if pinned else SIZE_LABEL_SHARE],
        # scale_bar_width is a percentage of the field width and runs 20-100
        # (see MousePalette.sbWidth). The slider carries that range itself,
        # so the number on screen is the number stored.
        [("slider", get("scale_bar_width"),
          {"minimum": 20, "maximum": 100, "suffix": "%"})],
        [LENGTH_LABEL, ("float", get("scale_bar_length_um")), None],
        [LENGTH_NOTE],
        [],
        [THICKNESS_LABEL],
        [("slider", clampScaleBarThickness(get("scale_bar_thickness")),
          {"minimum": MIN_SCALE_BAR_THICKNESS,
           "maximum": MAX_SCALE_BAR_THICKNESS,
           "suffix": " px"})],
    ]


def storeScaleBarResponse(series, response):
    """Store an accepted response (the tuple described at the top)."""
    series.setOption("show_scale_bar_text", response[0][0][1])
    series.setOption("show_scale_bar_ticks", response[0][1][1])
    series.setOption(
        "scale_bar_mode",
        "micron_pinned" if response[1][1][1] else "screen_fraction",
    )
    series.setOption("scale_bar_width", response[2])
    # an empty or nonsensical box keeps the stored length rather than pinning
    # the bar to nothing. "Nonsensical" has to mean more than `<= 0`: `inf > 0`
    # is True and `1e400` parses to inf, and this key is global, so storing one
    # would crash the palette on every launch from here on. validPinnedLength
    # is the predicate the palette and the bar itself apply to the same value.
    if validPinnedLength(response[3]):
        series.setOption("scale_bar_length_um", float(response[3]))
    series.setOption("scale_bar_thickness", response[4])


def _controls(page):
    """The page's input widgets, in response order."""
    checks, radios, size, length, thickness = (f.widget for f in page.inputs)
    return checks, radios, size, length, thickness


def _buttons(group):
    layout = group.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def readScaleBarSettings(page, series):
    """What the page shows now, as {option: value}, with no warnings.

    For the live preview, so it reads as the user types: a length that is
    blank or not yet a number falls back to the stored one rather than
    popping up a warning or flicking the bar to the other mode.
    """
    checks, radios, size, length, thickness = _controls(page)
    text, ticks = (b.isChecked() for b in _buttons(checks))
    pinned = _buttons(radios)[1].isChecked()
    try:
        micron_length = float(length.text())
    except ValueError:
        micron_length = None
    if not validPinnedLength(micron_length):
        micron_length = series.getOption("scale_bar_length_um")
    return {
        "show_scale_bar_text": text,
        "show_scale_bar_ticks": ticks,
        "scale_bar_mode": "micron_pinned" if pinned else "screen_fraction",
        "scale_bar_width": size.value(),
        "scale_bar_length_um": micron_length,
        "scale_bar_thickness": thickness.value(),
    }


def _label(page, text):
    for label in page.findChildren(QLabel):
        if label.text() == text:
            return label
    return None


def wireScaleBarControls(page, series, preview=None):
    """Make the page react: the length row is enabled only in fixed-length
    mode, the size label says what the slider does in the chosen mode, and
    `preview(settings)` is called with readScaleBarSettings on every change.

    Returns the function that applies the mode, for the tests.
    """
    checks, radios, size, length, thickness = _controls(page)
    size_label = (_label(page, SIZE_LABEL_SHARE)
                  or _label(page, SIZE_LABEL_FIXED))
    length_label = _label(page, LENGTH_LABEL)
    note = _label(page, LENGTH_NOTE)
    note.setWordWrap(True)
    length.setToolTip(LENGTH_TIP)
    note.setToolTip(LENGTH_TIP)

    def applyMode():
        pinned = _buttons(radios)[1].isChecked()
        size_label.setText(SIZE_LABEL_FIXED if pinned else SIZE_LABEL_SHARE)
        for widget in (length_label, length, note):
            widget.setEnabled(pinned)

    def changed(*_args):
        applyMode()
        if preview is not None:
            preview(readScaleBarSettings(page, series))

    for button in _buttons(checks) + _buttons(radios):
        button.toggled.connect(changed)
    size.slider.valueChanged.connect(changed)
    thickness.slider.valueChanged.connect(changed)
    length.textEdited.connect(changed)
    applyMode()
    return applyMode


class ScaleBarSettingsDialog(QuickDialog):
    """The scale bar's right-click "Scale bar settings..." dialog.

    The same page as the Options group, previewed on the bar as it changes.
    OK stores every option and Cancel puts the bar back; either way the bar
    is changed in place, so its position, visibility and right-click menu are
    untouched.
    """

    def __init__(self, parent, series, palette=None):
        super().__init__(parent, scaleBarStructure(series), TITLE)
        self.series = series
        self.palette = palette
        self.previewed = False
        wireScaleBarControls(self, series, self._preview)

    def _preview(self, settings):
        if self.palette is not None:
            self.palette.previewScaleBar(settings)
            self.previewed = True

    def accept(self, close=True):
        if not super().accept(close=False):
            return False
        # the choices the user accepted, saved even while the old KHLab
        # settings are still being copied
        with user_action():
            storeScaleBarResponse(self.series, self.responses)
        if self.palette is not None:
            self.palette.restoreScaleBar()
        self.previewed = False
        if close:
            QDialog.accept(self)
        return True

    def reject(self):
        if self.previewed and self.palette is not None:
            self.palette.restoreScaleBar()
        self.previewed = False
        super().reject()
