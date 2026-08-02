"""A malformed ``*_columns`` option is rejected where it is read, by name.

The bug: ``getOption`` carried a ``if "_columns" in option_name`` type check,
but it sat after the settings-store branch and every one of the five
``*_columns`` options lives in the series-internal ``options`` dict, which
returns several lines earlier. Nothing reached the check, so a malformed value
round-tripped through the .jser and failed inside the table widgets instead, at
``dict(self.columns)`` or ``self.columns.append(...)``, with messages that named
neither the option nor the file:

    ValueError: dictionary update sequence element #0 has length 1; 2 is required
    AttributeError: 'dict' object has no attribute 'append'
    TypeError: 'NoneType' object is not iterable

The type check would also have passed a flat ``["Thickness", "Locked"]``, which
is a list and still crashes ``dict(...)``, so the replacement checks the shape.

No Qt required: the internal-options path in ``getOption`` touches neither the
settings store nor any PySide6 symbol.
"""
import pytest

from PyReconstruct.modules.datatypes.series import Series, SeriesOptionError

COLUMN_OPTIONS = [
    "object_columns",
    "trace_columns",
    "flag_columns",
    "section_columns",
    "ztrace_columns",
]


def _series(**options):
    """A Series carrying `options` and nothing else.

    Built with ``__new__`` so no file is opened and no settings store is
    consulted: the internal-options branch of ``getOption`` reads
    ``self.options`` and returns.
    """
    s = Series.__new__(Series)
    s.options = dict(options)
    return s


# ---------------------------------------------------------------------------
# the check is reachable at all
# ---------------------------------------------------------------------------

def test_every_columns_option_is_internal():
    """The five column options all live in the branch that returned early.

    This is the reason the old check was dead code, so it is pinned: if one of
    them ever moves to the settings store, the settings-store copy of the check
    is what covers it, and this test is where that shows up.
    """
    options = Series.getEmptyDict()["options"]
    assert [k for k in options if "_columns" in k] == COLUMN_OPTIONS


@pytest.mark.parametrize("option_name", COLUMN_OPTIONS)
def test_malformed_value_is_rejected(option_name):
    series = _series(**{option_name: "Thickness"})
    with pytest.raises(SeriesOptionError):
        series.getOption(option_name)


# ---------------------------------------------------------------------------
# the message is actionable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad, problem",
    [
        ("Thickness", "is a str, not a list"),
        ({"Thickness": True}, "is a dict, not a list"),
        (None, "is a NoneType, not a list"),
        (5, "is a int, not a list"),
        (["Thickness", "Locked"], "entry 0 is not a [column name, shown] pair"),
        ([("Thickness", True), ("Locked",)], "entry 1 is not a [column name, shown] pair"),
        ([(3, True)], "entry 0 has a int where the column name should be"),
    ],
)
def test_message_names_option_value_and_shape(bad, problem):
    """Each rejection names the option, the expected shape, and the value."""
    series = _series(section_columns=bad)
    with pytest.raises(SeriesOptionError) as excinfo:
        series.getOption("section_columns")
    message = str(excinfo.value)

    assert "section_columns" in message
    assert "list of [column name, shown] pairs" in message
    assert problem in message
    assert repr(bad) in message
    # names the way out, which is what the old crash inside the table did not
    assert 'delete the "section_columns" entry under "options"' in message


def test_long_value_is_truncated():
    """A huge malformed value does not paste the whole thing into a dialog."""
    series = _series(section_columns="x" * 5000)
    with pytest.raises(SeriesOptionError) as excinfo:
        series.getOption("section_columns")
    assert len(str(excinfo.value)) < 800
    assert "..." in str(excinfo.value)


# ---------------------------------------------------------------------------
# valid values still pass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("option_name", COLUMN_OPTIONS)
def test_defaults_pass(option_name):
    """The shipped defaults are lists of tuples."""
    options = Series.getEmptyDict()["options"]
    series = _series(**{option_name: options[option_name]})
    assert series.getOption(option_name) == options[option_name]


def test_json_round_tripped_pairs_pass():
    """A jser round-trip turns every pair into a list, and that is still valid."""
    series = _series(section_columns=[["Thickness", True], ["Locked", False]])
    assert series.getOption("section_columns") == [
        ["Thickness", True], ["Locked", False]
    ]


def test_empty_list_passes():
    """Every column hidden is a list with no entries, not a malformed value."""
    series = _series(section_columns=[])
    assert series.getOption("section_columns") == []


def test_user_column_names_pass():
    """User columns are appended by name, so an unknown name is not malformed."""
    series = _series(object_columns=[("Range", True), ("some user column", False)])
    assert series.getOption("object_columns")[1] == ("some user column", False)


def test_get_default_is_not_checked():
    """`get_default=True` reads the shipped template, never the stored value."""
    series = _series(section_columns="Thickness")
    assert series.getOption("section_columns", get_default=True) == (
        Series.getEmptyDict()["options"]["section_columns"]
    )


def test_non_column_options_are_untouched():
    series = _series(small_dist=0.01, autoseg={})
    assert series.getOption("small_dist") == 0.01
    assert series.getOption("autoseg") == {}


# ---------------------------------------------------------------------------
# the message survives the trip to the dialog
# ---------------------------------------------------------------------------

def test_error_dialog_keeps_the_line_breaks(monkeypatch):
    """The global hook renders the message as rich text, so `\\n` needs help.

    Without this, a message that spells the expected shape and the fix out on
    separate lines arrives as one run-on paragraph. `show_save_error` already
    converted; the exception hook did not.
    """
    from PyReconstruct.modules.gui.utils import errors

    shown = {}

    def fake_show(summary_html, report, parent=None, title="Error"):
        shown["summary"] = summary_html

    monkeypatch.setattr(errors, "show_error_report", fake_show)

    series = _series(section_columns="Thickness")
    try:
        series.getOption("section_columns")
    except SeriesOptionError as err:
        errors.customExcepthook(type(err), err, err.__traceback__)

    summary = shown["summary"]
    lead = summary.split("Click <b>Copy report")[0]
    assert "\n" not in lead
    assert "<br>Problem: the value is a str, not a list.<br>Value:" in lead
    # still escaped, so a value carrying markup cannot render as markup
    assert "&quot;section_columns&quot;" in lead
