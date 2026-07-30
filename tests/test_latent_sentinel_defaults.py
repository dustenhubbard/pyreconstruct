"""Four functions that raise or silently no-op when called with their own
documented default.

Each one is the same shape: a parameter documented as optional, defaulting to
``None``, that is then dereferenced as a container. In three of the four the
guard exists but sits after the use or inverts its sense, which is why reading
the guard alone says the code is fine:

- ``ObjGroupDict.__init__``  runs ``groups.copy().items()`` four lines before
  ``if groups:``.
- ``optimizeSeriesBC``       tests ``section_nums is not None and snum in
  section_nums``, so the documented default optimizes zero sections instead of
  every section.
- ``seriesToLabels``         runs ``range(*window[1])`` before ``if window:``,
  which makes the ``else`` branch that reads the window back off the zarr
  unreachable.
- ``Series.importTraces``    runs ``range(*srange)`` with no guard at all.

None of the four had a caller that reached the default, so none of them can be
provoked from the GUI as shipped. They are covered here because the default is
the documented entry point and the next caller to use it gets a traceback or a
silent no-op.
"""

import types

import pytest


# --------------------------------------------------------------------------- #
# ObjGroupDict.__init__
# --------------------------------------------------------------------------- #
def test_obj_group_dict_accepts_its_documented_default():
    """``groups`` is documented "an existing group dictionary to build from" and
    defaults to None, meaning there is no existing dictionary. The empty-group
    scan dereferenced it first.
    """
    from PyReconstruct.modules.datatypes.obj_group_dict import ObjGroupDict

    g = ObjGroupDict(None, "objects")

    assert g.groups == {}
    assert g.objects == {}
    assert g.contain_type == "objects"


def test_obj_group_dict_still_drops_empty_groups():
    """The scan the guard now sits in front of has to keep working: a group
    whose object list is empty is not a group.
    """
    from PyReconstruct.modules.datatypes.obj_group_dict import ObjGroupDict

    g = ObjGroupDict(None, "objects", {"real": ["a", "b"], "hollow": []})

    assert set(g.groups) == {"real"}
    assert g.groups["real"] == {"a", "b"}


# --------------------------------------------------------------------------- #
# optimizeSeriesBC
# --------------------------------------------------------------------------- #
class _RecordingSection:
    def __init__(self, n, saved):
        self.n = n
        self._saved = saved

    def save(self):
        self._saved.append(self.n)


class _RecordingSeries:
    """The slice of Series that optimizeSeriesBC reaches for."""

    def __init__(self, snums):
        self.snums = snums
        self.saved = []

    def enumerateSections(self, *args, **kwargs):
        for n in self.snums:
            yield n, _RecordingSection(n, self.saved)


@pytest.fixture()
def no_op_section_bc(monkeypatch):
    """optimizeSectionBC needs real image data. Which sections it is called for
    is the whole question here, so replace it and count the calls.
    """
    from PyReconstruct.modules.backend.view import optimize_bc

    called = []
    monkeypatch.setattr(
        optimize_bc,
        "optimizeSectionBC",
        lambda section, *a, **k: called.append(section.n),
    )
    return called


def test_optimize_series_bc_default_optimizes_every_section(no_op_section_bc):
    """``section_nums=None`` is "no restriction", the same as the ``window=None``
    beside it. The inverted guard turned it into "no sections", so the
    documented default did nothing and reported nothing.
    """
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSeriesBC

    series = _RecordingSeries([0, 1, 2])
    optimizeSeriesBC(series)

    assert no_op_section_bc == [0, 1, 2]
    assert series.saved == [0, 1, 2]


def test_optimize_series_bc_still_restricts_to_the_given_sections(no_op_section_bc):
    """The restriction is the reason the parameter exists; widening None must
    not widen an explicit list.
    """
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSeriesBC

    series = _RecordingSeries([0, 1, 2, 3])
    optimizeSeriesBC(series, section_nums=[1, 3])

    assert no_op_section_bc == [1, 3]
    assert series.saved == [1, 3]


# --------------------------------------------------------------------------- #
# seriesToLabels
# --------------------------------------------------------------------------- #
class _FakeZarrArray:
    def __init__(self, attrs):
        self.shape = (3, 64, 64)
        self.attrs = attrs


class _FakeZarrGroup(dict):
    def __init__(self, raw):
        super().__init__()
        self["raw"] = raw
        self.created = {}

    def create_dataset(self, name, **kwargs):
        self[name] = _FakeZarrArray({})
        self.created[name] = kwargs


class _CountingThreadPool:
    """Stands in for ThreadPoolProgBar: records one entry per queued section."""

    def __init__(self):
        self.workers = []

    def createWorker(self, fn, *args, **kwargs):
        self.workers.append(args)

    def startAll(self, *args, **kwargs):
        pass


@pytest.fixture()
def labels_zarr(monkeypatch):
    """A zarr whose ``raw`` array carries the attributes seriesToZarr writes,
    plus a threadpool that queues instead of running.
    """
    from PyReconstruct.modules.backend.autoseg import conversions

    raw = _FakeZarrArray(
        {
            "alignment": {"0": [], "1": [], "2": [], "5": [], "6": []},
            "window": [10.0, 20.0, 8.0, 4.0],
            "offset": [0, 0, 0],
            "sections": [0, 1, 2],
            "true_mag": 0.008,
            "voxel_size": [50, 8, 8],
        }
    )
    group = _FakeZarrGroup(raw)
    pools = []

    def make_pool():
        pool = _CountingThreadPool()
        pools.append(pool)
        return pool

    monkeypatch.setattr(
        conversions, "zarr", types.SimpleNamespace(open=lambda *a, **k: group)
    )
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", make_pool)
    return group, pools


def test_series_to_labels_reads_the_section_range_off_the_zarr(labels_zarr):
    """``window=None`` is supported by the ``else`` branch, which reads the
    window back out of ``raw.attrs``. ``range(*window[1])`` ran first, so that
    branch was dead code and the documented default raised TypeError.
    """
    from PyReconstruct.modules.backend.autoseg.conversions import seriesToLabels

    group, pools = labels_zarr

    seriesToLabels(None, "/nonexistent.zarr", group="mito")

    ## one queued worker per section named in raw.attrs["sections"]
    assert len(pools) == 1
    assert [args[1] for args in pools[0].workers] == [0, 1, 2]

    ## and the labels dataset is shaped from the window stored on the zarr:
    ## 3 sections, h/mag = 4.0/0.008, w/mag = 8.0/0.008
    assert group.created["labels_mito"]["shape"] == (3, 500, 1000)


def test_series_to_labels_still_prefers_an_explicit_window(labels_zarr):
    """When a window is supplied it carries its own section range as element 1,
    and that range wins over the one recorded on the zarr.
    """
    from PyReconstruct.modules.backend.autoseg.conversions import seriesToLabels

    group, pools = labels_zarr

    seriesToLabels(
        None,
        "/nonexistent.zarr",
        group="mito",
        window=[[0.0, 0.0, 8.0, 4.0], (5, 7)],
        raw_window=[0.0, 0.0, 8.0, 4.0],
    )

    assert [args[1] for args in pools[0].workers] == [5, 6]
    assert group.created["labels_mito"]["shape"][0] == 2


# --------------------------------------------------------------------------- #
# Series.importTraces
# --------------------------------------------------------------------------- #
class _ImportedSection:
    def __init__(self, n, visited):
        self.n = n
        self._visited = visited

    def importTraces(self, *args, **kwargs):
        self._visited.append(self.n)


def _import_stubs(snums):
    """Build the two Series stubs importTraces needs to reach its skip test.

    Only the section-range decision is under test, so the attribute merge past
    the loop is switched off (``import_obj_attrs=False``). Logging stays on,
    because ``histories.importLogs`` is the second consumer of ``srange`` in the
    same body and it has to see the same value.
    """
    from PyReconstruct.modules.datatypes.log import LogSet
    from PyReconstruct.modules.datatypes.series import Series

    empty_logset = LogSet.__new__(LogSet)
    empty_logset.all_logs = []

    visited = []

    class _Data(dict):
        supress_logging = False

    this = Series.__new__(Series)
    this.data = _Data()
    this.getFullHistory = lambda: empty_logset
    this.enumerateSections = lambda *a, **k: iter(
        [(n, _ImportedSection(n, visited)) for n in snums]
    )
    this.save = lambda *a, **k: None
    this.addLog = lambda *a, **k: None

    other = Series.__new__(Series)
    other.getFullHistory = lambda: empty_logset
    other.sections = {n: f"s{n}" for n in snums}
    other.loadSection = lambda n: _ImportedSection(n, [])

    return this, other, visited


def test_import_traces_default_srange_covers_every_section():
    """``srange`` is documented "the range of sections to include in import" and
    defaults to None. ``range(*None)`` raises TypeError, so the default was not
    a default at all.
    """
    from PyReconstruct.modules.datatypes.series import Series

    this, other, visited = _import_stubs([0, 1, 2])
    Series.importTraces(this, other, import_obj_attrs=False)

    assert visited == [0, 1, 2]


def test_import_traces_still_honors_an_explicit_srange():
    """The range is exclusive at the top end, and widening the default must not
    widen an explicit range.
    """
    from PyReconstruct.modules.datatypes.series import Series

    this, other, visited = _import_stubs([0, 1, 2, 3])
    Series.importTraces(this, other, srange=(1, 3), import_obj_attrs=False)

    assert visited == [1, 2]


def test_import_traces_restores_logging_suppression_on_the_default_path():
    """The suppression flag is process-wide for the session. Widening the range
    must not change that it is always put back.
    """
    from PyReconstruct.modules.datatypes.series import Series

    this, other, _ = _import_stubs([0, 1])
    Series.importTraces(this, other, import_obj_attrs=False)

    assert this.data.supress_logging is False
