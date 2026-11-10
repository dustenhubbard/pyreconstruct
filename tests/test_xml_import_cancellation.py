"""Canceling legacy XML conversion leaves the inputs usable for another import."""

import pytest

from PyReconstruct.modules.backend.func import xml_json_conversions as conv
from PyReconstruct.modules.constants import blank_series


class _Progress:
    def __init__(self, cancel_at=None):
        self.value = 0
        self.cancel_at = cancel_at
        self.closed = False

    def setValue(self, value):
        self.value = value

    def wasCanceled(self):
        return self.cancel_at is not None and self.value >= self.cancel_at

    def close(self):
        self.closed = True


@pytest.mark.parametrize("cancel_at", [0, 25, 50])
def test_canceled_import_can_be_retried(qapp, tmp_path, monkeypatch, cancel_at):
    ser = tmp_path / "sample.ser"
    ser.write_text(
        blank_series.replace("[SECTION_NUM]", "1")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "2")
        .replace("[LASTTHUMBSECTION]", "2"),
        encoding="utf-8",
    )
    for n in (1, 2):
        (tmp_path / f"sample.{n}").write_text(
            f'<Section index="{n}" thickness="0.05" alignLocked="false">'
            '<Transform dim="0" xcoef="0 1 0 0 0 0" ycoef="0 0 1 0 0 0">'
            '<Contour name="axon" hidden="false" closed="true" '
            'simplified="false" border="1 0 0" fill="1 0 0" mode="9" '
            'points="0 0, 4 0, 4 4, 0 4,"/>'
            '</Transform></Section>',
            encoding="utf-8",
        )
    originals = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    progress = _Progress(cancel_at)
    monkeypatch.setattr(conv, "getProgbar", lambda *args, **kwargs: progress)

    assert conv.xmlToJSON(str(ser)) is None
    assert progress.closed
    assert progress.value == cancel_at
    assert {name: (tmp_path / name).read_bytes() for name in originals} == originals

    progress = _Progress()
    series = conv.xmlToJSON(str(ser))
    try:
        assert sorted(series.sections) == [1, 2]
        assert series.current_section == 1
        for n in (1, 2):
            section = series.loadSection(n)
            assert section.src == ""
            assert section.mag == 0.00254
            assert section.thickness == 0.05
            assert [trace.name for trace in section.tracesAsList()] == ["axon"]
            for point, expected in zip(
                section.contours["axon"][0].points,
                [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
                strict=True,
            ):
                assert point == pytest.approx(expected, abs=0.00254)
    finally:
        series.close()
    assert progress.closed
