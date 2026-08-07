import math

from PySide6.QtGui import QPainter, QColor, QFontMetrics, QFont

from PyReconstruct.modules.datatypes.default_settings import validPinnedLength
from PyReconstruct.modules.gui.utils import drawOutlinedText

from .buttons import MoveableButton

# The ladder of lengths the scale bar is allowed to be.
#
# The bar is never drawn at the widget's full width: it is cut back to the
# longest "nice" length that still fits, so that the number printed under it is
# a round value a reader can trust on a figure.  Each rung is
# (mantissa, subdivisions) and every rung repeats once per decade, so 2.0 means
# the bar can be 0.2 µm, 2 µm, 20 µm, 200 µm and so on.
#
#   subdivisions   how many segments the tick marks cut that rung into, chosen
#                  per rung so every tick label is round as well: 2 µm in 4 gives
#                  0.5 µm ticks, where the historic fixed 5 would give 0.4 µm.
#                  Where more than one divisor qualifies, the one nearest the
#                  historic 5 wins, so the four rungs that predate this table
#                  (1, 2.5, 5, 10) keep exactly the tick spacing they had.
NICE_LENGTHS = (
    (1.0, 5),    # ticks every 0.2
    (1.5, 3),    # ticks every 0.5
    (2.0, 4),    # ticks every 0.5
    (2.5, 5),    # ticks every 0.5
    (3.0, 6),    # ticks every 0.5
    (4.0, 4),    # ticks every 1
    (5.0, 5),    # ticks every 1
    (6.0, 6),    # ticks every 1
    (7.0, 7),    # ticks every 1
    (8.0, 4),    # ticks every 2
    (9.0, 3),    # ticks every 3
    (10.0, 5),   # ticks every 2
)


def niceLength(max_len, rungs=None):
    """Return the longest ladder rung that fits within max_len.

        Params:
            max_len (float): the largest length, in real-world units, the bar
                             widget has room for
            rungs (tuple): the ladder, as (mantissa, subdivisions) pairs in
                           ascending order; defaults to NICE_LENGTHS, read at
                           call time so a test can swap the module's ladder
        Returns:
            (float, int): the bar's length in real-world units, and the number
                          of segments its ticks divide it into.  (0.0, 0) when
                          there is no room to draw, which is what a zero width
                          or a zero scale means.
    """
    if rungs is None:
        rungs = NICE_LENGTHS
    if not max_len > 0:  # zero width, zero scale, or NaN: nothing to draw
        return 0.0, 0

    decade = 10.0 ** math.floor(math.log10(max_len))
    mantissa = max_len / decade

    # the tolerance is what keeps a length that is exactly a rung on that rung:
    # 0.3 divided by its decade is 2.9999999999999996, and without the slack it
    # would fall back to 2.5 and leave a fifth of the widget empty
    length, subdivs = rungs[0][0] * decade, rungs[0][1]
    for m, s in rungs:
        if m <= mantissa + 1e-9:
            length, subdivs = m * decade, s

    return length, subdivs


# The shortest bar, in screen pixels, that is still worth drawing.
#
# Only the micron-pinned mode needs this.  A bar pinned to a fixed real-world
# length shrinks as the user zooms out, and below roughly this width it is
# narrower than the label printed over it, so the reader gets a caption with no
# measurable rule under it.  40 px is a little wider than "5 µm" set in the
# 12 pt bold Courier the label uses.
MIN_PINNED_PIXELS = 40


def pinnedLength(micron_length, scale, max_pix, min_pix=MIN_PINNED_PIXELS):
    """Return the length a micron-pinned bar should actually draw.

    In micron-pinned mode the user picks a length in real-world units and the
    bar's pixel width follows the zoom, which is the inverse of what
    `niceLength` does.  The whole point of the mode is that the number under the
    bar does not move, so this returns the user's own length untouched wherever
    it can be drawn.

    It cannot always be drawn.  Zoomed far out, `micron_length / scale` falls to
    a handful of pixels; zoomed far in, it runs off the side of the field.  A
    scale bar whose drawn length does not match its printed label is worse than
    useless on a figure, so the pixel width is never clamped on its own: when
    the requested length will not fit the drawable range, the *length itself*
    moves, by whole decades, and the label moves with it.  The mantissa the user
    chose is invariant -- 5 µm becomes 0.5 µm or 50 µm, never 4 µm or 6 µm -- so
    the bar still reads as the number they asked for, and the drawn rule always
    measures exactly what the label says.

    This deliberately does not reuse `NICE_LENGTHS`.  That ladder exists to snap
    a screen-fraction bar down to a round number, which is a different job: it
    would replace the user's chosen length rather than rescale it.

        Params:
            micron_length (float): the length the user pinned the bar to, in
                                   real-world units
            scale (float): real-world units per screen pixel (the current zoom)
            max_pix (int): the widest the bar is allowed to be drawn, in pixels
                           -- the room the field gives it
            min_pix (int): the narrowest bar still worth drawing, in pixels
        Returns:
            (float, int): the bar's length in real-world units, and that length
                          in screen pixels.  (0.0, 0) when there is nothing to
                          draw, matching `niceLength`.
    """
    # validPinnedLength rather than `micron_length > 0`: inf passes the latter
    # and then reaches math.log10(0.0) below.  See that function.
    if not (validPinnedLength(micron_length) and scale > 0 and max_pix > 0):
        return 0.0, 0

    def pixels(exponent):
        return micron_length * 10.0 ** exponent / scale

    # first guess: the decade shift that lands inside the range, read straight
    # off the logarithm.  The epsilons keep a length that sits exactly on a
    # boundary on its own decade rather than one step past it, the same job the
    # tolerance does in niceLength.
    exponent = 0
    if pixels(0) > max_pix:
        exponent = math.floor(math.log10(max_pix * scale / micron_length) + 1e-9)
    elif pixels(0) < min_pix:
        exponent = math.ceil(math.log10(min_pix * scale / micron_length) - 1e-9)

    # then correct it by measurement, because the guess is a float computation
    # and the invariant below is the thing that actually has to hold.  Both
    # loops are bounded: each step multiplies or divides the width by ten.
    steps = 0
    while pixels(exponent) > max_pix and steps < 400:
        exponent -= 1
        steps += 1
    # growing is only allowed while it still fits; on a field too narrow to hold
    # one whole decade there may be no exponent that satisfies both bounds, and
    # fitting wins -- a bar that overruns the field is clipped and lies about its
    # length, a bar that is too short is merely hard to read.
    while pixels(exponent) < min_pix and pixels(exponent + 1) <= max_pix and steps < 400:
        exponent += 1
        steps += 1

    real_len = micron_length * 10.0 ** exponent
    pix_len = int(real_len / scale)
    if pix_len <= 0:
        return 0.0, 0
    return real_len, pix_len


def pinnedSubdivisions(real_len, rungs=None):
    """How finely to tick a micron-pinned bar of this length.

    The screen-fraction bar always lands on a `NICE_LENGTHS` rung, so it always
    has a subdivision count that cuts it into round numbers.  A pinned bar is
    whatever the user typed, so it may not: 3.7 µm has no division into two to
    seven parts that prints roundly.  Rather than print ticks labelled 0.74 and
    1.48, a length that is not a rung gets no interior ticks at all -- 1, which
    `paintEvent`'s `range(1, subdivs)` draws as none.

        Params:
            real_len (float): the bar's length in real-world units
            rungs (tuple): the ladder, as (mantissa, subdivisions) pairs;
                           defaults to NICE_LENGTHS, read at call time
        Returns:
            int: the number of segments to cut the bar into
    """
    if rungs is None:
        rungs = NICE_LENGTHS
    if not real_len > 0:
        return 1

    decade = 10.0 ** math.floor(math.log10(real_len))
    mantissa = real_len / decade
    for m, s in rungs:
        if abs(m - mantissa) < 1e-9:
            return s
    return 1


def formatLength(value):
    """Render a length the way a figure caption would: no trailing zeros.

    The bar's own label and its tick labels both go through here so that one
    length always prints one way.  Before, the label was built with `str()` on
    the arithmetic's result, so the same 10 µm bar printed "10 µm" or "10.0 µm"
    depending on which side of a decade the zoom happened to be on, and every
    tick label carried a trailing ".0".
    """
    if not value > 0:
        return "0"
    text = f"{value:.10g}"
    if "e" in text or "E" in text:  # sub-ångström lengths, in principle
        text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text


class ScaleBar(MoveableButton):

    def __init__(self, parent, manager, length, height, scale,
                 micron_length=None, max_pixel_length=None):
        """Create the scale bar.

            Params:
                parent (QWidget): the parent of the scale bar
                manager (QMainWindow): the manager of the scale bar
                length (int): the max pixel length of the scale bar
                height (int): the max pixel height of the scale bar
                scale (float): the number of real-world units per pixel
                ticks (bool): True if ticks should be shown on the scale bar
                micron_length (float): the real-world length to pin the bar to,
                                       or None (the default) for the historic
                                       screen-fraction sizing, where `length` is
                                       the room the bar may fill and the printed
                                       figure follows the zoom
                max_pixel_length (int): how wide the bar may grow when pinned;
                                        defaults to `length`
        """
        super().__init__(parent, manager, "sb")
        self.scale = scale
        self.micron_length = micron_length
        self.max_pixel_length = length if max_pixel_length is None else max_pixel_length
        self.resize(length, height)
        self._fitPinned()

    def setScale(self, scale):
        self.scale = scale
        self._fitPinned()
        self.update()

    def setMaxPixelLength(self, max_pixel_length):
        """Say how much room the field has for the bar (pinned mode only)."""
        if max_pixel_length == self.max_pixel_length:
            return
        self.max_pixel_length = max_pixel_length
        self._fitPinned()
        self.update()

    def pinnedRender(self):
        """The pinned bar's length and tick count at the current zoom."""
        real_len, pix_len = pinnedLength(
            self.micron_length, self.scale, self.max_pixel_length
        )
        return real_len, pix_len, pinnedSubdivisions(real_len)

    def _fitPinned(self):
        """Resize the widget to the pinned bar, so the paint is never clipped.

        In screen-fraction mode the widget's width is the room the bar may fill
        and never moves.  Pinned, the bar *is* its width -- the widget is also
        the drag handle, so leaving it at full field width would put an
        invisible grab target over the field.  The resize happens here rather
        than in `paintEvent`, which must not change geometry.
        """
        if not self.micron_length:
            return
        _real_len, pix_len, _subdivs = self.pinnedRender()
        if pix_len > 0 and pix_len != self.width():
            self.resize(pix_len, self.height())

    def paintEvent(self, event):
        if self.micron_length:
            # a fixed real-world length: the pixels follow the zoom
            real_len, _pix_len, subdivs = self.pinnedRender()
        else:
            # the longest nice length that fits the widget, and how finely to tick it
            real_len, subdivs = niceLength(self.width() * self.scale)
        if real_len <= 0:
            return
        pix_len = int(real_len / self.scale)

        # check text and tick preferences
        draw_text = self.manager.series.getOption("show_scale_bar_text")
        draw_ticks = self.manager.series.getOption("show_scale_bar_ticks")

        # draw the scale bar
        r_x = 0
        r_y = self.height() / 2
        r_w = pix_len
        r_h = self.height() / 2
        painter = QPainter(self)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRect(r_x, r_y, r_w, r_h)
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(r_x + 1, r_y + 1, r_w - 2, r_h - 2)

        # draw text
        if draw_text:
            font = QFont("Courier New", 12)
            font.setBold(True)
            small_font = QFont("Courier New", 9)  # used for ticks
            l_text = formatLength(real_len) + " µm"
            painter.setFont(font)
            drawCenteredText(
                painter,
                r_x + r_w/2,
                r_y / 2,
                l_text,
                outlined=True
            )

        # draw ticks if requested
        if draw_ticks:
            for i in range(1, subdivs):
                t_x = r_x + r_w/subdivs * i
                painter.drawLine(t_x, r_h, t_x, r_h + 4)
                if draw_text:
                    painter.setFont(small_font)
                    t_text = formatLength(real_len * i/subdivs)
                    drawCenteredText(
                        painter,
                        t_x,
                        r_h + 8,
                        t_text
                    )

        painter.end()

def drawCenteredText(painter, x, y, text, outlined=False):
    font_metrics = QFontMetrics(painter.font())
    text_rect = font_metrics.boundingRect(text)
    adjusted_x = x - text_rect.width() / 2
    adjusted_y = y + text_rect.height() / 2
    if outlined:
        drawOutlinedText(
            painter,
            adjusted_x,
            adjusted_y,
            text
        )
    else:
        painter.drawText(adjusted_x, adjusted_y, text)


