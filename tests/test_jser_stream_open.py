"""Opening a .jser one section at a time.

``Series.openJser`` used to parse the whole file into one document and keep it
alive through the series build: a 1.4 GB series peaked at 10.3 GB. Now
``scan_jser`` indexes the file by byte range, the collision check reads only the
contour names, and the unpack decodes one section at a time. Anything the scan
does not read goes back to the whole-file read.

What is pinned here:

* the scan is faithful: every section range decodes to the same value the whole
  parse holds, and the names, series and log match, at every buffer size down
  to one byte, so no boundary case hides;
* every shape the scan refuses raises ``NotStreamable``, never a wrong index;
* the hidden directory an open writes is byte for byte the one the whole-file
  read writes, on compact, pretty, renamed and colliding files;
* the open never hands the whole file to the parser;
* the collision question still comes before the hidden directory exists.
"""

import json
import os

import pytest

from PyReconstruct.modules.backend.notifier import Notifier, NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import jser_scan
from PyReconstruct.modules.constants.fast_json import fast_loads
from PyReconstruct.modules.constants.jser_format import dumps_jser
from PyReconstruct.modules.constants.jser_scan import (
    NotStreamable,
    read_range,
    scan_jser,
)
from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes.series import Series, SeriesOpenError

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)


def shapes1():
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    with open(FIXTURE) as f:
        return json.load(f)


def tricky_doc(openable=False):
    """shapes1, with every structure the scan has to step over or decode.

    `openable` leaves out the sections whose contours are null or missing:
    the scan reads them, but ``Section.updateJSON`` cannot, on either path.
    """
    doc = shapes1()
    first = next(i for i, s in enumerate(doc["sections"]) if s)
    sd = doc["sections"][first]
    names = list(sd["contours"])
    # keys that need escapes, hold structural bytes, or are not ASCII
    for name, new in zip(names, [
        'quo"te', "back\\slash", "café ☃", "br}ac]k[s{",
        "comma, space", "tab\there",
    ]):
        sd["contours"][new] = sd["contours"].pop(name)
    sd["flags"] = []                      # a flat array as a whole value
    sd["extra"] = {"a": [[], {}, [1e-7, -2.5E+3]], "s": "]}[{\\\""}
    doc["sections"].insert(first, None)   # null slots, also leading
    doc["sections"].append(None)
    doc["sections"].append({**sd, "contours": {}})
    if not openable:
        doc["sections"].append({**sd, "contours": None})
        no_contours = dict(sd)
        del no_contours["contours"]
        doc["sections"].append(no_contours)
    doc["log"] = "Date, Time, User, Obj, Sections, Event\n\"quoted\", é"
    return doc


def as_bytes(doc, form):
    if form == "compact":
        return dumps_jser(doc, pretty=False)
    if form == "pretty":
        return dumps_jser(doc, pretty=True)
    if form == "stdlib-indent":
        return json.dumps(doc, indent=2).encode()
    if form == "raw-utf8":
        return json.dumps(doc, ensure_ascii=False).encode("utf-8")
    raise ValueError(form)


FORMS = ("compact", "pretty", "stdlib-indent", "raw-utf8")


def write(folder, data, name="probe"):
    folder.mkdir(exist_ok=True)
    fp = folder / f"{name}.jser"
    fp.write_bytes(data)
    return str(fp)


def scan(fp):
    with open(fp, "rb") as f:
        index = scan_jser(f)
        decoded = [
            None if r is None else fast_loads(read_range(f, r))
            for r in index.sections
        ]
    return index, decoded


# ---------------------------------------------------------------------------
# the scan alone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64, None])
@pytest.mark.parametrize("form", FORMS)
def test_scan_matches_the_whole_parse(tmp_path, monkeypatch, form, chunk):
    """Every range, name, series and log value, at every buffer boundary."""
    if chunk is not None:
        monkeypatch.setattr(jser_scan, "_CHUNK", chunk)
    data = as_bytes(tricky_doc(), form)
    whole = json.loads(data)

    index, decoded = scan(write(tmp_path, data))

    assert decoded == whole["sections"]
    assert index.names == [
        None if s is None else list(s.get("contours") or {})
        for s in whole["sections"]
    ]
    assert index.series == whole["series"]
    assert index.has_log and index.log == whole["log"]


def test_scan_without_a_log(tmp_path):
    doc = shapes1()
    doc.pop("log", None)
    index, _ = scan(write(tmp_path, as_bytes(doc, "compact")))
    assert index.has_log is False


def modern(**over):
    doc = {"sections": [{"contours": {"a": []}}], "series": {}, "log": ""}
    doc.update(over)
    return json.dumps(doc).encode()


REFUSED = {
    "legacy layout": json.dumps({"probe.ser": {}, "probe.0": {"contours": {}}}).encode(),
    "unknown key": modern(extra=1),
    "repeated top key": b'{"sections": [{}], "series": {}, "series": {}}',
    "repeated section key": b'{"sections": [{"contours": {}, "contours": {}}], "series": {}}',
    "section is a list": modern(sections=[[1]]),
    "section is a number": modern(sections=[1]),
    "contours is a list": modern(sections=[{"contours": ["a"]}]),
    "series is a list": modern(series=[]),
    "no series": json.dumps({"sections": [{}]}).encode(),
    "all sections null": modern(sections=[None, None]),
    "sections is an object": modern(sections={}),
    "missing comma": b'{"sections": [{} {}], "series": {}}',
    "trailing comma": b'{"sections": [{},], "series": {}}',
    "trailing bytes": modern() + b" x",
    "byte order mark": b"\xef\xbb\xbf" + modern(),
    "truncated": modern()[:-5],
    "not json": b"this is not json",
    "empty file": b"",
    "nan in series": b'{"sections": [{}], "series": {"a": NaN}}',
    "nul for null": b'{"sections": [nul], "series": {}}',
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_scan_refuses_every_other_shape(tmp_path, case):
    with pytest.raises(NotStreamable):
        scan(write(tmp_path, REFUSED[case]))


# ---------------------------------------------------------------------------
# the open: same bytes as the whole-file read
# ---------------------------------------------------------------------------

def hidden_files(fp):
    hidden = os.path.join(os.path.dirname(fp), "." + os.path.basename(fp)[:-5])
    out = {}
    for name in sorted(os.listdir(hidden)):
        with open(os.path.join(hidden, name), "rb") as f:
            out[name] = f.read()
    return out


def refuse(cls, fp):
    raise NotStreamable("forced by the test")


def open_and_read(fp, monkeypatch, whole):
    """Open `fp`, return its hidden dir's bytes; `whole` forces the old read."""
    with monkeypatch.context() as m:
        if whole:
            m.setattr(series_module._StreamedJser, "open", classmethod(refuse))
        series = Series.openJser(
            fp, progress=NullProgressReporter, notifier=NullNotifier()
        )
    try:
        return hidden_files(fp)
    finally:
        series.close()


def renamed(doc, renames):
    for sd in doc["sections"]:
        if sd:
            for old, new in renames.items():
                if old in sd["contours"]:
                    sd["contours"][new] = sd["contours"].pop(old)
    return doc


DOCS = {
    "shapes1": lambda: shapes1(),
    "tricky": lambda: tricky_doc(openable=True),
    "rename": lambda: renamed(shapes1(), {"star": "my star"}),
    "collision": lambda: renamed(shapes1(), {"star": "my trace", "square": "my,trace"}),
}


@pytest.mark.parametrize("form", ("compact", "pretty", "stdlib-indent"))
@pytest.mark.parametrize("doc", sorted(DOCS))
def test_open_writes_the_bytes_the_whole_read_writes(tmp_path, monkeypatch, doc, form):
    data = as_bytes(DOCS[doc](), form)
    streamed = write(tmp_path / "s", data)
    old = write(tmp_path / "w", data)

    assert open_and_read(streamed, monkeypatch, whole=False) == \
        open_and_read(old, monkeypatch, whole=True)


def test_a_section_only_the_stdlib_parser_reads(tmp_path, monkeypatch):
    """orjson refuses NaN; that section alone takes fast_loads' stdlib leg."""
    data = as_bytes(shapes1(), "compact")
    data = data.replace(b'"thickness":0.05', b'"thickness":NaN', 1)
    assert b"NaN" in data
    streamed = write(tmp_path / "s", data)
    old = write(tmp_path / "w", data)

    assert open_and_read(streamed, monkeypatch, whole=False) == \
        open_and_read(old, monkeypatch, whole=True)


def test_a_legacy_layout_opens_through_the_whole_read(tmp_path, monkeypatch):
    """Section numbers as top-level keys: the oldest shape still opens."""
    doc = shapes1()
    legacy = {"probe.ser": doc["series"]}
    for snum, sd in enumerate(doc["sections"]):
        if sd is not None:
            legacy[f"probe.{snum}"] = sd
    old = write(tmp_path, json.dumps(legacy).encode())
    doc["log"] = "Date, Time, User, Obj, Sections, Event"
    new = write(tmp_path / "m", json.dumps(doc).encode())

    assert open_and_read(old, monkeypatch, whole=False) == \
        open_and_read(new, monkeypatch, whole=False)


def test_the_open_never_parses_the_whole_file(tmp_path, monkeypatch):
    """The 10 GB peak was one parse of the whole file; no call may see it."""
    data = as_bytes(shapes1(), "compact")
    fp = write(tmp_path, data)
    seen = []
    real = series_module.fast_loads

    def spying(raw):
        seen.append(len(raw))
        return real(raw)

    monkeypatch.setattr(series_module, "fast_loads", spying)
    files = open_and_read(fp, monkeypatch, whole=False)

    assert len(files) > 2
    assert seen, "the open decoded nothing through series.fast_loads"
    assert max(seen) < len(data)


def test_the_whole_read_lets_go_of_each_section():
    """The fallback hands each section over once and keeps no copy."""
    doc = shapes1()
    doc["log"] = ""
    source = series_module._WholeJser(doc)
    count = sum(1 for _ in source.sections())
    assert count == sum(1 for s in shapes1()["sections"] if s is not None)
    assert all(s is None for s in doc["sections"])


# ---------------------------------------------------------------------------
# the collision question and failures
# ---------------------------------------------------------------------------

class Recorder(Notifier):
    """Says no, and notes whether the hidden directory existed when asked."""

    def __init__(self, hidden):
        self.hidden = hidden
        self.asked = []

    def notify(self, message):
        return False

    def confirm(self, message, title="Confirm"):
        self.asked.append((message, os.path.isdir(self.hidden)))
        return False


def test_the_question_comes_before_the_hidden_dir(tmp_path, monkeypatch):
    """Names that meet only across sections are still found, and asked first."""
    doc = shapes1()
    filled = [sd for sd in doc["sections"] if sd and sd["contours"]]
    assert len(filled) >= 2
    a, b = filled[0], filled[1]
    a["contours"]["one name"] = a["contours"].pop(next(iter(a["contours"])))
    b["contours"]["one,name"] = b["contours"].pop(next(iter(b["contours"])))
    data = as_bytes(doc, "compact")
    answers = {}
    for whole in (False, True):
        sub = tmp_path / str(whole)
        fp = write(sub, data)
        notifier = Recorder(str(sub / ".probe"))
        with monkeypatch.context() as m:
            if whole:
                m.setattr(series_module._StreamedJser, "open", classmethod(refuse))
            result = Series.openJser(
                fp, progress=NullProgressReporter, notifier=notifier
            )
        assert result is None
        assert not (sub / ".probe").exists()
        answers[whole] = notifier.asked

    assert len(answers[False]) == 1
    assert answers[False][0][1] is False, "asked after the hidden dir existed"
    assert "one_name" in answers[False][0][0]
    assert answers[False] == answers[True]


def test_a_corrupt_section_fails_like_a_corrupt_file(tmp_path):
    """A bad value the scan skips is caught when its section is decoded."""
    data = as_bytes(shapes1(), "compact")
    data = data.replace(b'"thickness":0.05', b'"thickness":0.0.5', 1)
    assert b"0.0.5" in data
    fp = write(tmp_path, data)
    before = os.stat(fp).st_mtime_ns

    with pytest.raises(SeriesOpenError, match="corrupt or is not JSON"):
        Series.openJser(fp, progress=NullProgressReporter, notifier=NullNotifier())

    assert not (tmp_path / ".probe").exists()
    assert os.stat(fp).st_mtime_ns == before
