import math

from PySide6.QtGui import QPainter, QColor, QFontMetrics, QFont

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

    def __init__(self, parent, manager, length, height, scale):
        """Create the scale bar.

            Params:
                parent (QWidget): the parent of the scale bar
                manager (QMainWindow): the manager of the scale bar
                length (int): the max pixel length of the scale bar
                height (int): the max pixel height of the scale bar
                scale (float): the number of real-world units per pixel
                ticks (bool): True if ticks should be shown on the scale bar
        """
        super().__init__(parent, manager, "sb")
        self.scale = scale
        self.resize(length, height)

    def setScale(self, scale):
        self.scale = scale
        self.update()

    def paintEvent(self, event):
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


