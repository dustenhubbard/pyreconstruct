"""Palette CSV preserves tag boundaries and pairs every coordinate."""

import csv
import itertools

import pytest

from PyReconstruct.modules.datatypes import Trace


@pytest.mark.parametrize("tags", [
    {"axon,1"},
    {"two words"},
    {"axon,beta"},
    {'say "axon"', "two words", "axon,beta", "[legacy]", "back\\slash"},
    {"line\nbreak", "tab\tcharacter", "café"},
    set(),
])
def test_palette_csv_roundtrip_preserves_tags_and_geometry(real_series, tmp_path, tags):
    trace = Trace("triangle", (10, 20, 30))
    trace.points = [(0.125, 0.25), (2.5, 0.75), (0.5, 3.25)]
    trace.tags = tags
    trace.fill_mode = ("solid", "selected")
    real_series.palette_traces["source"] = [trace]
    path = tmp_path / "palette.csv"

    real_series.exportTracePaletteCSV(str(path), "source")
    assert real_series.importTracePaletteCSV(str(path), "roundtrip")

    result, = real_series.palette_traces["roundtrip"]
    assert result.tags == tags
    assert list(result.points) == [(0.125, 0.25), (2.5, 0.75), (0.5, 3.25)]
    assert result.name == "triangle"
    assert result.color == (10, 20, 30)
    assert result.fill_mode == ("solid", "selected")


@pytest.mark.parametrize("tags", [
    'axon spine [legacy] "quoted"', '"quoted"', '"axon', '""',
])
def test_palette_csv_imports_legacy_space_separated_tags(real_series, tmp_path, tags):
    path = tmp_path / "legacy.csv"
    path.write_text(
        "Name,Color,Fill,Tags,X,Y\n"
        f"triangle,10 20 30,solid selected,{tags},0 2 0,0 0 2\n"
    )

    assert real_series.importTracePaletteCSV(str(path), "legacy")

    trace, = real_series.palette_traces["legacy"]
    assert trace.tags == set(tags.split())
    assert list(trace.points) == [(0, 0), (2, 0), (0, 2)]


@pytest.mark.parametrize("row", [
    "triangle,10 20 30,solid selected,axon,0 2 0,0 0\n",
    "triangle,10 20 30,solid selected,axon,0 2,0 0 2\n",
    "triangle,10 20 30,solid selected,axon,1,0 2 0,0 0 2\n",
    "triangle,10 20 30,solid selected,axon,,\n",
    "triangle,10 20 30,solid selected,axon,nan 2 0,0 0 2\n",
    "triangle,10 20 30,solid selected,axon,0 2 0,0 inf 2\n",
    "triangle,10 20 30,solid selected,axon,0 2 0\n",
])
def test_malformed_palette_csv_leaves_existing_palette_untouched(
    real_series, tmp_path, row
):
    name = real_series.palette_index[0]
    before = real_series.palette_traces[name]
    token = real_series.paletteToken(name)
    index = list(real_series.palette_index)
    path = tmp_path / "bad.csv"
    path.write_text(
        "Name,Color,Fill,Tags,X,Y\n"
        "valid,10 20 30,solid selected,axon,0 2 0,0 0 2\n" + row
    )

    with pytest.raises(ValueError):
        real_series.importTracePaletteCSV(str(path), name)

    assert real_series.palette_traces[name] is before
    assert real_series.palette_index == index
    assert real_series.paletteToken(name) == token


@pytest.mark.gui
@pytest.mark.parametrize("tags_header,tags_text", [("Tags", "axon"), ("TagsJSON", '["axon"]')])
@pytest.mark.parametrize("fill", ["", "solid", "solid selected extra", "unknown selected", "solid unknown"])
@pytest.mark.parametrize("replace", [True, False])
def test_invalid_csv_fill_preserves_palettes_and_editor(
    qtbot, real_series, tmp_path, tags_header, tags_text, fill, replace
):
    from PyReconstruct.modules.gui.dialog.trace_palette import TracePaletteDialog

    series = real_series
    name = series.palette_index[0] if replace else "new palette"
    series.palette_index[1] = 1
    before = dict(series.palette_traces)
    for palette in before:
        series.paletteToken(palette)
    tokens = dict(series.palette_tokens)
    index = list(series.palette_index)
    limit = csv.field_size_limit()
    path = tmp_path / "bad-fill.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", tags_header, "X", "Y"])
        writer.writerow(["valid", "10 20 30", "solid selected", tags_text, "0 2 0", "0 0 2"])
        writer.writerow(["triangle", "10 20 30", fill, tags_text, "0 2 0", "0 0 2"])

    with pytest.raises(ValueError, match="Invalid palette CSV at line 3: .*fill"):
        series.importTracePaletteCSV(str(path), name)

    assert series.palette_traces == before
    assert all(series.palette_traces[key] is value for key, value in before.items())
    assert series.palette_tokens == tokens
    assert series.palette_index == index
    assert csv.field_size_limit() == limit
    dialog = TracePaletteDialog(None, series)
    qtbot.addWidget(dialog)
    assert dialog.tab_widget.tabText(dialog.tab_widget.currentIndex()) == index[0]


@pytest.mark.gui
@pytest.mark.parametrize("tags_header,tags_text", [("Tags", "axon"), ("TagsJSON", '["axon"]')])
@pytest.mark.parametrize("x_text,y_text", [
    ("0", "0"),
    ("2.5", "-1"),
    ("1 1 1", "2 2 2"),
    ("0 1e308", "0 -1e308"),
    ("0 5e-324", "0 0"),
    ("0.0000001", "0"),
    ("0.0000001 0.0000001 0.0000001", "0 0 0"),
    ("123.4567891 123.4567891", "-0.25 -0.25"),
    ("4.566615243026992e-07 4.566615243026993e-07", "0 0"),
])
@pytest.mark.parametrize("replace", [True, False])
def test_zero_radius_csv_shape_preserves_palettes_and_editor(
    qtbot, real_series, tmp_path, tags_header, tags_text, x_text, y_text, replace
):
    from PyReconstruct.modules.gui.dialog.trace_palette import TracePaletteDialog

    series = real_series
    name = series.palette_index[0] if replace else "new palette"
    series.palette_index[1] = 1
    before = dict(series.palette_traces)
    for palette in before:
        series.paletteToken(palette)
    tokens = dict(series.palette_tokens)
    index = list(series.palette_index)
    path = tmp_path / "bad-shape.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", tags_header, "X", "Y"])
        writer.writerow(["valid", "10 20 30", "solid selected", tags_text, "0 2 0", "0 0 2"])
        writer.writerow(["dot", "10 20 30", "solid selected", tags_text, x_text, y_text])

    with pytest.raises(ValueError, match="Invalid palette CSV at line 3: .*radius"):
        series.importTracePaletteCSV(str(path), name)

    assert series.palette_traces == before
    assert all(series.palette_traces[key] is value for key, value in before.items())
    assert series.palette_tokens == tokens
    assert series.palette_index == index
    dialog = TracePaletteDialog(None, series)
    qtbot.addWidget(dialog)
    assert dialog.tab_widget.tabText(dialog.tab_widget.currentIndex()) == index[0]


@pytest.mark.gui
@pytest.mark.parametrize("tags_header,tags_text", [("Tags", "axon"), ("TagsJSON", '["axon"]')])
def test_csv_line_shape_imports_and_opens_in_editor(
    qtbot, real_series, tmp_path, tags_header, tags_text
):
    from PyReconstruct.modules.gui.dialog.trace_palette import TracePaletteDialog

    path = tmp_path / "line.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", tags_header, "X", "Y"])
        writer.writerow(["line", "10 20 30", "none none", tags_text, "0 2", "0 0"])

    assert real_series.importTracePaletteCSV(str(path), "lines")

    trace, = real_series.palette_traces["lines"]
    assert list(trace.points) == [(0, 0), (2, 0)]
    real_series.palette_index[:] = ["lines", 0]
    dialog = TracePaletteDialog(None, real_series)
    qtbot.addWidget(dialog)
    assert dialog.tab_widget.tabText(dialog.tab_widget.currentIndex()) == "lines"


@pytest.mark.gui
@pytest.mark.parametrize("tags_header,tags_text", [("Tags", "axon"), ("TagsJSON", '["axon"]')])
@pytest.mark.parametrize("color", [
    "", "10", "10 20", "10 20 30 40", "10 20 30 40 50",
    "-1 20 30", "10 -1 30", "10 20 -1",
    "256 20 30", "10 256 30", "10 20 256",
    "99999999999999999999999 20 30", "10.5 20 30", "nan 20 30",
])
@pytest.mark.parametrize("replace", [True, False])
def test_invalid_csv_color_preserves_palettes_and_label(
    qtbot, real_series, tmp_path, tags_header, tags_text, color, replace
):
    from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette
    from PyReconstruct.modules.gui.palette.outlined_label import OutlinedLabel

    series = real_series
    name = series.palette_index[0] if replace else "new palette"
    series.palette_index[1] = 1
    before = dict(series.palette_traces)
    for palette in before:
        series.paletteToken(palette)
    tokens = dict(series.palette_tokens)
    index = list(series.palette_index)
    selected = series.palette_traces[index[0]][index[1]]
    limit = csv.field_size_limit()
    path = tmp_path / "bad-color.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", tags_header, "X", "Y"])
        writer.writerow(["valid", "10 20 30", "solid selected", tags_text, "0 2 0", "0 0 2"])
        writer.writerow(["triangle", color, "solid selected", tags_text, "0 2 0", "0 0 2"])

    with pytest.raises(ValueError, match="Invalid palette CSV at line 3"):
        series.importTracePaletteCSV(str(path), name)

    assert series.palette_traces == before
    assert all(series.palette_traces[key] is value for key, value in before.items())
    assert series.palette_tokens == tokens
    assert series.palette_index == index
    assert csv.field_size_limit() == limit
    label = OutlinedLabel(None)
    qtbot.addWidget(label)
    palette = MousePalette.__new__(MousePalette)
    palette.series = series
    palette.palette_buttons = [None] * len(before[index[0]])
    palette.label = label
    palette.placeLabel = lambda: None
    palette.updateLabel()
    assert palette.selectedTrace() is selected
    assert label.text() == selected.name
    assert label.brush.color().getRgb() == (*selected.color, 255)


@pytest.mark.gui
@pytest.mark.parametrize("tags_header,tags_text", [("Tags", "axon"), ("TagsJSON", '["axon"]')])
@pytest.mark.parametrize("color", [(0, 0, 0), (255, 255, 255), (0, 128, 255)])
def test_palette_csv_roundtrips_rgb_boundaries_in_label(
    main_window, main_window_dialogs, tmp_path, tags_header, tags_text, color
):
    path = tmp_path / "rgb.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", tags_header, "X", "Y"])
        writer.writerow([
            "triangle", " ".join(map(str, color)), "solid selected", tags_text, "0 2 0", "0 0 2"
        ])
    main_window_dialogs.file_responses = [str(path)]

    main_window.importTracePaletteCSV()

    series = main_window.series
    trace = main_window.mouse_palette.selectedTrace()
    assert series.palette_index == ["rgb", 0]
    assert trace.color == color
    assert trace.tags == {"axon"}
    assert list(trace.points) == [(0, 0), (2, 0), (0, 2)]
    assert main_window.mouse_palette.label.text() == "triangle"
    assert main_window.mouse_palette.label.brush.color().getRgb() == (*color, 255)
    series.exportTracePaletteCSV(str(path), "rgb")
    assert series.importTracePaletteCSV(str(path), "roundtrip")
    result, = series.palette_traces["roundtrip"]
    assert result.color == color
    assert result.tags == {"axon"}
    assert list(result.points) == [(0, 0), (2, 0), (0, 2)]


@pytest.mark.parametrize("tags_header,tags_text", [("Tags", "axon"), ("TagsJSON", '["axon"]')])
@pytest.mark.parametrize("fill", list(itertools.product(
    ["none", "transparent", "solid"], ["none", "selected", "unselected", "always"]
)))
def test_palette_csv_preserves_valid_fill_pairs(real_series, tmp_path, tags_header, tags_text, fill):
    path = tmp_path / "valid-fill.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", tags_header, "X", "Y"])
        writer.writerow(["triangle", "10 20 30", " ".join(fill), tags_text, "0 2 0", "0 0 2"])

    assert real_series.importTracePaletteCSV(str(path), "valid")
    real_series.exportTracePaletteCSV(str(path), "valid")
    assert real_series.importTracePaletteCSV(str(path), "roundtrip")

    trace, = real_series.palette_traces["roundtrip"]
    assert trace.fill_mode == fill
    assert trace.tags == {"axon"}
    assert list(trace.points) == [(0, 0), (2, 0), (0, 2)]


def test_large_palette_geometry_roundtrips_without_changing_csv_field_limit(real_series, tmp_path):
    trace = Trace("large", (10, 20, 30))
    points = [(i / 10001, (i + 1) / 10001) for i in range(10000)]
    trace.points = points
    real_series.palette_traces["source"] = [trace]
    path = tmp_path / "large.csv"
    real_series.exportTracePaletteCSV(str(path), "source")
    limit = csv.field_size_limit()

    assert real_series.importTracePaletteCSV(str(path), "large")

    result, = real_series.palette_traces["large"]
    assert list(result.points) == points
    assert csv.field_size_limit() == limit


@pytest.mark.parametrize("tags", ['["axon", 1]', '{"axon": true}', '"axon"', '["axon"'])
def test_invalid_json_tags_leave_existing_palette_untouched(real_series, tmp_path, tags):
    name = real_series.palette_index[0]
    before = real_series.palette_traces[name]
    limit = csv.field_size_limit()
    path = tmp_path / "bad-tags.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Color", "Fill", "TagsJSON", "X", "Y"])
        writer.writerow(["triangle", "10 20 30", "solid selected", tags, "0 2 0", "0 0 2"])

    with pytest.raises(ValueError, match="Invalid palette CSV at line 2"):
        real_series.importTracePaletteCSV(str(path), name)

    assert real_series.palette_traces[name] is before
    assert csv.field_size_limit() == limit


@pytest.mark.gui
@pytest.mark.parametrize("row", [
    "triangle,10 20 30,solid selected,axon,0 2 0,0 0\n",
    "triangle,10 20 30,,axon,0 2 0,0 0 2\n",
    "triangle,10 20 30,solid,axon,0 2 0,0 0 2\n",
    "triangle,10 20,solid selected,axon,0 2 0,0 0 2\n",
    "triangle,99999999999999999999999 20 30,solid selected,axon,0 2 0,0 0 2\n",
])
def test_window_reports_invalid_palette_csv_without_adding_a_palette(
    main_window, main_window_dialogs, tmp_path, row
):
    series = main_window.series
    before = dict(series.palette_traces)
    for palette in before:
        series.paletteToken(palette)
    tokens = dict(series.palette_tokens)
    index = list(series.palette_index)
    path = tmp_path / "bad.csv"
    path.write_text(
        "Name,Color,Fill,Tags,X,Y\n" + row
    )
    main_window_dialogs.file_responses = [str(path)]
    main_window.seriesModified(False)

    main_window.importTracePaletteCSV()

    assert series.palette_traces == before
    assert all(series.palette_traces[key] is value for key, value in before.items())
    assert series.palette_tokens == tokens
    assert series.palette_index == index
    assert not series.modified
    assert len(main_window_dialogs.notices) == 1
    assert "line 2" in main_window_dialogs.notices[0]
    assert "Nothing was imported." in main_window_dialogs.notices[0]
