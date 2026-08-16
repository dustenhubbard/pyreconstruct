import os
import re
import json
import shutil
from datetime import datetime
from copy import copy, deepcopy
from pathlib import Path
from typing import Union

from .log import LogSet, LogSetPair
from .ztrace import Ztrace
from .section import Section
from .trace import Trace, normalizeObjectName
from .trace_id import TraceIDIssuer
from .transform import Transform
from .obj_group_dict import ObjGroupDict
from .series_data import SeriesData
from .objects import Objects
from .default_settings import default_settings, default_series_settings
from .host_tree import HostTree
from .filters import passesFilters

from PyReconstruct.modules.calc import traceGeometry

from PyReconstruct.modules.constants import (
    createHiddenDir,
    welcome_series_dir,
    getDateTime,
    fast_loads,
    fast_dumps,
    dumps_jser,
    canon_keys_inplace,
    JSER_SCHEMA_VERSION,
    SERIES_KEYS,
    default_traces,
)


class SeriesOpenError(Exception):
    """Raised when a file cannot be opened as a series (corrupt or not a jser)."""


class SeriesSaveError(Exception):
    """Raised when a series cannot be written without losing a section.

    Always raised before anything is written, so the existing .jser on disk is
    still the last good copy when this reaches the caller.
    """


class SeriesOptionError(Exception):
    """Raised when an option read from the series file has the wrong shape."""


def _checkColumnsOption(option_name : str, value):
    """Raise if a ``*_columns`` option is not a list of (name, shown) pairs.

    The table widgets do ``dict(columns)`` and ``for name, shown in columns``
    straight off the stored value, so a malformed one does not fail here: it
    fails several frames later with ``dictionary update sequence element #0 has
    length 1; 2 is required`` or ``'dict' object has no attribute 'append'``,
    neither of which names the option, the file, or the fix. These options are
    written verbatim into the .jser, and the .jser is meant to be hand-editable,
    so a typo in one is a shape a user can actually produce.

    Checking the shape rather than only the type is the point. A flat
    ``["Thickness", "Locked"]`` passes ``type(value) is list`` and still crashes
    ``dict(columns)``, so a type-only check would move the error message without
    covering the case.

    Pairs are compared loosely: in memory they are tuples, and a jser round-trip
    turns every one of them into a list.

        Params:
            option_name (str): the name of the option being read
            value: the stored value to check
        Raises:
            SeriesOptionError: if `value` is not a list of (name, shown) pairs
    """
    def _bad(problem : str):
        shown = repr(value)
        if len(shown) > 200:
            shown = shown[:200] + "..."
        raise SeriesOptionError(
            f'The series option "{option_name}" is malformed, so the list that '
            f"uses it cannot be built.\n\n"
            f"Expected a list of [column name, shown] pairs, for example "
            f'[["Thickness", true], ["Locked", false]].\n'
            f"Problem: {problem}.\n"
            f"Value: {shown}\n\n"
            f'Fix or delete the "{option_name}" entry under "options" in the '
            f"series file. Deleting it restores the built-in default."
        )

    if not isinstance(value, list):
        _bad(f"the value is a {type(value).__name__}, not a list")
    for i, pair in enumerate(value):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            _bad(f"entry {i} is not a [column name, shown] pair")
        if not isinstance(pair[0], str):
            _bad(
                f"entry {i} has a {type(pair[0]).__name__} where the column "
                f"name should be"
            )
def contourNameCollisions(jser_data : dict) -> dict:
    """Find the object names a load would fold together, without loading.

    ``Section.updateJSON`` normalizes a contour key that contains whitespace or
    a comma, and appends its traces to whatever contour already holds the
    normalized name. Two names that differ only in those characters therefore
    become one object, and the second one's identity is gone: its groups, its
    comment, its curation status and its hosts are all keyed by the name that no
    longer exists.

    Reported over the whole file rather than per section, because two names can
    collide across sections without ever meeting inside one, and the series data
    they orphan is series-wide either way.

        Params:
            jser_data (dict): the parsed jser
        Returns:
            (dict): merged name -> the sorted source names folded into it, for
                every name with more than one source. A name that is merely
                renamed (one source) is not a collision and is not listed.
    """
    sources = {}
    for section_data in jser_data.get("sections") or []:
        if not section_data:
            continue
        for cname in (section_data.get("contours") or {}):
            sources.setdefault(normalizeObjectName(cname), set()).add(cname)
    return {
        merged: sorted(names, key=str)
        for merged, names in sources.items()
        if len(names) > 1
    }


def contourMergeWarning(collisions : dict) -> str:
    """The text shown before a load folds distinct objects together.

    Separate from the load so it can be read and tested without one, and so the
    caller decides how to surface it.
    """
    lines = [
        "This series has object names that differ only in spaces or commas.",
        "",
        "Object names cannot hold either character, so opening the series "
        "converts them to underscores. Where that produces a name another "
        "object already has, the two become one object. Their traces are all "
        "kept, but only one set of groups, comments, curation and hosts "
        "survives the merge.",
        "",
    ]
    for merged in sorted(collisions, key=str):
        names = ", ".join(repr(n) for n in collisions[merged])
        lines.append(f"    {names} -> {merged!r}")
    lines += [
        "",
        "Cancel to leave the file untouched, then rename the objects in a copy "
        "if you want to keep them apart.",
    ]
    return "\n".join(lines)


def applyContourRenames(series_data : dict, renames : dict, collisions : dict):
    """Repoint the series' object references after contours have been renamed.

    ``Section.updateJSON`` renames the contour keys but only ever sees one
    section. Everything a series knows *about* an object -- its group
    memberships, its ``obj_attrs`` entry (comment, curation, alignment, user
    column values, last user, 3D settings) and its place in the host tree -- is
    keyed by name in the series file, and was left behind pointing at a name no
    section holds any more. Renaming a contour and dropping all of that is
    silent data loss on a plain open, with no collision needed.

    Where several names merged onto one, only one attribute set can survive.
    The winner is the source that already had the merged name if there is one
    (it was not renamed, so nothing about it should change), otherwise the first
    in sorted order. Groups and hosts are unioned instead, since membership is
    additive and a union can only ever keep more. Attribute keys the winner does
    not have are filled from the losers in sorted order: that never overrides
    the winner and it is strictly better than discarding them.

    Three structures, not four: the top-level ``log`` is also keyed by object
    name -- the fourth ``", "``-delimited field of every row -- and is
    deliberately left pointing at the old name. So a renamed object's history
    stays under its old name, and a legacy row whose name holds ``", "`` still
    fails to parse on open, which is the very case the normalization exists to
    prevent. Both were true before this function existed; it neither causes nor
    worsens them. The reason it is not fixed here is that repointing rewrites
    recorded *history* rather than metadata, and that the rows most in need of
    it are exactly the ones ``Log.fromStr`` cannot find the object name in by
    field index -- the shifted fields are why they fail -- so it wants a
    substring reconstruction with its own ambiguity rules, not the field swap
    below. Long form in ``tests/test_contour_name_collision.py``'s module
    docstring.

    (Updates ``series_data`` in place.)

        Params:
            series_data (dict): the series JSON, after ``Series.updateJSON``
            renames (dict): old name -> new name, aggregated over all sections
            collisions (dict): merged name -> sorted source names
    """
    if not renames:
        return

    # merged name -> the sources it takes attributes from, winner first
    order = {}
    for old, new in renames.items():
        order.setdefault(new, [])
    for merged, names in collisions.items():
        if merged not in order:
            continue
        winner = merged if merged in names else names[0]
        order[merged] = [winner] + [n for n in names if n != winner]
    for old, new in sorted(renames.items(), key=lambda kv: str(kv[0])):
        if not order[new]:
            order[new] = [old]

    obj_attrs = series_data.get("obj_attrs")
    if isinstance(obj_attrs, dict):
        for merged, names in sorted(order.items(), key=lambda kv: str(kv[0])):
            merged_attrs = {}
            for name in names:
                source = obj_attrs.get(name)
                if not isinstance(source, dict):
                    continue
                for key, value in source.items():
                    if key not in merged_attrs:
                        merged_attrs[key] = value
            for name in names:
                if name != merged:
                    obj_attrs.pop(name, None)
            if merged_attrs:
                obj_attrs[merged] = merged_attrs

    groups = series_data.get("object_groups")
    if isinstance(groups, dict):
        for group, members in groups.items():
            if not isinstance(members, list):
                continue
            renamed = [renames.get(m, m) for m in members]
            # dedupe, preserving the file's order: two members of one group can
            # merge onto the same name
            seen = set()
            groups[group] = [
                m for m in renamed if not (m in seen or seen.add(m))
            ]

    host_tree = series_data.get("host_tree")
    if isinstance(host_tree, dict):
        rebuilt = {}
        for obj_name, hosts in host_tree.items():
            if not isinstance(hosts, list):
                rebuilt[obj_name] = hosts  # shape this code does not know: keep
                continue
            target = renames.get(obj_name, obj_name)
            merged_hosts = rebuilt.setdefault(target, [])
            for host in hosts:
                host = renames.get(host, host)
                # a merge can make an object its own host; that is a cycle the
                # host tree rejects, so drop it rather than write it out
                if host != target and host not in merged_hosts:
                    merged_hosts.append(host)
        host_tree.clear()
        host_tree.update({k: v for k, v in rebuilt.items() if v})



#: Module-local override, kept for callers that set it directly. Leave it None
#: and the default resolves through `settings_store.default_settings_store()`,
#: which is the one process-wide cache. Setting it can only make isolation
#: tighter, never looser, so it cannot reopen the seam closed below.
_SETTINGS_STORE = None


def _default_settings_store():
    """Resolve the default settings store for a `Series` with none injected.

    Delegates to `settings_store.default_settings_store()` rather than keeping
    a second cache of its own. That matters for more than tidiness: this
    function is what `Series.getOption`/`setOption` fall back on, so while it
    cached separately, `set_default_settings_store()` -- the sanctioned way to
    redirect settings away from the real `QSettings("KHLab", "PyReconstruct")`
    domain -- closed only the store that `constants.getdatetime` uses and left
    every `getOption` call resolving the real one. A caller that redirected
    settings the documented way still got a half-open seam, and the half that
    worked looked like proof that it had worked.

    `Series.getOption` writes the default back when a key is absent, so a
    *read* through the missed half was a write: reading `series.user` stored
    `get_username()` into the real domain, which is how the developer's own
    username was overwritten once already.

    Behavior is unchanged for the shipped application: with no override
    installed the delegate lazily creates the same `QSettingsStore`. The Qt
    import stays deferred (`settings_store` imports `QSettings` inside
    `QSettingsStore._settings`), so resolving the default still pulls in no Qt.
    """
    if _SETTINGS_STORE is not None:
        return _SETTINGS_STORE
    from PyReconstruct.modules.backend.settings_store import (
        default_settings_store
    )
    return default_settings_store()


_PROGRESS_REPORTER_FACTORY = None


def _default_progress_reporter_factory():
    """Lazily resolve and cache the default Qt-backed ProgressReporter factory.

    Imported lazily so that this module does not pull in Qt just to resolve the
    default; behavior for GUI callers is identical to direct getProgbar use. The
    factory is a callable ``(text, cancel) -> ProgressReporter`` (the
    QtProgressReporter class), invoked fresh per operation.
    """
    global _PROGRESS_REPORTER_FACTORY
    if _PROGRESS_REPORTER_FACTORY is None:
        from PyReconstruct.modules.backend.progress import QtProgressReporter
        _PROGRESS_REPORTER_FACTORY = QtProgressReporter
    return _PROGRESS_REPORTER_FACTORY


_NOTIFIER = None


def _default_notifier():
    """Lazily create and cache the default Qt-backed notifier.

    Imported lazily so that this module does not pull in Qt/GUI just to resolve
    the default; behavior for GUI callers is identical to the previous inline
    notify()/QApplication guard.
    """
    global _NOTIFIER
    if _NOTIFIER is None:
        from PyReconstruct.modules.backend.notifier import QtNotifier
        _NOTIFIER = QtNotifier()
    return _NOTIFIER


def _atomicWrite(fp : str, data : bytes):
    """Write bytes to a file atomically.

    Writes to a temp file in the same directory, flushes and fsyncs it, then
    os.replace()s it over the destination so a crash, power loss, or full disk
    mid-write can never leave a truncated file behind.

        Params:
            fp (str): the destination filepath
            data (bytes): the bytes to write
    """
    tmp_fp = fp + ".tmp"
    try:
        with open(tmp_fp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # retry a transiently-locked replace (Windows AV/indexer/sync) so a
        # background save doesn't fail spuriously; real errors still propagate
        from PyReconstruct.modules.backend.func.atomic_io import replace_with_retry
        replace_with_retry(tmp_fp, fp)
    except OSError:
        # best-effort cleanup of the temp file; the destination is untouched
        try:
            if os.path.isfile(tmp_fp):
                os.remove(tmp_fp)
        except OSError:
            pass
        raise


class Series():
    
    qsettings_defaults = default_settings.copy()
    qsettings_series_defaults = default_series_settings.copy()

    def __init__(self, filepath : str, sections : dict, get_series_data=True):
        """Load the series file.

        (This function is not used to open a JSER file.)
        
            Params:
                filepath (str): the filepath for the series JSON file
                sections (dict): section basename for each section
                get_series_data (bool): True if series data should be loaded
        """
        self.filepath = filepath
        self.sections = sections
        self.name = os.path.basename(self.filepath)[:-4]

        ## The series' one trace-id issuer. One per series because uniqueness
        ## is series-global (`trace_id.py`), and it lives HERE rather than on
        ## any store because a store's lifetime is one build: before this,
        ## `Section._rebuildColumnarStore` took its issuer from the OUTGOING
        ## store, and the first build has no outgoing store, so the chain was
        ## never seeded and every trace in every shipped session carried no id
        ## at all. Assigned before anything below can load a section --
        ## `self.data.refresh()` walks every section on the `openJser` fast
        ## path -- and both `openJser` entry paths (the hidden-directory fast
        ## path and the full .jser unpack) construct their Series through this
        ## method, so both are seeded. Ids reach memory only; no byte of any
        ## .jser changes.
        self.trace_id_issuer = TraceIDIssuer()

        with open(filepath, "rb") as f:
            series_data = fast_loads(f.read())

        Series.updateJSON(series_data)

        self.jser_fp = ""
        self.hidden_dir = os.path.dirname(self.filepath)
        self.modified = False

        self.current_section = series_data["current_section"]
        self.src_dir = series_data["src_dir"]
        self.screen_mag = 0  # default value for screen mag (will be calculated when generateView called)
        self.window = series_data["window"]
        self.palette_traces = dict((
            (name, [Trace.fromList(trace) for trace in palette_group])
            for name, palette_group in series_data["palette_traces"].items()
        ))
        self.palette_index = series_data["palette_index"]

        self.ztraces = series_data["ztraces"]
        for name in self.ztraces:
            self.ztraces[name] = Ztrace.fromDict(name, self.ztraces[name])

        self.alignment = series_data["alignment"]
        
        self.object_groups = ObjGroupDict(self, "objects", series_data["object_groups"])
        self.groups_visibility = self.initGroupViz()

        self.ztrace_groups = ObjGroupDict(self, "ztraces", series_data["ztrace_groups"])

        self.obj_attrs = series_data["obj_attrs"]
        self.ztrace_attrs = series_data["ztrace_attrs"]

        self.bc_profile = series_data["current_brightness_contrast_profile"]

        # default settings
        self.modified_ztraces = set()
        self.modified_objects = set()
        self.leave_open = False

        # possible zarr overlay
        self.zarr_overlay_fp = None
        self.zarr_overlay_group = None

        self.options = series_data["options"]

        # possible existing log set
        if "log_set" in series_data:
            self.log_set = LogSet.fromList(series_data["log_set"])
        else:
            self.log_set = LogSet()

        # keep track of relevant overall series data
        self.data = SeriesData(self)
        if get_series_data:
            self.data.refresh()

        # objects for non-GUI users
        self.objects = Objects(self)

        # editors list
        self.editors = set(series_data["editors"])
        if not self.isWelcomeSeries() and not self.editors:
            self.editors = self.getEditorsFromHistory()

        # series code
        self.code = series_data["code"]

        # user-defined columns
        self.user_columns = series_data["user_columns"]

        # host tree
        self.host_tree = HostTree(series_data["host_tree"], self)

        ## Group visibility
        self.groups_visibility = self.initGroupViz()

    def __enter__(self):
        
        return self

    def __exit__(self, exc_type, exc_value, tb):

        self.close()

        return False  # propagate any exception from the with-block
    
    ## OPENING, LOADING, AND MOVING THE JSER FILE
    @staticmethod
    def openJser(fp : str, progress=None, notifier=None):
        """Process the file containing all section and series information.

            Params:
                fp (str): the filepath to the jser
                progress: an optional ProgressReporter factory (callable
                    (text, cancel) -> ProgressReporter); defaults to the
                    Qt-backed reporter. Headless callers may pass
                    NullProgressReporter.
                notifier: an optional Notifier used to ask before folding
                    distinct objects together (see contourNameCollisions);
                    defaults to the Qt-backed notifier, which asks nothing when
                    no GUI is up and the load proceeds as before.
            Returns:
                (Series): the series object created from the jser, or None if
                    the user declined the object merge
        """
        # check for existing hidden folder
        sdir = os.path.dirname(fp)
        sname = os.path.basename(fp)
        sname = sname[:sname.rfind(".")]
        hidden_dir = os.path.join(sdir, f".{sname}")
        ser_filepath = os.path.join(hidden_dir, f"{sname}.ser")
        if os.path.isdir(hidden_dir) and os.path.isfile(ser_filepath):
            # gather sections
            sections = {}
            for f in os.listdir(hidden_dir):
                if "." not in f:
                    continue
                ext = f[f.rfind(".")+1:]
                if ext.isnumeric():
                    snum = int(ext)
                    sections[snum] = f
            series = Series(ser_filepath, sections)
            series.jser_fp = fp
            series.leave_open = True
            return series

        # load json
        try:
            with open(fp, "rb") as f:
                jser_data = fast_loads(f.read())
        except ValueError as e:
            raise SeriesOpenError(
                f"{os.path.basename(fp)} is not a valid series file "
                f"(the file is corrupt or is not JSON)."
            ) from e

        if not isinstance(jser_data, dict):
            raise SeriesOpenError(
                f"{os.path.basename(fp)} is not a valid series file "
                f"(unexpected file structure)."
            )

        # UPDATE FROM OLD JSER FORMATS
        updated_jser_data = {}
        sections_dict = {}
        if "sections" not in jser_data and "series" not in jser_data:
            # gather the sections and section numbers
            for key in jser_data:
                # key could just be the extension OR the name + extension
                if "." in key:
                    ext = key[key.rfind(".")+1:]
                else:
                    ext = key
                # check if section or series data
                if ext.isnumeric():
                    snum = int(ext)
                    sections_dict[snum] = jser_data[key]
                else:
                    updated_jser_data["series"] = jser_data[key]
            if not sections_dict or "series" not in updated_jser_data:
                raise SeriesOpenError(
                    f"{os.path.basename(fp)} is not a valid series file "
                    f"(no series or section data found)."
                )
            # organize the sections in a list
            sections_list = [None] * (max(sections_dict.keys())+1)
            for snum, sdata in sections_dict.items():
                sections_list[snum] = sdata
            updated_jser_data["sections"] = sections_list
            # replace data
            jser_data = updated_jser_data

        # validate the overall structure before extracting anything
        if (
            not isinstance(jser_data.get("series"), dict) or
            not isinstance(jser_data.get("sections"), list) or
            not any(s is not None for s in jser_data["sections"])
        ):
            raise SeriesOpenError(
                f"{os.path.basename(fp)} is not a valid series file "
                f"(missing series or section data)."
            )

        # UPDATE TO INCLUDE A LOG
        if "log" not in jser_data:
            jser_data["log"] = "Date, Time, User, Obj, Sections, Event"

        # Distinct objects about to become one object. Asked BEFORE the hidden
        # directory exists, so declining leaves the file exactly as it was.
        collisions = contourNameCollisions(jser_data)
        if collisions:
            asker = notifier if notifier is not None else _default_notifier()
            if asker.confirm(contourMergeWarning(collisions)) is False:
                return None

        # creating loading bar
        factory = progress if progress is not None else _default_progress_reporter_factory()
        reporter = factory(text="Opening series...")
        progress = 0
        final_value = 0
        for sdata in jser_data["sections"]:
            if sdata: final_value += 1
        final_value *= 2  # for loading section data
        final_value += 2  # unpacking series and log

        # create the hidden directory
        hidden_dir = createHiddenDir(sdir, sname)

        # The .ser file is written LAST as the completion sentinel: both
        # recovery scans (the fast path above and the GUI's unsaved-work
        # prompt) require it, so a cancelled or crashed open can never leave
        # a partial hidden dir that is later mistaken for unsaved work.
        # On any cancel or exception, remove the partial hidden dir entirely.
        try:
            # extract JSON section data
            sections = {}
            renames = {}
            for snum, section_data in enumerate(jser_data["sections"]):
                # check for empty section, skip if so
                if section_data is None:
                    continue

                filename = sname + "." + str(snum)
                section_fp = os.path.join(hidden_dir, filename)

                # update any missing attributes; collect the contour renames so
                # the series data can follow them below
                #
                # `stored_ids` is the trace ids the file's own keyed rows carry,
                # and re-attaching them is not an optimization -- it is the
                # difference between a persisted id existing and not. The rows
                # the object model reads come from THIS hidden copy, never from
                # the `.jser` directly, and `updateJSON` converts a keyed row to
                # the positional shape. Without the line below the id is decoded
                # here and then written out of existence one statement later, so
                # `Section.__init__` has nothing to adopt no matter what it
                # does. Measured on a hand-keyed fixture before it was added:
                # every row reached the store carrying a derived id and not the
                # one the file named.
                #
                # Empty, and therefore a no-op, for every positional file --
                # which is every file any shipped build has ever written.
                stored_ids = {}
                renames.update(Section.updateJSON(
                    section_data, snum, stored_ids=stored_ids
                ))
                if stored_ids:
                    Section.reattachTraceIDs(section_data, stored_ids)

                # Every section locks on open, and the stored value is ignored
                # on purpose -- this is the intended behavior, not an oversight,
                # so please do not "fix" it. Opening a file protects its
                # alignments; honoring a stored False would remove that
                # protection for the one case it exists to cover. The asymmetry
                # with the hidden-dir fast path above is deliberate in the same
                # way: that path resumes a live working directory rather than
                # opening a file, so re-locking there would silently discard a
                # lock the user cleared mid-session. Pinned by
                # tests/test_bc_profiles_and_section_lock.py, finding 2, which
                # covers both halves.
                section_data["align_locked"] = True

                # gather the section numbers and section filenames
                sections[snum] = filename

                with open(section_fp, "wb") as f:
                    f.write(fast_dumps(section_data))

                if reporter.was_canceled():
                    shutil.rmtree(hidden_dir, ignore_errors=True)
                    return None
                progress += 1
                reporter.set_progress(progress/final_value * 100)

            # Extract the existing log. Copied through byte for byte: the
            # contour renames collected above are NOT applied to its object-name
            # field, deliberately -- see `applyContourRenames` for why.
            log_str = jser_data["log"]
            existing_log_fp = os.path.join(hidden_dir, "existing_log.csv")
            with open(existing_log_fp, "w", encoding="utf-8") as f:
                f.write(log_str)
            if reporter.was_canceled():
                shutil.rmtree(hidden_dir, ignore_errors=True)
                return None
            progress += 1
            reporter.set_progress(progress/final_value * 100)

            # extract JSON series data (LAST: the .ser is the completion sentinel)
            series_data = jser_data["series"]
            # add empty log_set for opening/saving purposes
            series_data["log_set"] = []
            Series.updateJSON(series_data)
            # Carry the contour renames above into everything the series keys by
            # object name except the log, above. Runs after updateJSON, which is
            # what folds the legacy curation / last_user / 3D_modes maps into
            # obj_attrs.
            applyContourRenames(series_data, renames, collisions)
            series_fp = os.path.join(hidden_dir, sname + ".ser")
            with open(series_fp, "wb") as f:
                f.write(fast_dumps(series_data))
            if reporter.was_canceled():
                shutil.rmtree(hidden_dir, ignore_errors=True)
                return None
            progress += 1
            reporter.set_progress(progress/final_value * 100)

            # create the series
            series = Series(series_fp, sections, get_series_data=False)
            series.jser_fp = fp

            # gather the series data
            for snum, section in series.enumerateSections(show_progress=False):
                series.data.updateSection(section, update_traces=True, log_events=False)
                if reporter.was_canceled():
                    shutil.rmtree(hidden_dir, ignore_errors=True)
                    return None
                progress += 1
                reporter.set_progress(progress/final_value * 100)

        except BaseException:
            shutil.rmtree(hidden_dir, ignore_errors=True)
            raise

        return series

    def saveJser(self, save_fp : str = None, close : bool = False):
        """Save the jser file.

        The section set written is `self.sections`, the series' index, and not
        the hidden directory's listing. The two can disagree, and when they do
        the index is right: a numbered file with no entry in `self.sections` is
        not part of the series, and the writer used to put it back.

        Deleting a section made exactly that disagreement, through ordinary GUI
        use and with no error anywhere. `deleteSections` removes the file and the
        index entry, but the field is still holding the deleted `Section` object
        (`changeSection` parks it in `field.b_section` via `swapABsections`), and
        `MainWindow.saveAllData` writes `b_section`'s file back into the hidden
        dir on every save, `recreateTables` included, inside the delete action
        itself. `Section.save` now declines to rewrite a section the series no
        longer has, so the stale file is not usually created in the first place;
        this loop is the part that has to hold whatever the hidden dir contains.
        Reading from the listing had three outcomes, all of them bad:

          * an interior section came back on the next open, with the z-trace
            points that crossed it gone (`deleteSections` repointed the z-traces)
            and a "Delete section" line in the log that did not stick
          * the highest-numbered section raised `IndexError` out of
            `jser_data["sections"][int(ext)] = ...`, because the stale file's
            extension was past the end of a list sized from `self.sections`.
            Only `OSError` was caught, so the save crashed, the progress dialog
            was left on screen, and, since the stale file stayed where it was,
            **every later save failed the same way**
          * a section file missing from the hidden dir was written as `null`,
            the save reported success, and the atomic write replaced the last
            good .jser with one short a section

        Both disagreements now refuse, before anything is written, rather than
        write a .jser that is missing a section. A missing or unreadable section
        file means the data is already gone from the working copy that was being
        edited, so no save can preserve it, and refusing costs nothing that
        proceeding would have saved: every section file that does exist stays in
        the hidden dir and is recovered on the next open, and the previous .jser
        still holds the missing section, which is a real recovery route that a
        successful save would have destroyed. Proceeding loses a section for
        good; refusing loses an afternoon at worst, and only if the user gives up
        on the recovery route.

            Params:
                save_fp (str): the optional override filepath to save the jser file
                close (bool): True if series should be closed after saving
            Raises:
                SeriesSaveError: if the series cannot be written without losing a
                    section. Nothing is written, so the existing .jser is still
                    the last good copy.
        """
        self.save()

        jser_fp = self.jser_fp if not save_fp else save_fp

        # Pre-flight, before the reporter exists and before a single byte is
        # written: cheap stats, and a refusal here leaves no dialog and no
        # half-written document.
        snums = sorted(self.sections)
        if not snums:
            self._refuseSave(
                jser_fp,
                "the series has no sections. A .jser with no sections cannot be "
                "reopened, so writing one would replace the existing file with "
                "an unopenable one."
            )

        missing = [
            snum for snum in snums
            if not os.path.isfile(os.path.join(self.hidden_dir, self.sections[snum]))
        ]
        if missing:
            self._refuseSave(
                jser_fp,
                f"the working file for section(s) {missing} is gone from\n"
                f"{self.hidden_dir}\n\n"
                "Saving now would write a series without them. The sections are "
                "still in the existing file, so copy it somewhere safe before "
                "doing anything else."
            )

        jser_data = {}

        reporter = self._progressReporterFactory()(
            text="Saving series...",
            cancel=False
        )
        # finish() in a finally: an exception used to leave the progress dialog
        # on screen with no way to dismiss it.
        try:
            progress = 0
            final_value = len(snums) + 2  # the sections, the .ser, the log

            # Sized from the index, and every index below comes from the same
            # dict, so a section number can no longer be out of range.
            jser_data["sections"] = [None] * (snums[-1] + 1)
            jser_data["series"] = {}
            jser_data["log"] = ""

            for snum in snums:
                fp = os.path.join(self.hidden_dir, self.sections[snum])
                try:
                    with open(fp, "rb") as f:
                        jser_data["sections"][snum] = fast_loads(f.read())
                except (OSError, ValueError) as e:
                    # Same reasoning as a missing file: refuse rather than write
                    # the section out as null.
                    self._refuseSave(
                        jser_fp,
                        f"the working file for section {snum} could not be read "
                        f"({e}). Saving now would write a series without it."
                    )

                progress += 1
                reporter.set_progress(progress/final_value * 100)

            # the series file itself (self.filepath is the .ser in the hidden dir)
            with open(self.filepath, "rb") as f:
                filedata = fast_loads(f.read())
            # `log_set` is the hidden dir's working accumulator, not part of the
            # .jser: its rows are flattened into the "log" text a few lines down
            # and `openJser` overwrites the key with [] on the way back in, so a
            # copy in the series dict would be dead weight at best. Removed
            # unconditionally. It used to be `if filedata.get("log_set")`, a
            # truthiness test standing in for an existence test, which skipped
            # the removal for a present-but-empty log set and wrote `"log_set":
            # []` into the file. No content was ever lost -- the removal is not
            # what carries the rows out -- but the key's presence tracked
            # session activity rather than series content, so save, reopen, save
            # was not byte-idempotent for any series that logged an event.
            filedata.pop("log_set", None)
            # add the log_set string to the log
            log_set_str = str(self.log_set)
            if log_set_str:
                jser_data["log"] += "\n" + log_set_str
            # save the series
            jser_data["series"] = filedata
            progress += 1
            reporter.set_progress(progress/final_value * 100)

            # The series history: this session's entries appended to everything
            # the file already carried, written as one string under "log".
            #
            # The .jser audit filed this as "one unbounded escaped string ...
            # growing monotonically until exported". It does grow monotonically,
            # and that is DELIBERATELY LEFT AS IS, for two measured reasons.
            #
            # It is slow. On a real 276-section series, one simulated hour of
            # dense tracing (600 edits, the same workload as the undo-stack
            # measurement) adds 25.0-46.3 KB, the range spanning full LogSet
            # coalescing to none. Per hour that is ~1/85th of what the undo
            # stacks take in memory over the same hour, and the dataset's own
            # four months of real work by a real user amount to 60,379 B -- one
            # eighth of one percent of the 51 MB file.
            #
            # And it is already rotatable. LogSet.exportLogHistory offloads
            # entries older than N days to an external CSV and rewrites
            # existing_log.csv with the remainder; the GUI exposes it as
            # MainWindow.exportLog. So the audit's own "until exported" names a
            # feature, not a gap.
            #
            # Truncating it here instead would discard user history, which is
            # the one thing this string must not do: LogSet is the series-level
            # record and a superset of the per-trace history field. If the rate
            # ever needs revisiting, measure it -- do not cap it silently.
            # See measurements/log_string_growth.py in the notes repo.
            existing_log_fp = os.path.join(self.hidden_dir, "existing_log.csv")
            if os.path.isfile(existing_log_fp):
                with open(existing_log_fp, "r", encoding="utf-8", errors="replace") as f:
                    existing_log = ""
                    for line in f.readlines():
                        if line.strip():
                            existing_log += line
                jser_data["log"] = existing_log + jser_data["log"]
            progress += 1
            reporter.set_progress(progress/final_value * 100)

            # Canonical series key order. The .ser in the hidden dir is written from
            # Series.getDict (already canonical), so this only matters for a series
            # object that reached this point by some other route.
            canon_keys_inplace(jser_data["series"], SERIES_KEYS)

            # Minified, with canonical ordering applied. Ordering is what makes two
            # saves of the same content byte-identical and it costs nothing; the
            # structural pretty printer costs +11% wall time and ~27% more transient
            # memory in this call (an extra copy of the document: it builds a list of
            # row fragments and joins it), so it is opt-in via PYRECON_JSER_PRETTY=1
            # for when a human is going to read the diff.
            save_bytes = dumps_jser(jser_data)

            try:
                # atomic: the previous .jser stays intact until the new one is complete
                _atomicWrite(jser_fp, save_bytes)
            except OSError as e:
                self._surfaceSaveError(jser_fp, e)
                raise

            if close:
                self.close()
        finally:
            reporter.finish()

    def _refuseSave(self, jser_fp : str, reason : str):
        """Tell the user why the save is not happening, then raise.

        Mirrors the OSError path in saveJser: the same "existing file was left
        unchanged" wording, through the same injectable notifier, and then the
        exception, so the caller does not go on to mark the series saved.

            Params:
                jser_fp (str): the filepath that was not written
                reason (str): what stopped the save, in the user's terms
            Raises:
                SeriesSaveError: always
        """
        err = SeriesSaveError(reason)
        self._surfaceSaveError(jser_fp, err)
        raise err

    def move(self, new_jser_fp : str, section : Section = None, b_section : Section = None):
        """Move/rename the series to its jser filepath.
        
            Params:
                new_jser_fp (str): the new location for the series
                section (Section): the section file being used (in GUI)
                b_section (Section): the secondary section file being used (in GUI)
            """
        
        ## Move/Rename hidden directory
        old_name = self.name
        new_name = os.path.basename(new_jser_fp)
        new_name = new_name[:new_name.rfind(".")]

        old_hidden_dir = os.path.dirname(self.filepath)

        new_hidden_dir = os.path.join(
            os.path.dirname(new_jser_fp),
            "." + new_name
        )

        # Save-As onto the current path: the hidden dir is already in place --
        # moving it onto itself would fail (or nest it), so just refresh paths
        same_dir = (
            os.path.isdir(new_hidden_dir) and
            os.path.samefile(old_hidden_dir, new_hidden_dir)
        )

        if not same_dir:
            # clear any stale hidden dir at the destination: shutil.move would
            # otherwise nest the old dir inside it, orphaning every filepath
            if os.path.isdir(new_hidden_dir):
                shutil.rmtree(new_hidden_dir)
            shutil.move(old_hidden_dir, new_hidden_dir)

        ## Manually hide dir if Windows
        if os.name == "nt":
            import subprocess
            subprocess.check_call(["attrib", "+H", new_hidden_dir])

        ## Rename all files
        for f in os.listdir(new_hidden_dir):
            if old_name in f:
                new_f = f.replace(old_name, new_name)
                if new_f != f:
                    os.rename(
                        os.path.join(new_hidden_dir, f),
                        os.path.join(new_hidden_dir, new_f)
                    )
        
        ## Rename series
        self.rename(new_name)

        ## Update filepaths in series and section files
        self.jser_fp = new_jser_fp
        self.hidden_dir = new_hidden_dir
        
        self.filepath = os.path.join(
            new_hidden_dir,
            os.path.basename(self.filepath).replace(old_name, new_name)
        )

        ## Update loaded sections in GUI
        if section:
            section.filepath = os.path.join(
                new_hidden_dir,
                os.path.basename(section.filepath).replace(old_name, new_name)
            )
            
        if b_section:
            b_section.filepath = os.path.join(
                new_hidden_dir,
                os.path.basename(b_section.filepath).replace(old_name, new_name)
            )
    
    def close(self):
        """Clear the hidden directory of the series."""
        
        if self.isWelcomeSeries() or self.leave_open:
            return
        
        if os.path.isdir(self.hidden_dir):
            
            for f in os.listdir(self.hidden_dir):
                os.remove(os.path.join(self.hidden_dir, f))
                
            os.rmdir(self.hidden_dir)
    
    @staticmethod
    def updateJSON(series_data : dict):
        """Add missing attributes to the series JSON.

        (Updates the dictionary in place)
        
            Params:
                series_data (dict): the JSON data to update
        """
        empty_series = Series.getEmptyDict()
        for key in empty_series:
            if key not in series_data:
                series_data[key] = empty_series[key]
        for key in empty_series["options"]:
            if key not in series_data["options"]:
                series_data["options"][key] = empty_series["options"][key]
        for key in list(series_data["options"].keys()):
            if key not in empty_series["options"]:
                del series_data["options"][key]
        
        # check for backup_dir key
        if "backup_dir" in series_data:
            del series_data["backup_dir"]
        
        # check the ztraces
        if type(series_data["ztraces"]) is list:
            ztraces_dict = {}
            for ztrace in series_data["ztraces"]:
                # check for missing color attribute
                if "color" not in ztrace:
                    ztrace["color"] = (255, 255, 0)
                # convert to dictionary format
                name = ztrace["name"]
                ztraces_dict[name] = {}
                del(ztrace["name"])
                ztraces_dict[name] = ztrace
            series_data["ztraces"] = ztraces_dict
        
        # check the traces (convert dicts to lists) if old format of trace palette (single trace palette)
        if type(series_data["palette_traces"]) is list:
            for i, trace in enumerate(series_data["palette_traces"]):
                if type(trace) is dict:
                    trace = [
                        trace["name"],
                        trace["x"],
                        trace["y"],
                        trace["color"],
                        trace["closed"],
                        trace["negative"],
                        trace["hidden"],
                        trace["mode"],
                        trace["tags"],
                    ]
                    series_data["palette_traces"][i] = trace
                # remove history from trace if it exists
                elif len(trace) == 10:
                    trace.pop()
                # check for trace mode
                if type(trace[7]) is not list:
                    trace[7] = ["none", "none"]

        # check for palette reformatting
        if "current_trace" in series_data:
            del(series_data["current_trace"])
            series_data["palette_traces"] = {"palette1": series_data["palette_traces"]}
            series_data["palette_index"] = ["palette1", 0]
        
        # check the window
        window = series_data["window"]
        if window[2] == 0:  # width
            window[2] = 1
        if window[3] == 0:  # height
            window[3] == 1
        
        # check for separate obj attrs
        if "obj_attrs" not in series_data:
            series_data["obj_attrs"] = {}
        obj_attrs = series_data["obj_attrs"]
        if "object_3D_modes" in series_data:
            for obj_name, modes in series_data["object_3D_modes"].items():
                if obj_name not in obj_attrs:
                    obj_attrs[obj_name] = {}
                obj_attrs[obj_name]["3D_modes"] = modes
        if "last_user" in series_data:
            for obj_name, last_user in series_data["last_user"].items():
                if obj_name not in obj_attrs:
                    obj_attrs[obj_name] = {}
                obj_attrs[obj_name]["last_user"] = last_user
        if "curation" in series_data:
            for obj_name, curation in series_data["curation"].items():
                if obj_name not in obj_attrs:
                    obj_attrs[obj_name] = {}
                if "curation" not in obj_attrs[obj_name]:  # do not overwrite existing curation
                    obj_attrs[obj_name]["curation"] = curation
        
        # check for brightnes_contrast profile
        if "current_brightness_contrast_profile" not in series_data:
            series_data["current_brightness_contrast_profile"] = "default"
        
        # check for splitting 3D modes
        for name, data in series_data["obj_attrs"].items():
            if "3D_modes" in data:
                data["3D_mode"] = data["3D_modes"][0]
                data["3D_opacity"] = data["3D_modes"][1]
                del(data["3D_modes"])
        
        # check for editors list
        if "editors" not in series_data:
            series_data["editors"] = []

        # schema_version: TOLERATED WHEN ABSENT, AND ABSENT IS THE COMMON CASE.
        #
        # Stamped rather than read, and the difference matters. Everything above
        # this line IS the migration to the shape this build understands, so the
        # value written here is a true statement about the dict that leaves this
        # function whatever the file claimed -- including a file that claimed
        # nothing, which is every file written before this key existed and,
        # importantly, every file whose last writer was an older build. An older
        # build rebuilds the series object from its own model on save
        # (`docs/JSER_FORMAT.md` divergence 1) and its `Series.getDict` has never
        # heard of this key, so it deletes the field and leaves every row it
        # wrote untouched. Measured against the shipped v1.21.0 reader and pinned
        # in `tests/test_jser_schema_version.py`.
        #
        # The consequence is the reason nothing below reads it: absence is not
        # evidence of an old document, so ABSENCE CANNOT BE DISPATCHED ON, and
        # neither can presence -- row shape is per row and one document may
        # legitimately hold both shapes. Per-row shape detection stays
        # authoritative. See `JSER_SCHEMA_VERSION` for the whole argument.
        #
        # Not added to `getEmptyDict` on purpose, which would have got the
        # absent case for free through the back-fill loop at the top: the
        # back-fill preserves a value that is already there, so a file carrying
        # some other build's number would keep it in memory and this build's
        # in-memory document would then be labelled with a claim that is not
        # about it.
        series_data["schema_version"] = JSER_SCHEMA_VERSION

        # Canonical key order, last, once every migration above has finished
        # adding and deleting keys. Both this dict and its options bag back-fill
        # missing keys at the tail, so provenance leaked into the byte layout.
        # The options bag has no independent writer order -- it is passed through
        # by reference from here to Series.getDict -- so the empty-dict template
        # defines its canonical order. Rebuilt in place: callers keep references.
        canon_keys_inplace(series_data["options"], tuple(empty_series["options"]))
        canon_keys_inplace(series_data, SERIES_KEYS)

    def getDict(self) -> dict:
        """Convert series object into a dictionary.

        Emits `schema_version` as the first key, and **that field is a hint for
        whoever reads the file next, never a dispatch key for a reader.** Two
        independent reasons, both of which a caller has to know before trusting
        it (the full argument is on `JSER_SCHEMA_VERSION`):

        - **An older build deletes it.** The series object is rebuilt from the
          in-memory model on every save -- `docs/JSER_FORMAT.md` divergence 1,
          "sections pass through opaquely; the series object does not" -- and no
          build before this one writes the key. So a build older than this one
          opens a file carrying `schema_version`, ignores it, and silently drops
          it on the first save **while leaving every row it wrote exactly as it
          found them**. Measured against the shipped v1.21.0 reader and pinned as
          a test expectation in `tests/test_jser_schema_version.py`. A file with
          no `schema_version` therefore says nothing about its age or its shape.
        - **It could not describe the rows anyway.** Row shape is per row: every
          shipped reader back to v1.19.0 accepts a positional trace row and a
          keyed one in the same contour, so one document can hold both. Per-row
          shape detection stays authoritative.

        What it is good for is the part that survives: an external consumer -- a
        converter, an archive checker, a script reading `.jser` without
        PyReconstruct -- gets a positive statement of the schema the last writer
        intended, when there is one. Present means "written by a build that
        stamps this". Absent means "no claim", not "old".

            Returns:
                (dict): all of the compiled section data
        """
        d = {}

        d["schema_version"] = JSER_SCHEMA_VERSION

        d["current_section"] = self.current_section
        d["src_dir"] = self.src_dir
        d["window"] = self.window
        
        d["palette_traces"] = dict((
            (name, [trace.getList() for trace in palette_group])
            for name, palette_group in self.palette_traces.items()
        ))
        d["palette_index"] = self.palette_index

        d["ztraces"] = {}
        for name in self.ztraces:
            d["ztraces"][name] = self.ztraces[name].getDict()
            
        d["alignment"] = self.alignment
        d["object_groups"] = self.object_groups.getGroupDict()
        d["ztrace_groups"] = self.ztrace_groups.getGroupDict()

        d["obj_attrs"] = self.obj_attrs
        d["ztrace_attrs"] = self.ztrace_attrs

        d["current_brightness_contrast_profile"] = self.bc_profile

        # ADDED SINCE JAN 25TH
        d["options"] = self.options

        d["log_set"] = self.log_set.getList()

        # editors is a set in memory: sort it so identical content serializes to
        # identical bytes across processes (canonical ordering)
        d["editors"] = sorted(self.editors, key=str)
        d["code"] = self.code
        d["user_columns"] = self.user_columns
        d["host_tree"] = self.host_tree.getDict()

        return d
    
    @staticmethod
    def getEmptyDict() -> dict:
        """Get an empty dictionary for a series object.
        
            Returns:
                (dict): the empty series dictionary
        """
        series_data = {}
        
        # series_data["sections"] = {}  # section_number : section_filename
        series_data["current_section"] = 0  # last section left off
        series_data["src_dir"] = ""  # the directory of the images
        series_data["window"] = [0, 0, 1, 1] # x, y, w, h of reconstruct window in field coordinates
        series_data["palette_traces"] = {
            "palette1": [t.getList(include_name=True) for t in Series.getDefaultPaletteTraces()]
        }
        series_data["palette_index"] = ["palette1", 0]
        series_data["ztraces"] = []
        series_data["alignment"] = "default"
        series_data["object_groups"] = {}
        series_data["ztrace_groups"] = {}
        series_data["current_brightness_contrast_profile"] = "default"

        # ADDED SINCE JAN 25TH

        series_data["options"] = {
            # table columns (default display)
            # note: "static" columns are *always* displayed and are not included here.
            # See gui/table/trace.py for static cols
            # MFO = modifiable from options
            "object_columns": list({  # MFO
                
                "Range"        : True,
                "Count"        : False,
                "Flat area"    : False,
                "Volume"       : False,
                "Radius"       : False,
                "Host"         : True,
                "Superhosts"   : False,
                "Groups"       : True,
                "Trace tags"   : False,
                "Locked"       : True,
                "Last user"    : True,
                "Curate"         : False,
                "Alignment"      : False,
                "Comment"        : True,
                "Configuration"  : False
                
            }.items()),
            
            "trace_columns": list({  # MFO
                
                "Index"        : False,
                "Tags"         : True,
                "Hidden"       : True,
                "Closed"       : True,
                "Length"       : True,
                "Area"         : True,
                "Radius"       : True,
                "Centroid"     : False,
                "Feret"        : False,
                
            }.items()),
            
            "flag_columns": list({  # MFO
                
                "Section"      : True,
                "Color"        : True,
                "Flag"         : True,
                "Resolved"     : False,
                "Last Comment" : True
                
            }.items()),
            
            "section_columns": list({  # MFO
                
                "Thickness"    : True,
                "Locked"       : True,
                "Brightness"   : True,
                "Contrast"     : True,
                "Image Source" : True
                
            }.items()),
            
            "ztrace_columns": list({  # MFO
                
                "Start"        : True,
                "End"          : True,
                "Distance"     : True,
                "Groups"       : True,
                "Alignment"    : True
                
            }.items()),

            # distances
            "small_dist"       : 0.01,  # MFO
            "med_dist"         : 0.1,  # MFO
            "big_dist"         : 1,  # MFO

            # Last-used autosegmentation job parameters, kept so the train,
            # predict and segment dialogs open on the values the previous run
            # used. Audited twice for "stale parameters are never pruned" and
            # left alone both times, so the reasoning is recorded here rather
            # than re-derived a third time, and pinned by
            # tests/test_autoseg_options_retained.py:
            #
            #  - Reuse is the feature, not the defect. The three dialogs read
            #    this bag only to prefill their fields.
            #  - It cannot grow without bound. The three writers set a fixed
            #    17 keys between them, all scalars or short lists, so a fully
            #    populated bag is about 400 bytes and stays that size.
            #  - Nothing writes it today. Every caller has been commented out
            #    since 2024 ("AUTOSEG FUNCTIONS TEMPORARILY REMOVED" in
            #    gui/main/main_window.py), so a current session adds nothing.
            #
            # Pruning it would therefore save a few hundred bytes in old files
            # and throw away the parameters the dialogs want back on the day
            # autosegmentation is restored.
            #
            # One note for whoever restores it: the commented callers mutate
            # `series.options["autoseg"]` in place rather than going through
            # `setOption`. That only works while `getOption` hands back the
            # stored dict itself, which is exactly the aliasing the copy-on-read
            # work is closing, so restore it with a `setOption` call.
            "autoseg"          : {},

        }

        series_data["obj_attrs"] = {}
        series_data["ztrace_attrs"] = {}

        series_data["editors"] = []
        series_data["code"] = ""
        series_data["user_columns"] = {}
        series_data["host_tree"] = {}

        return series_data
    
    @staticmethod
    def new(image_locations : list, series_name : str, mag : float, thickness : float):
        """Create a new blank series.
        
            Params:
                image_locations (list): the paths for each image
                series_name (str): user-entered series name
                mag (float): the microns per pixel for the series
                thickness (float): the section thickness
            Returns:
                (Series): the newly created series object
        """
        try:
            
            wdir = os.path.dirname(image_locations[0])
            
            if "zarr" in wdir:  # create series next to zarr if necessary
                
                src_dir = wdir[:wdir.rfind("zarr") + len("zarr")]
                wdir = os.path.dirname(src_dir)
                
            else:
                
                src_dir = wdir
                
            hidden_dir = createHiddenDir(wdir, series_name)
            
        except PermissionError:
            
            print(
                "Series cannot be created adjacent to images due "
                "to user not having proper permissions. Creating "
                "in home folder instead."
            )
            
            if os.name == "nt":
                
                wdir = os.environ.get("HOMEPATH")
                
            else:
                
                wdir = os.environ.get("HOME")
                
            hidden_dir = createHiddenDir(wdir, series_name)

        series_data = Series.getEmptyDict()
        series_data["src_dir"] = src_dir  # img dir
        sections = {}

        for i, _ in enumerate(image_locations):
            sections[i] = series_name + "." + str(i)

        series_fp = os.path.join(hidden_dir, series_name + ".ser")
        
        with open(series_fp, "w") as series_file:
            series_file.write(json.dumps(series_data, indent=2))
        
        ## Create section files (.number files)
        for i, img in enumerate(image_locations):
            Section.new(series_name, i, img, mag, thickness, hidden_dir)

        ## Create empty existing_log.csv file
        existing_log_path = os.path.join(hidden_dir, "existing_log.csv")
        with open(existing_log_path, "w", encoding="utf-8") as f:
            f.write("Date, Time, User, Obj, Sections, Event")

        ## Create series object
        series = Series(series_fp, sections)
        
        # save the jser file
        # series.jser_fp = os.path.join(
        #     wdir,
        #     f"{series_name}.jser"
        # )
        # series.saveJser()

        ## Create initial log
        series.addLog(None, None, "Create series")
        
        return series
    
    def isWelcomeSeries(self) -> bool:
        """Return True if self is the welcome series.
        
            Returns:
                (bool): True if this series is the wolcome series
        """
        try:
            if os.path.samefile(self.filepath, os.path.join(welcome_series_dir, "welcome.ser")):
                return True
            else:
                return False
            
        except FileNotFoundError:
            return False
        
    def save(self):
        """Save file into json."""
        if self.isWelcomeSeries():
            return

        d = self.getDict()
        try:
            # internal hidden working file -- write compact bytes atomically
            _atomicWrite(self.filepath, fast_dumps(d))
        except OSError as e:
            self._surfaceSaveError(self.filepath, e)
            raise

    def getwdir(self) -> str:
        """Get the working directory of the series.
        
            Returns:
                (str): the directory containing the series
        """
        return os.path.dirname(self.filepath)
    
    def loadSection(self, section_num : int) -> Section:
        """Load a section object.
        
            Params:
                section_num (int): the section number
            Returns:
                (Section): the section
        """
        section = Section(section_num, self)
        return section
    
    def enumerateSections(self, show_progress : bool = True, message : str = "Loading series data...", series_states=None, breakable=True, section_numbers=None):
        """Allow iteration through the sections.

        Proper use in a for loop: for snum, section in series.enumerateSections():

            Params:
                show_progress (bool): True if progress should be displayed
                message (str): the message to display by the progress bar
                series_states (dict): section number : SectionStates object (use with GUI for undo/redo)
                breakable (bool): True if sereis state is breakable
                section_numbers (iterable): if given, only iterate these section
                    numbers (used to avoid loading every section for operations
                    that only touch a few objects)
            Returns:
                (SeriesIterator): an iterable object for for loops
        """
        return SeriesIterator(self, show_progress, message, series_states, breakable, section_numbers)

    def getObjectSections(self, obj_names) -> set:
        """Return the set of section numbers that contain any of the objects.

        Uses the in-memory object index (data["objects"][name].traces is keyed
        by section number) so callers can restrict a series-wide pass to only
        the sections that actually contain the targeted objects.

            Params:
                obj_names (iterable): the object names to look up
            Returns:
                (set): the section numbers containing any of the objects
        """
        snums = set()
        for name in obj_names:
            obj_data = self.data["objects"].get(name)
            if obj_data:
                snums.update(obj_data.traces.keys())
        return snums

    def _forEachObjectSection(self, obj_names, message, edit, series_states=None):
        """Run an edit on every section a set of objects appears on.

        The loop the bulk object operations all need: visit only the sections
        holding the objects (never the whole series), let the caller change
        what it likes, and save the section if and only if it changed. Seven
        of them wrote this out by hand, which is how `hideAllTraces` came to
        be missing its `self.modified = True` for a while.

        The `edit` callback owns everything section-specific, including
        deciding whether anything changed -- returning a falsy value skips the
        save, exactly as the hand-written `if traces:`/`if modified:` guards
        did. Logging and `self.modified` stay with the public methods, because
        they vary (per-object vs series-wide, `log_event`-gated or not) and
        because several of them log before the loop rather than after.

            Params:
                obj_names (list): the objects the operation applies to
                message (str): the progress bar message
                edit (callable): called with each Section; returns True if
                    that section was modified and should be saved
                series_states (dict): optional dict for GUI undo states
        """
        for snum, section in self.enumerateSections(
            message=message,
            series_states=series_states,
            section_numbers=self.getObjectSections(obj_names)
        ):
            if edit(section):
                section.save()

    def remapStoredAlignments(self, alignment_dict : dict):
        """Follow renames and clear deletes in stored alignment attributes.

        Objects and z-traces may pin themselves to a named alignment. Renaming
        or deleting that alignment used to leave the attribute naming something
        that no longer existed anywhere in the series, because the tform rewrite
        in ``modifyAlignments`` only ever touched the sections and the
        series-wide current alignment.

        A name that survives is left alone. A name that became exactly one new
        name is followed, which is what preserves the intent across a rename:
        clearing instead would silently drop a z-trace back to the series
        alignment while the alignment it asked for still existed under a new
        name. A name that was deleted, or that ambiguously fed several new
        names, is cleared, since there is no honest single answer.

        A name that never existed is cleared too, so a series already carrying a
        dangling attribute from an older save is repaired by any alignment edit.

            Params:
                alignment_dict (dict): as passed to modifyAlignments, mapping
                    each resulting alignment name to the old name it comes from
                    (None for a deletion)
        """
        surviving = {
            new_a for new_a, old_a in alignment_dict.items() if old_a is not None
        }
        for attrs, is_ztrace in ((self.obj_attrs, False), (self.ztrace_attrs, True)):
            for name in list(attrs.keys()):
                stored = attrs.get(name, {}).get("alignment")
                if stored is None or stored in surviving:
                    continue
                renamed_to = [
                    new_a for new_a, old_a in alignment_dict.items()
                    if old_a == stored and new_a in surviving
                ]
                self.setAttr(
                    name,
                    "alignment",
                    renamed_to[0] if len(renamed_to) == 1 else None,
                    ztrace=is_ztrace,
                )

    def modifyAlignments(self, alignment_dict : dict, series_states=None, log_event=True):
        """Modify the series's alignment.

        Accepts input from dialog. Note: Do not use this method outside of
        the user interface.
        
            Params:
                alignment_dict (dict): returned from the alignment dialog
                series_states (dict): optional dict of undo states for GUI
                log_event (bool): True if event should be logged
        """
        # change the current alignment if necessary
        if self.alignment != "no-alignment" and alignment_dict[self.alignment] is None:
            self.alignment = "no-alignment"

        # and carry the per-object and per-ztrace alignment attributes across,
        # or they keep naming an alignment this rewrite is about to remove
        self.remapStoredAlignments(alignment_dict)

        for snum, section in self.enumerateSections(
            message="Modifying alignments...",
            series_states=series_states,
            breakable=False
        ):
            old_tforms = section.tforms.copy()
            new_tforms = {}
            for new_a, old_a in alignment_dict.items():
                if old_a is None or old_a not in old_tforms:
                    continue
                else:
                    new_tforms[new_a] = old_tforms[old_a]
            section.tforms = new_tforms
            section.save()
        
        if log_event:
            for new_a, old_a in alignment_dict.items():
                if new_a == old_a:
                    continue
                if old_a is None and new_a in old_tforms and new_a not in alignment_dict.values():
                    self.addLog(None, None, f"Delete alignment {new_a}")
                elif old_a == self.alignment:
                    self.addLog(None, None, f"Create alignment {new_a} from {old_a}")
                elif old_a in old_tforms and new_a not in old_tforms:
                    self.addLog(None, None, f"Rename alignment {old_a} to {new_a}")
    
    def modifyBCProfiles(self, profiles_dict : dict, series_states=None, log_event=True):
        """Modify the series's brightness/contrast profiles.

        Accepts input from dialog. Note: Do not use this method outside of
        the user interface.
        
            Params:
                profiles_dict (dict): returned from the bc_profiles dialog
                series_states (SeriesStates): the series undo states from the GUI
                log_event (bool): True if event should be logged
        """
        # breakable=False: renaming or deleting a profile rewrites bc_profiles on
        # every section, and Series.bc_profiles raises when the sections disagree
        # about which profiles exist, so the undo has to be all-or-nothing rather
        # than dissolvable into per-section undos.
        for snum, section in self.enumerateSections(
            message="Modifying brightness/contrast profiles...",
            series_states=series_states,
            breakable=False
        ):
            old_profiles = section.bc_profiles.copy()
            # SeriesIterator records a per-section undo only when a section
            # reports modified traces, transforms or flags, and bc_profiles is
            # none of those, so hand the old profiles to the series state here.
            if series_states is not None:
                series_states.recordBCProfiles(snum, old_profiles)
            new_profiles = {}
            for new_p, old_p in profiles_dict.items():
                if old_p is None:
                    continue
                elif old_p not in old_profiles:
                    continue
                else:
                    new_profiles[new_p] = old_profiles[old_p]
            section.bc_profiles = new_profiles
            section.save()
        
        if log_event:
            for new_p, old_p in profiles_dict.items():
                if new_p == old_p:
                    continue
                if old_p is None and new_p in old_profiles and new_p not in profiles_dict.values():
                    self.addLog(None, None, f"Delete brightness/contrast profile {new_p}")
                elif old_p == self.alignment:
                    self.addLog(None, None, f"Create brightness/contrast profile {new_p} from {old_p}")
                elif old_p in old_profiles and new_p not in old_profiles:
                    self.addLog(None, None, f"Rename brightness/contrast profile {old_p} to {new_p}")
    
    def getZValues(self):
        """Return z-coordinates for each section.

        Notes: This method is primarily for 3D use.
        
            Returns:
                (dict): section number : z-value
        """
        zvals = {}
        z = 0
        for snum in sorted(self.sections.keys()):
            t = self.data["sections"][snum]["thickness"]
            z += t
            zvals[snum] = z
        
        return zvals
    
    def createZtrace(
            self,
            obj_name : str,
            cross_sectioned : bool = True,
            z_points : list = None,
            ztrace_color : tuple[int, ...] | list[int] = (0, 0, 0),
            log_event=True
    ):
        """Create a ztrace from an existing object in the series.

        ``ztrace_color`` moves with ``Ztrace.__init__``'s ``color``, which it is
        passed straight into below. The z-tracing path in
        ``FieldWidgetMouse.ztoolRelease`` calls this with
        ``ztrace_color=self.tracing_trace.color``, and a file-loaded trace's
        color is a ``list`` -- so a ``tuple``-only annotation here would go on
        rejecting a live caller even after ``Ztrace`` itself was corrected. See
        ``Ztrace.__init__`` for why the union names its two containers rather
        than saying ``Sequence[int]``.

            Params:
                obj_name (str): the name of the object to create the ztrace from
                cross_sectioned (bool): True if one ztrace point per section, False if multiple per section
                z_points (list): points provided if creating ztrace from field
                ztrace_color (tuple[int, ...] | list[int]): color of ztrace to display in field
                log_event (bool): True if event should be logged
        """
        # A fresh list per call: a shared mutable default would let the points
        # generated for one object leak into the next from-object ztrace.
        if z_points is None:
            z_points = []

        # capture this BEFORE the from-object branch below fills z_points --
        # the alignment decision at the end must not see the mutated list
        from_object = not z_points

        if from_object:  # append name with "_zlen" if creating from obj
            ztrace_name = f"{obj_name}_zlen"
        else:  # use tracing_trace name
            ztrace_name = obj_name

        ## Remove existing ztrace with same name
        
        if ztrace_name in self.ztraces:
            del(self.ztraces[ztrace_name])
            if log_event: self.addLog(ztrace_name, None, "Updated ztrace")

        if from_object:  # generate points from already traced object if none provided

            ## If create on midpoints, make one point per section

            if cross_sectioned:

                for snum, section in self.enumerateSections(
                    message="Creating ztrace..."
                ):

                    if obj_name in section.contours:

                        contour = section.contours[obj_name]
                        p = (*contour.getMidpoint(), snum)
                        z_points.append(p)

            ## Otherwise, make points by trace history by section. Each trace gets
            ## its own point, ztrace points made in chronological order of trace
            ## history. (Accomodates obliquely and longitudinally sectioned objects.

            else:

                for snum, section in self.enumerateSections(
                    message="Creating ztrace..."
                ):

                    if obj_name in section.contours:

                        contour = section.contours[obj_name]

                        for trace in contour:
                            # get the midpoint
                            p = (*trace.getMidpoint(), snum)
                            z_points.append(p)

        self.ztraces[ztrace_name] = Ztrace(
            ztrace_name,
            ztrace_color,
            z_points
        )

        ## Assign alignement to ztrace
        if from_object:  # use obj alignment
            alignment = self.getAttr(obj_name, "alignment")
        else:  # use current alignment
            alignment = self.alignment

        self.setAttr(ztrace_name, "alignment", alignment, ztrace=True)

        ## Set modified and log event
        
        self.modified_ztraces.add(ztrace_name)

        if log_event:
            self.addLog(ztrace_name, None, "Create ztrace")

        self.modified = True
    
    def editZtraceAttributes(self, name : str, new_name : str, new_color : tuple[int, ...] | list[int], log_event=True):
        """Edit the name and color of a ztrace.

        ``new_color`` moves with ``Ztrace.__init__``'s ``color``, which it is
        assigned to below. Its one caller, ``FieldWidgetTrace``'s method of the
        same name, seeds a ``ColorButton`` with the ztrace's current color and
        reads the button back, and the button
        returns that same object untouched unless the user actually picks a new
        one -- so on a file-loaded ztrace, whose color is a ``list``, the value
        arriving here is a list. See ``Ztrace.__init__`` for why the union names
        its two containers rather than saying ``Sequence[int]``.

            Params:
                name (str): the original ztrace name
                new_name (str): the new name
                new_color (tuple[int, ...] | list[int]): the new color
                log_event (bool): True if event should be logged
        """
        # modify the ztrace data
        ztrace = self.ztraces[name]
        if new_name:
            ztrace.name = new_name
            if new_name != name:  # if renamed
                del(self.ztraces[name])
                self.ztraces[new_name] = ztrace
                # update group data
                groups = self.ztrace_groups.getObjectGroups(name)
                for g in groups:
                    self.ztrace_groups.add(g, new_name)
                self.ztrace_groups.removeObject(name)
        if new_color:
            ztrace.color = new_color
        
        self.modified = True
        self.modified_ztraces.add(name)
        self.modified_ztraces.add(new_name)
        
        if log_event:
            if new_name != name:
                self.addLog(name, None, f"Rename ztrace to {new_name}")
                self.addLog(new_name, None, f"Create ztrace from {name}")
            else:
                self.addLog(name, None, "Modify ztrace")
    
    def smoothZtraces(self, names : list, smooth : int, newztrace : bool, log_event=True):
        """Smooth a set of ztraces.
        
            Params:
                names (list): the names of the ztraces to smooth
                smooth (int): the smoothing factor
                newztrace (bool): False if ztrace should be overwritten
        """
        ## Smooth ztraces
        for name in names:

            
            
            ## Create new ztrace if requested
            if newztrace:
                
                ztrace = self.ztraces[name].copy()
                ztrace_align = self.getAttr(name, "alignment", ztrace=True)
                
                new_name = f"{ztrace.name}_smooth{smooth}"

                ztrace.name = new_name
                self.ztraces[new_name] = ztrace
                self.setAttr(new_name, "alignment", ztrace_align, ztrace=True)
                
            else:
                
                ztrace = self.ztraces[name]
                
            ztrace.smooth(self, smooth)
            
            self.modified_ztraces.add(ztrace.name)
        
            if log_event:
                self.addLog(name, None, "Smooth ztrace")

    def deleteZtraces(self, names : list, log_event=True):
        """Delete a list of ztraces:
            Params:
                names (list): the names of the ztraces
        """
        for name in names:
            del(self.ztraces[name])
            self.modified_ztraces.add(name)
            self.ztrace_groups.removeObject(name)

            if log_event:
                self.addLog(name, None, "Delete ztrace")
        
    def rename(self, new_name : str):
        """Rename the series.
        
            Params:
                new_name (str): the new name for the series
        """
        old_name = self.name
        for snum in self.sections:
            sname = self.sections[snum]
            self.sections[snum] = sname.replace(old_name, new_name)
        self.name = new_name

    #### Series-wide trace functions ###############################################################
    
    def deleteObjects(self, obj_names : list, series_states=None):
        """Delete object(s) from the series.
        
            Params:
                obj_names (list): the objects to delete
                series_states (dict): for use with GUI states
        """
        def edit(section):
            modified = False
            for obj_name in obj_names:
                if obj_name in section.contours:
                    for trace in section.contours[obj_name]:
                        section.removeTrace(trace)
                    del(section.contours[obj_name])
                    modified = True
            if modified:
                # The `del` above drops a contour key from outside `Section`,
                # and the loop it follows removes from a list it is iterating,
                # so `removeTrace` is not reached for every trace in a contour
                # holding more than one. Either alone leaves the columnar store
                # holding rows for traces the object model no longer has.
                # Rebuild it from the result; without this the next edit on this
                # section raises `ColumnarDualWriteMismatch`.
                section.resyncColumnarStore()
            return modified  # deleting object will automatically be logged

        self._forEachObjectSection(
            obj_names, "Deleting object(s)...", edit, series_states
        )

        self.modified = True

    def copyObjectNames(self, obj_names : list) -> list:
        """The object names `copyObjects` would write its traces into.

        `copyObjects` invents its destination rather than asking for one, so the
        destination is not visible to a caller until the copy has happened.
        Split out so the lock check below, the return value, and the field can
        all name the same objects from one place.

            Params:
                obj_names (list): the objects that would be copied
            Returns:
                (list): the destination name for each, in the same order
        """
        return [f"{obj_name}_copy" for obj_name in obj_names]

    def lockedDestinations(self, names) -> list:
        """The locked objects among the names an operation would write into.

        The datatype counterpart to the field's lock checks. Those read the
        objects a selection is in now, so they cover an operation that names its
        destination. `copyObjects` and `splitObject` generate one instead, and a
        generated name can land on an object that already exists: `_copy` on a
        second copy of the same object, `_NN` on any series that already numbers
        objects that way. Neither generator looks for a free name, so the traces
        go into whatever is already there, and when that object is locked the
        operation adds traces to it. Adding traces is precisely what lock
        exists to prevent.

        Keyed on the destination name alone, so it stays inside the rule that
        locking guards quantitative data and never selection, color or
        visibility.

            Params:
                names (iterable): the object names that would receive traces
            Returns:
                (list): those that are locked, in order, without duplicates
        """
        return [
            name for name in dict.fromkeys(names)
            if self.getAttr(name, "locked")
        ]

    def copyObjects(self, obj_names: list, series_states=None, log_event=True) -> list:
        """Copy object(s) from the series

        Refuses outright if any generated destination is locked, and refuses the
        whole call rather than the offending object: one locked destination
        stops everything, which is the all-or-nothing shape the field's
        `refuseLockedTraces` and `object_function` already use, so a caller
        cannot end up with half a copy applied.

            Params:
                obj_names (list): the objects to delete
                series_states (dict): for use with GUI states
            Returns:
                (list): the names of the copies, empty if the copy was refused
        """
        copy_names = self.copyObjectNames(obj_names)

        if self.lockedDestinations(copy_names):
            return []

        if log_event:

            for obj_name in obj_names:
                self.addLog(obj_name, None, f"Create copy {obj_name}_copy")

        for snum, section in self.enumerateSections(
                message="Copying object(s)...",
                series_states=series_states,
                section_numbers=self.getObjectSections(obj_names)
        ):

            modified = False

            for obj_name in obj_names:

                if obj_name in section.contours:

                    traces = section.contours[obj_name].getTraces()
                    copy_name = f"{obj_name}_copy"
                    
                    for trace in traces:

                        copy_trace = trace.copy()
                        copy_trace.name = copy_name
                        section.addTrace(copy_trace, log_event=False)

                    modified = True

            if modified:
                section.save()

        ## Assign object attrs to copies
        for obj_name, copy_name in zip(obj_names, copy_names):
            self.objects.copyObjAttrs(obj_name, copy_name)

        self.modified = True

        return copy_names

    def copyTracesToSections(self, traces : list, section_numbers, series_states=None, log_event=True):
        """Copy traces into multiple sections at the same field (x, y) location.

        The traces' points must be given in FIELD (not SCREEN) coordinates.
        Each target section stores the points through its own inverse
        transform, so the traces land at the identical field x-y on every
        section regardless of how each section is aligned.

        An alignment lock protects a section's transform, not its trace
        content, so traces are copied onto every chosen section regardless of
        its lock status (just as traces can be drawn on a locked section).

            Params:
                traces (list): the traces to copy, points in field coordinates
                section_numbers (iterable): the target section numbers
                series_states (dict): section number : SectionStates (GUI undo)
                log_event (bool): True if the trace creation should be logged
            Returns:
                (tuple): (list of section numbers that received the traces,
                          list of section numbers skipped because their
                          transform is not invertible)
        """
        copied_to = []
        skipped = []

        for snum, section in self.enumerateSections(
            message="Copying traces to sections...",
            series_states=series_states,
            section_numbers=section_numbers
        ):
            # obtain this section's inverse transform ONCE; a singular
            # (non-invertible) transform cannot place the trace, so skip the
            # section rather than crash or store garbage points
            try:
                inv_tform = section.tform.inverted()
            except Exception:
                skipped.append(snum)
                continue

            for trace in traces:
                new_trace = trace.copy()
                # re-project the shared field coordinates through this section's
                # own inverse transform so the trace occupies the same field x-y
                new_trace.points = [inv_tform.map(*p) for p in trace.points]
                section.addTrace(new_trace, log_event=log_event)

            section.save()
            copied_to.append(snum)

        if copied_to:
            self.modified = True

        return copied_to, skipped

    def deleteAllTraces(self, trace_name : str, tags : set = None, series_states=None):
        """Delete all traces with a certain name and tag set.
        
            Params:
                trace_name (str): the name of the traces to delete
                tags (set): the tags to check to delete
        """
        def edit(section):
            if trace_name not in section.contours:
                return False
            contour = section.contours[trace_name]
            to_del = []
            for trace in contour:
                if (
                    (tags is not None and trace.tags == tags) or
                    (tags is None)
                ):
                    to_del.append(trace)
            for trace in to_del:
                section.removeTrace(trace)
            return bool(to_del)

        self._forEachObjectSection(
            [trace_name], "Deleting trace(s)...", edit, series_states
        )
        self.modified = True
    
    def editObjectAttributes(
            self, 
            obj_names : list, 
            name : str = None, 
            color : tuple = None, 
            tags : set = None, 
            mode : tuple = None, 
            sections : list = None, 
            series_states=None,
            add_tags : bool = True,
            log_event=True):
        """Edit the attributes of objects.
        
            Params:
                obj_names (list): the names of the objects to rename
                name (str): the new name for the objects
                color (tuple): the new color for the objects
                tags (set): the tags for the traces of the objects. None leaves
                    every trace's own tags untouched, as for name/color/mode.
                mode (tuple): the display mode to set for the traces
                section (list): the section numbers to modify the object on (default: all)
                series_states: the series states as store in the GUI
                add_tags (bool): True if `tags` should be added to each trace's
                    existing tags, False if it should REPLACE them. Only a
                    replacement can remove a tag, so a caller that shows the
                    user the current tags and takes back an edited set must pass
                    False. Additive is the default because a caller working on a
                    selection whose tags it never displayed cannot ask for a
                    replacement without discarding tags the user never saw.
                log_event (bool): True if event should be logged
        """
        ## Preemptively create log
        if log_event:
            for obj_name in obj_names:
                if name and obj_name != name:
                    self.addLog(obj_name, None, f"Rename object to {name}")
                    self.addLog(name, None, f"Create trace(s) from {obj_name}")
                else:
                    self.addLog(obj_name, None, "Modify object")
        
        ## Modify object on every section
        attrs_migrated = False
        for snum, section in self.enumerateSections(
            message="Modifying object(s)...",
            series_states=series_states,
            section_numbers=self.getObjectSections(obj_names)
        ):

            ## Move object attrs

            ## Note why this must be done once inside the loop: the loop
            ## initiates series_state data collection, and renaming must happen
            ## after the series state collection; however, it must also happen
            ## before the object is fully deleted.
            
            if name and not attrs_migrated:
                
                for obj_name in obj_names:

                    if obj_name != name:
                        self.renameObjAttrs(obj_name, name)
                        
                attrs_migrated = True
            
            if sections is not None and snum not in sections:  # None = all sections
                continue

            traces = []
            
            for obj_name in obj_names:
                
                if obj_name in section.contours:
                    traces += section.contours[obj_name].getTraces()
                    
            if traces:
                
                section.editTraceAttributes(
                    traces, name, color, tags, mode, add_tags=add_tags, log_event=False
                )
                
                ## Gather new traces
                if name:
                    traces = section.contours[name].getTraces()
                    
                else:
                    traces = []
                    for obj_name in obj_names:
                        if obj_name in section.contours:
                            traces += section.contours[obj_name].getTraces()

                section.save()

        ## Migrate attrs even if no sections were iterated (e.g. an object with
        ## no traces): the loop above does this on its first iteration, so this
        ## only fires when the loop did not run.
        if name and not attrs_migrated:
            for obj_name in obj_names:
                if obj_name != name:
                    self.renameObjAttrs(obj_name, name)
            attrs_migrated = True

        self.modified = True

    def smoothObject(self, obj_names: list, series_states=None, log_event=True) -> list:
        """Smooth all traces belonging to an object.

        Malformed traces with too few points to smooth (e.g. "pixel dust"
        artifacts) are skipped rather than smoothed.

            Returns:
                (list): one record per skipped trace, each a dict with keys
                    "name" (object name), "section" (section number),
                    "points" (point count), "index" (the trace's position
                    within the contour on that section, used to focus the
                    field on that exact trace), "location" ((x, y) of the
                    first point, or None when the trace has no points),
                    "reason" (why it was skipped) and "match" (a
                    {"color", "points"} signature used to re-find and delete
                    the trace later). Empty when nothing was skipped.
        """

        window = self.getOption("roll_window")

        if log_event:

            for obj_name in obj_names:

                self.addLog(obj_name, None, f"Smooth {obj_name} traces")

        malformed = []

        for snum, section in self.enumerateSections(
                message="Smoothing traces...",
                series_states=series_states,
                section_numbers=self.getObjectSections(obj_names)
        ):

            section_modified = False

            for obj_name in obj_names:

                obj = section.contours.get(obj_name)

                if obj:

                    smoothed_any = False

                    for index, trace in enumerate(obj.traces):

                        if trace.smooth(window=window, spacing=0.004):

                            smoothed_any = True

                        else:

                            num_points = len(trace.points)

                            malformed.append({
                                "name": obj_name,
                                "section": snum,
                                # position within the contour, so the dialog can
                                # frame this exact trace (findTrace) on go-to
                                "index": index,
                                "points": num_points,
                                "location": (
                                    tuple(round(c, 4) for c in trace.points[0])
                                    if num_points else None
                                ),
                                # Trace.smooth only returns falsy for these two
                                # reasons, distinguishable by the point count.
                                "reason": (
                                    "Fewer than 3 points"
                                    if num_points < 3
                                    else "Smoothing produced no points"
                                ),
                                # signature used to re-find this exact trace at
                                # delete time (sections are reloaded fresh from
                                # disk). points are rounded to the 7 decimals
                                # save() writes, so the match survives a reload.
                                "match": {
                                    "color": trace.color,
                                    "points": [
                                        (round(x, 7), round(y, 7))
                                        for x, y in trace.points
                                    ],
                                },
                            })

                    if smoothed_any:

                        section.modified_contours.add(obj_name)
                        section_modified = True

            # only re-serialize sections that actually changed (previously every
            # section was saved, recomputing its full geometry index each time)
            if section_modified:

                # `Trace.smooth` rewrote `points` in place on traces the section
                # already holds, from outside `Section`, so no dual-write hook
                # saw it and the store still carries the unsmoothed points.
                # Without this rebuild the drifted rows survive until
                # something notices: the `section.save()` on the next line
                # rebuilds the store and writes the drift to the log (D11), and
                # the user's next edit to one of these traces raises
                # `ColumnarDualWriteMismatch` in their face. Once per section
                # rather than once per contour: `resyncColumnarStore` rebuilds
                # the whole section's store either way, and `section_modified` is
                # true exactly when some contour set `smoothed_any`.
                section.resyncColumnarStore()

                section.save()

                self.modified = True

        return malformed

    def deleteMalformedTraces(self, records : list, series_states=None, message="Deleting malformed contours...") -> list:
        """Delete specific malformed traces reported by smoothObject.

        Also used by the data clean-up operations (pixel-dust / empty traces),
        which produce records with the same schema (name, section, match); pass
        a different ``message`` so the progress bar reads sensibly.

        Each record must carry the keys produced by smoothObject — in
        particular "name", "section" and "match" (a {"color", "points"}
        signature). Because sections are reloaded fresh from disk, the stored
        signature is matched against each candidate trace by color and
        7-decimal-rounded points rather than by object identity, so the exact
        trace is removed even across a save/reload. A record whose trace can no
        longer be found (e.g. it was edited or re-smoothed in the meantime) is
        skipped and left out of the returned list.

            Params:
                records (list): malformed-contour records to delete
                series_states: the series states as stored in the GUI (undo)
            Returns:
                (list): the records whose trace was found and deleted
        """
        ## Group records by section so each section is loaded and saved once
        by_section = {}
        for record in records:
            by_section.setdefault(record["section"], []).append(record)

        if not by_section:
            return []

        deleted = []
        for snum, section in self.enumerateSections(
            message=message,
            series_states=series_states
        ):
            removed_any = False
            for record in by_section.get(snum, []):
                contour = section.contours.get(record["name"])
                if not contour:
                    continue
                for trace in contour:
                    if self._traceMatchesSignature(trace, record["match"]):
                        section.removeTrace(trace)
                        deleted.append(record)
                        removed_any = True
                        break
            if removed_any:
                section.save()

        if deleted:
            self.modified = True
        return deleted

    @staticmethod
    def _traceMatchesSignature(trace, signature) -> bool:
        """Whether a trace matches a malformed record's signature.

        Compares color and points; points are rounded to 7 decimals (the
        precision save() writes to disk) so a signature captured before save
        still matches the trace once it is reloaded.
        """
        if trace.color != signature["color"]:
            return False
        points = trace.points
        if len(points) != len(signature["points"]):
            return False
        for (x, y), (sx, sy) in zip(points, signature["points"]):
            if round(x, 7) != sx or round(y, 7) != sy:
                return False
        return True

    @staticmethod
    def _cleanupRecord(obj_name, snum, index, trace, reason, area=None,
                       area_px=None) -> dict:
        """Build a clean-up candidate record.

        Uses the same schema smoothObject produces (so the records can be
        deleted with deleteMalformedTraces and shown in the review dialog): a
        "match" signature of color + 7-decimal-rounded points re-finds the exact
        trace after the section is reloaded from disk. An optional pixel area
        (px^2) and physical area (um^2) are carried for display in the
        pixel-dust review list.
        """
        num_points = len(trace.points)
        record = {
            "name": obj_name,
            "section": snum,
            "index": index,
            "points": num_points,
            "location": (
                tuple(round(c, 4) for c in trace.points[0])
                if num_points else None
            ),
            "reason": reason,
            "match": {
                "color": trace.color,
                "points": [
                    (round(x, 7), round(y, 7)) for x, y in trace.points
                ],
            },
        }
        if area is not None:
            record["area"] = area
        if area_px is not None:
            record["area_px"] = area_px
        return record

    @staticmethod
    def _traceArea(trace, tform) -> float:
        """Physical area (um^2) of a trace, matching the object/trace tables.

        Mirrors TraceData: map the points through the section transform, then
        run the shared traceGeometry math. Open traces have no enclosed area.
        """
        if not trace.closed or len(trace.points) < 3:
            return 0.0
        pts = tform.mapPointsArray(trace.points)
        if not len(pts):
            return 0.0
        _, area, _, _ = traceGeometry(pts, True)
        return abs(area)

    def findPixelDustTraces(self, threshold_px : float, include_locked=False) -> list:
        """Find tiny "pixel-dust" traces at or below an area threshold in PIXELS.

        The threshold is expressed in pixels (px^2) so "pixel dust" means
        literally "smaller than N pixels on its own image". Because a section's
        magnification (``section.mag``, um/px) sets how big a pixel is, the
        physical cutoff is derived PER SECTION: a pixel-area threshold of
        ``threshold_px`` becomes ``threshold_px * section.mag ** 2`` um^2 on that
        section. A trace's physical area (um^2, computed the same way the
        object/trace tables report it) is compared against that per-section
        cutoff, so the same px threshold adapts to each section's scale.

        A candidate is a CLOSED trace whose physical area is greater than zero
        and at or below the per-section cutoff. Zero-area / degenerate traces are
        left to findEmptyTraces so the two operations stay disjoint. Open traces
        (lines) have no enclosed area and are never pixel dust. Locked objects
        are skipped unless ``include_locked`` is True. This only scans; nothing
        is modified. Use deleteMalformedTraces to remove the chosen records.

            Params:
                threshold_px (float): the maximum area in pixels (px^2), inclusive
                include_locked (bool): True to also consider locked objects
            Returns:
                (list): candidate records (see _cleanupRecord); each carries both
                    the pixel area ("area_px") and its physical area ("area", um^2)
        """
        candidates = []
        for snum, section in self.enumerateSections(
            message="Scanning for pixel-dust traces...",
        ):
            tform = section.tform
            mag2 = section.mag ** 2  # (um/px)^2, this section's pixel scale
            threshold_um2 = threshold_px * mag2  # px^2 cutoff -> this section's um^2
            for cname in section.contours:
                if not include_locked and self.getAttr(cname, "locked"):
                    continue
                for index, trace in enumerate(section.contours[cname]):
                    if not trace.closed or len(trace.points) < 3:
                        continue
                    area = self._traceArea(trace, tform)
                    if 0 < area <= threshold_um2:
                        area_px = area / mag2 if mag2 else 0.0
                        candidates.append(self._cleanupRecord(
                            cname, snum, index, trace,
                            reason=(
                                f"Area {area_px:.6g} px^2 (<= {threshold_px:.6g}); "
                                f"{area:.6g} um^2"
                            ),
                            area=area,
                            area_px=area_px,
                        ))
        return candidates

    def findEmptyTraces(self, include_locked=False) -> list:
        """Find empty / degenerate traces (no meaningful geometry).

        A trace is empty when it encloses/spans nothing: no points, a closed
        trace with zero area (fewer than 3 points or fully collinear/coincident
        points), or an open trace with zero length (all points coincident).
        These are unambiguous to remove. Locked objects are skipped unless
        ``include_locked`` is True. Scans only; use deleteMalformedTraces to
        remove the chosen records.

            Params:
                include_locked (bool): True to also consider locked objects
            Returns:
                (list): candidate records (see _cleanupRecord)
        """
        candidates = []
        for snum, section in self.enumerateSections(
            message="Scanning for empty traces...",
        ):
            tform = section.tform
            for cname in section.contours:
                if not include_locked and self.getAttr(cname, "locked"):
                    continue
                for index, trace in enumerate(section.contours[cname]):
                    npts = len(trace.points)
                    if npts == 0:
                        reason = "No points"
                    elif trace.closed:
                        if self._traceArea(trace, tform) == 0:
                            reason = "Closed trace enclosing zero area"
                        else:
                            continue
                    else:
                        length, _, _, _ = traceGeometry(
                            tform.mapPointsArray(trace.points), False
                        )
                        if length == 0:
                            reason = "Open trace of zero length"
                        else:
                            continue
                    candidates.append(self._cleanupRecord(
                        cname, snum, index, trace, reason=reason,
                    ))
        return candidates

    ## A pair of traces is only worth measuring an overlap ratio for if that
    ## ratio could possibly clear the threshold. _duplicatePairs proves a
    ## ceiling on the ratio from quantities it already has, and skips the pair
    ## when the ceiling falls this far below the threshold. The ceiling bounds
    ## the ratio of the true geometry; getOverlapRatio measures a rasterized
    ## approximation of it, which can read slightly high, so the ceiling is not
    ## applied at the threshold itself. Measured over the 2,465 pairs of
    ## bounding-box-overlapping differently-named traces on the densest section
    ## of a real 161,767-trace autoseg series, the rasterized ratio exceeded the
    ## ceiling by at most 0.008; 0.05 is six times that.
    _OVERLAP_CEILING_MARGIN = 0.05

    @classmethod
    def _duplicatePairs(cls, entries : list, threshold : float, mag : float = None):
        """Yield every pair of differently-named traces on a section that overlap.

        ``entries`` is one tuple per trace,
        ``(xmin, ymin, xmax, ymax, area, name, index, trace)``, where the bounds
        and area are in the trace's own untransformed coordinates (the space
        Trace.getOverlapRatio works in). Yields
        ``(entry_a, entry_b, ratio, points_match)`` per overlapping pair, ``a``
        before ``b`` in (name, index) order so the output does not depend on
        which order the section's contours were walked in.

        Comparing across names means comparing every trace on the section with
        every other, and a dense autosegmented section carries enough traces
        that measuring an overlap ratio for each of those pairs is not viable:
        Trace.getOverlapRatio rasterizes both polygons, which costs about 3 ms a
        pair. Two filters keep the number of ratios measured proportional to the
        number of traces rather than to its square:

          1. **An x-sorted sweep.** Entries are sorted by ``xmin``, so once a
             later entry starts to the right of where the current one ends, no
             remaining entry can touch it and the inner loop stops. Pairs whose
             bounding boxes are disjoint are therefore never even enumerated,
             and Trace.getOverlapRatio would have answered 0 for all of them.
          2. **A ceiling on the ratio, for closed pairs.** A closed pair's
             overlap ratio is an intersection-over-union of areas, so it is at
             most ``min(box_intersection, area_a, area_b) / max(area_a, area_b)``:
             the shapes cannot share more than the overlap of their bounding
             boxes, nor more than the smaller of them, and their union is at
             least the larger of them. Two traces of the same structure have
             nearly the same area and nearly the same bounding box, which puts
             that ceiling near 1; two neighboring autosegmented traces whose
             boxes merely touch put it near 0. **Open pairs are exempt**, because
             their ratio is not an area ratio at all -- see the comment at the
             ceiling itself, and Trace.getOverlapRatio.

        One limit worth naming, since the sweep decides what can be found at all:
        every bounding-box test here is slack by Trace.POINTS_MATCH_TOLERANCE
        (1e-2), which covers the point-match case exactly. An open pair is
        measured against Trace.openCurveTolerance instead, which is at most
        ``Trace.OPEN_TRACE_MATCH_MAX_PIXELS * mag``, so the two agree whenever
        ``mag`` is at or below 2e-3 series units per pixel -- and on a coarser
        section the open tolerance can exceed the slack, leaving a pair that sits
        within tolerance while its boxes miss by more than the slack unenumerated.
        Widening the sweep to cover it needs a bound over every entry, which would
        loosen the termination test for every pair on the section and give back
        the sweep's whole benefit, so it is deliberately not done. Such a pair is
        nearly disjoint and would score low anyway. (Before the tolerance was
        bounded this gap opened at an arc length of about 0.5 regardless of mag,
        which on a real series meant most of the long traces on it.)

        Point-for-point matches are settled before either filter can reach them,
        because a trace with no area at all (a straight line, say) is still a
        duplicate of an identical copy of itself, and both filters reason about
        areas. That mirrors Trace.overlaps, which also answers on points first.

        **Every bounding-box test here is slack by Trace's point-match
        tolerance**, and it has to be. Two traces can match point for point
        within that tolerance while their bounding boxes do not quite touch, so a
        strict box test throws away pairs that Trace.overlaps calls duplicates.
        That is not hypothetical: on the densest section of a real 161,767-trace
        autoseg series it is the one and only pair on the section, two two-point
        traces 0.006 apart in y. A brute-force comparison of all 833,000 pairs
        found it and a strict sweep did not.

            Params:
                entries (list): per-trace tuples, described above
                threshold (float): the overlap ratio above which two traces
                    count as duplicates, as in Trace.overlaps
                mag (float): the section's magnification, passed on to
                    Trace.getOverlapRatio, which requires it for an open pair
            Yields:
                (tuple): (entry_a, entry_b, ratio, points_match)
        """
        ## sorted by xmin so the inner loop can stop rather than run to the end
        entries = sorted(entries, key=lambda e: e[0])
        ceiling_floor = threshold - cls._OVERLAP_CEILING_MARGIN
        tol = Trace.POINTS_MATCH_TOLERANCE
        n = len(entries)
        for i in range(n):
            a = entries[i]
            axmin, aymin, axmax, aymax, aarea, aname, aindex, atrace = a
            for j in range(i + 1, n):
                b = entries[j]
                bxmin, bymin, bxmax, bymax, barea, bname, bindex, btrace = b
                if bxmin > axmax + tol:
                    break  # sorted by xmin: nothing further can reach a
                if aname == bname:
                    continue  # same-name duplicates are deleteDuplicateTraces'
                if atrace.closed != btrace.closed:
                    continue  # as in Trace.overlaps
                if aymax + tol < bymin or bymax + tol < aymin:
                    continue  # boxes overlap in x but not in y

                ## first, second: the pair in a stable order for the caller
                if (aname, aindex) <= (bname, bindex):
                    first, second = a, b
                else:
                    first, second = b, a

                if atrace.pointsMatch(btrace):
                    yield first, second, 1.0, True
                    continue

                ## the ceiling (see the docstring). Both areas zero means there
                ## is nothing to reason about, and getOverlapRatio answers 0 for
                ## that case rather than dividing by a collapsed bounding box.
                ## The box overlap is clamped at zero because the tests above are
                ## slack by the point-match tolerance, so a pair whose boxes miss
                ## each other by less than that reaches here.
                ##
                ## Only for closed pairs. The ceiling bounds an
                ## intersection-over-union of areas, which is what
                ## getOverlapRatio measures for closed traces and precisely what
                ## it does not measure for open ones: an open pair is compared
                ## curve-to-curve, and the "area" of an open trace is the sliver
                ## between the polyline and its own closing chord, a quantity
                ## with no bearing on whether the two curves coincide. Applying
                ## the ceiling to open pairs discards real duplicates before they
                ## are ever measured -- two near-straight profiles 0.28% apart in
                ## length, the reported case, ceiling at 0.63 and were dropped at
                ## a 0.95 threshold. Open pairs are filtered by the sweep and the
                ## bounding-box tests above and then measured; _openCurveRatio is
                ## several times cheaper than rasterizing, so the pairs that now
                ## reach it cost less each than the closed pairs always did.
                larger = aarea if aarea > barea else barea
                if larger > 0 and atrace.closed:
                    box_intersection = max(
                        0.0,
                        min(axmax, bxmax) - max(axmin, bxmin)
                    ) * max(
                        0.0,
                        min(aymax, bymax) - max(aymin, bymin)
                    )
                    ceiling = min(box_intersection, aarea, barea) / larger
                    if ceiling <= ceiling_floor:
                        continue

                ratio = atrace.getOverlapRatio(btrace, mag)
                if Trace.ratioIsOverlap(ratio, threshold):
                    yield first, second, ratio, False

    def findDifferentlyNamedDuplicates(self, threshold : float,
                                       include_locked=False) -> list:
        """Find traces that duplicate each other under two different names.

        The same-name case is Series.deleteDuplicateTraces, and it stays exactly
        as it is: that comparison only ever sees traces already grouped under one
        contour name, so two people tracing one structure under two names produce
        a duplicate it cannot find. This scans across names instead, comparing
        every trace on a section with every other one, and reports what it finds.

        This scan modifies nothing. Which of the two names is the right one is a
        judgment about the data rather than something geometry can settle, so
        this operation never chooses: the review list it feeds asks the person
        reading it, one row at a time, and deleteDifferentlyNamedDuplicates
        applies only the choices actually made. A row nobody answered is left
        alone rather than resolved by any rule, because every rule available
        here ("keep the name on more sections", "keep the larger trace") would
        be geometry answering a question about the data. Locked objects are
        skipped unless ``include_locked`` is True, matching findPixelDustTraces
        and findEmptyTraces; a locked object surfaced that way can still not
        have a trace deleted (see deleteDifferentlyNamedDuplicates).

        Overlap is decided exactly as it is for same-name duplicates, by
        Trace.overlaps' two tests: an identical point sequence, or an overlap
        ratio above ``threshold``. See _duplicatePairs for how the comparison is
        kept affordable across a whole section.

            Params:
                threshold (float): the overlap ratio above which two traces
                    count as duplicates
                include_locked (bool): True to also consider locked objects
            Returns:
                (list): one record per pair (see _cleanupRecord), describing the
                    first trace of the pair, with the second carried alongside
                    under the "other_" keys, plus the measured "ratio"
        """
        candidates = []
        for snum, section in self.enumerateSections(
            message="Scanning for duplicates named differently...",
        ):
            tform = section.tform
            entries = []
            for cname in section.contours:
                if not include_locked and self.getAttr(cname, "locked"):
                    continue
                for index, trace in enumerate(section.contours[cname]):
                    if not trace.points:
                        continue  # nothing to compare; findEmptyTraces' business
                    xmin, ymin, xmax, ymax = trace.getBounds()
                    ## the untransformed polygon area, in the same coordinates
                    ## getOverlapRatio rasterizes, for the ceiling in
                    ## _duplicatePairs. Not the physical area: that is measured
                    ## through the section transform, below, for the pairs that
                    ## survive.
                    _, area, _, _ = traceGeometry(trace.points, True)
                    entries.append(
                        (xmin, ymin, xmax, ymax, abs(area), cname, index, trace)
                    )

            for first, second, ratio, points_match in self._duplicatePairs(
                entries, threshold, section.mag
            ):
                fname, findex, ftrace = first[5], first[6], first[7]
                sname, sindex, strace = second[5], second[6], second[7]
                if points_match:
                    reason = f"Point-for-point match with '{sname}'"
                else:
                    reason = (
                        f"Overlap {ratio:.4g} with '{sname}' "
                        f"(above {threshold:.4g})"
                    )
                record = self._cleanupRecord(
                    fname, snum, findex, ftrace, reason=reason,
                    area=self._traceArea(ftrace, tform),
                )
                other = self._cleanupRecord(
                    sname, snum, sindex, strace, reason=reason,
                    area=self._traceArea(strace, tform),
                )
                record["ratio"] = ratio
                record["other_name"] = other["name"]
                record["other_index"] = other["index"]
                record["other_points"] = other["points"]
                record["other_location"] = other["location"]
                record["other_area"] = other["area"]
                record["other_match"] = other["match"]
                candidates.append(record)

        return candidates

    def deleteDifferentlyNamedDuplicates(self, choices : list,
                                         series_states=None,
                                         log_event=True) -> list:
        """Delete the unkept side of cross-name duplicate pairs the user chose.

        The removal half of findDifferentlyNamedDuplicates. Each choice is a
        ``(record, keep)`` tuple: ``record`` is a pair record from that scan and
        ``keep`` names which of the pair's two traces to keep, ``"first"`` for
        the record's own trace (its "name") or ``"other"`` for the one carried
        under the "other_" keys. The trace that was not kept is deleted; both
        traces of the pair survive if no choice was made.

        **Nothing is inferred.** A choice that is neither ``"first"`` nor
        ``"other"`` -- ``None`` above all, which is what an unanswered row
        carries -- is skipped, not resolved by a default. Silence is not a
        selection: the caller has to say which name is right, because that is
        the one thing the geometry cannot say.

        **A locked object never loses a trace here**, even when the scan that
        produced the record was run with ``include_locked=True`` and so put the
        locked object on the list. Deleting a trace changes quantitative data,
        which is exactly what locking an object refuses; the lock is checked
        against the object being *deleted from*, since keeping a trace does not
        modify it.

        Deletion runs through deleteMalformedTraces, the same path the
        pixel-dust and empty-trace clean-ups use, so it is one undoable
        operation (enumerateSections records the undo state into
        ``series_states``) and each trace is re-found after its section is
        reloaded by its stored color+points signature rather than by identity.

            Params:
                choices (list): (record, keep) tuples, described above
                series_states (dict): optional dict of undo states for GUI
                log_event (bool): True if events should be logged
            Returns:
                (list): the (record, keep) tuples whose trace was found and
                    deleted, so a caller can prune exactly those rows
        """
        targets = []
        for choice in choices:
            record, keep = choice
            if keep == "first":
                delete_name = record["other_name"]
                delete_match = record["other_match"]
                keep_name = record["name"]
            elif keep == "other":
                delete_name = record["name"]
                delete_match = record["match"]
                keep_name = record["other_name"]
            else:
                continue  # no choice made: never guess which name is right
            if self.getAttr(delete_name, "locked"):
                continue  # deleting a trace is a quantitative change
            targets.append({
                "name": delete_name,
                "section": record["section"],
                "match": delete_match,
                ## carried through deleteMalformedTraces, which returns the very
                ## dicts it deleted, so the log and the return value can name
                ## the pair each deletion came from
                "keep_name": keep_name,
                "choice": choice,
            })

        if not targets:
            return []

        deleted = self.deleteMalformedTraces(
            targets,
            series_states=series_states,
            message="Deleting duplicates named differently...",
        )

        if log_event:
            for target in deleted:
                self.addLog(
                    target["name"],
                    target["section"],
                    "Delete duplicate trace named differently "
                    f"(kept '{target['keep_name']}')",
                )

        return [target["choice"] for target in deleted]

    def editObjectRadius(self, obj_names : list, new_rad : float, series_states=None):
        """Change the radii of all traces of an object.
        
            Params:
                obj_names (list): the names of objects to modify
                new_rad (float): the new radius for the traces of the object
                series_states (dict): optional dict for GUI undo states
        """
        def edit(section):
            traces = []
            for name in obj_names:
                if name in section.contours:
                    traces += section.contours[name].getTraces()
            if not traces:
                return False
            section.editTraceRadius(traces, new_rad)
            return True

        self._forEachObjectSection(
            obj_names, "Modifying radii...", edit, series_states
        )

        self.modified = True
    
    def editObjectShape(self, obj_names : list, new_shape : list, series_states=None):
        """Change the shape of all traces of an object.
        
            Params:
                obj_names (list): the names of objects to modify
                new_shape (list): the new shape for the traces of the object
                series_states (dict): optional dict for GUI undo states
        """
        def edit(section):
            traces = []
            for name in obj_names:
                if name in section.contours:
                    traces += section.contours[name].getTraces()
            if not traces:
                return False
            section.editTraceShape(traces, new_shape)
            return True

        self._forEachObjectSection(
            obj_names, "Modifying shapes...", edit, series_states
        )

        self.modified = True
    
    def listObjects(self):
        """List all objects in a series."""

        series_data = self.data.data
        objs = list(series_data["objects"].keys())
        objs.sort()

        return objs

    def removeAllTraceTags(self, obj_names : list, series_states=None, log_event=True):
        """Remove all tags from all traces on a set of objects.
        
            Params:
                obj_names (list): a list of object names
                series_states (dict): optional dict for GUI undo states
                log_event (bool): True if event should be logged
        """
        def edit(section):
            traces = []
            for obj_name in obj_names:
                if obj_name in section.contours:
                    traces += section.contours[obj_name].getTraces()
            if not traces:
                return False
            section.editTraceAttributes(
                traces,
                name=None,
                color=None,
                tags=set(),
                mode=None, 
                log_event=False
            )
            return True

        self._forEachObjectSection(
            obj_names, "Removing trace tags...", edit, series_states
        )

        if log_event:
            for name in obj_names:
                self.addLog(name, None, "Remove all trace tags")

        self.modified = True

    def reapplyAutosegColors(self, obj_names : list, series_states=None, log_event=True):
        """Recolor objects using the CURRENT palette and seed.

        Presented to the user as "Reapply custom color palette to existing objects..." (context menus)
        and "Recolor all objects from palette..." (View menu). Renamed from
        "autoseg colors" on 2026-08-12 because the mapping below covers any
        name; the method keeps its historical name.

        Lets a user reapply today's palette (colorblind-safe default or a custom
        one) to objects imported before the palette existed -- their old colors
        were baked in at import time and never update on their own.

        Each object's color is resolved from its name: an unmodified autoseg
        name ("autoseg_<id>") recovers its label id and gets exactly the color a
        fresh import would assign; any other name falls back to a stable hash of
        the name (see ``palette_color_for_name``). The color is written through
        the same per-section ``editTraceAttributes`` path every other bulk
        attribute edit uses, so it is one undoable operation and the field/lists
        refresh correctly.

            Params:
                obj_names (list): the names of objects to recolor
                series_states (dict): optional dict for GUI undo states
                log_event (bool): True if the event should be logged
        """
        from PyReconstruct.modules.backend.autoseg.palette import (
            DEFAULT_AUTOSEG_PALETTE,
            palette_color_for_name,
        )

        ## Resolve the palette + seed once (empty override -> curated default),
        ## then the per-object color once -- these do not vary by section.
        palette = self.getOption("autoseg_color_palette") or DEFAULT_AUTOSEG_PALETTE
        color_seed = self.getOption("autoseg_color_seed") or 0
        color_map = {
            name: palette_color_for_name(name, palette, color_seed)
            for name in obj_names
        }

        def edit(section):
            modified = False
            for obj_name in obj_names:
                if obj_name in section.contours:
                    traces = section.contours[obj_name].getTraces()
                    if traces:
                        section.editTraceAttributes(
                            traces,
                            name=None,
                            color=color_map[obj_name],
                            tags=None,
                            mode=None,
                            log_event=False
                        )
                        modified = True
            return modified

        ## Touch only the sections the selected objects appear on.
        self._forEachObjectSection(
            obj_names, "Reapplying custom color palette...", edit, series_states
        )

        if log_event:
            for name in obj_names:
                self.addLog(name, None, "Reapply custom color palette")

        self.modified = True

    def hideObjects(self, obj_names : list, hide=True, series_states=None, log_event=True):
        """Hide all traces of a set of objects throughout the series.
        
            Params:
                obj_names (list): the names of objects to hide
                hide (bool): True if object should be hidden
                series_states (dict): optional dict for GUI undo states
                log_event (bool): True if event should be logged
        """
        def edit(section):
            modified = False
            for name in obj_names:
                if name in section.contours:
                    contour = section.contours[name]
                    for trace in contour:
                        trace.setHidden(hide)
                        modified = True
                    section.modified_contours.add(name)
            if modified:
                # `setHidden` writes the trace in place, from outside `Section`,
                # so no dual-write hook saw it and the columnar store still
                # holds the old flag. Rebuild from the result. Not optional --
                # `Section.save()` would rebuild the store anyway and log the
                # drift (D11), but the user's next edit to one of these traces
                # raises `ColumnarDualWriteMismatch` in their face first.
                section.resyncColumnarStore()
            return modified

        self._forEachObjectSection(
            obj_names,
            "Hiding object(s)..." if hide else "Unhiding object(s)...",
            edit,
            series_states,
        )

        if log_event:
            for name in obj_names:
                event = f"{'Hide' if hide else 'Unhide'} object"
                self.addLog(name, None, event)
        
        self.modified = True

    def snapshotObjectVisibility(self, obj_names) -> dict:
        """Record the hidden flags of a set of objects, series-wide.

        Read straight out of the in-memory object index
        (``data["objects"][name].traces``, keyed by section number, each
        ``TraceData`` carrying the ``hidden`` of the trace at that index in the
        section's contour), which ``Section.save`` keeps current. So this costs
        no section loads and is cheap enough to run in front of an isolate.

        PER TRACE, not per object, because that is the only granularity the data
        has: there is no object-level ``hidden`` attribute anywhere -- the flag
        lives on ``Trace.hidden``, and ``hideObjects`` writes the same value onto
        every trace of the contour. An object-level snapshot would therefore be
        lossy for a contour whose traces were hidden individually (the trace
        menu's ``Hide selected traces`` does exactly that), and restoring it
        would unhide traces the user hid by hand.

            Params:
                obj_names (iterable): the object names to record
            Returns:
                (dict): {object name: {section number: [hidden, ...]}}, the list
                    indexed the same way the section's contour is
        """
        snapshot = {}
        for name in obj_names:
            obj_data = self.data["objects"].get(name)
            if obj_data is None:
                continue
            snapshot[name] = {
                snum: [t.hidden for t in traces]
                for snum, traces in obj_data.traces.items()
            }
        return snapshot

    def restoreObjectVisibility(self, snapshot : dict, series_states=None, log_event=True):
        """Put back the hidden flags recorded by snapshotObjectVisibility.

        Only the sections the snapshot mentions are loaded, and only contours
        whose flags actually differ are written, so a restore that changes
        nothing costs no section writes and records no per-section undo.

        Traces are matched by their index in the contour, the same way
        ``TraceData`` resolves a table row back to a trace. If a contour's length
        changed since the snapshot (traces added or deleted in between) the
        overlap is restored and the rest is left as it is: a stale index would
        otherwise hide the wrong trace.

        No lock check, deliberately. Locking guards edits and quantification,
        not visibility, so a locked object's traces are restored like any other's
        -- the same rule ``hideObjects`` and ``hideOtherObjects`` follow.

            Params:
                snapshot (dict): as returned by snapshotObjectVisibility
                series_states (dict): optional dict for GUI undo states
                log_event (bool): True if event should be logged
            Returns:
                (bool): True if any trace's hidden flag was changed
        """
        if not snapshot:
            return False

        section_numbers = set()
        for by_section in snapshot.values():
            section_numbers.update(by_section.keys())
        if not section_numbers:
            return False

        changed_any = False
        for snum, section in self.enumerateSections(
            message="Restoring visibility...",
            series_states=series_states,
            section_numbers=section_numbers
        ):
            modified = False
            for name, by_section in snapshot.items():
                flags = by_section.get(snum)
                if not flags or name not in section.contours:
                    continue
                contour = section.contours[name]
                contour_modified = False
                for i, hidden in enumerate(flags[:len(contour)]):
                    if contour[i].hidden != hidden:
                        contour[i].setHidden(hidden)
                        contour_modified = True
                if contour_modified:
                    section.modified_contours.add(name)
                    modified = True
            if modified:
                # In-place `setHidden` from outside `Section`; see hideObjects.
                section.resyncColumnarStore()
                section.save()
                changed_any = True

        if log_event and changed_any:
            for name in snapshot:
                self.addLog(name, None, "Restore previous visibility")

        if changed_any:
            self.modified = True

        return changed_any

    def hideAllTraces(self, hidden=True, series_states=None, log_event=True):
        """Hide all traces in the entire series.
        
            Params:
                hidden (bool): True if traces are to be hidden
                series_states (dict): optional dict for GUI undo states
                log_event (bool): True if event should be logged
        """
        for snum, section in self.enumerateSections(
            message="Hiding traces..." if hidden else "Unhiding traces...",
            series_states=series_states
        ):
            for trace in section.tracesAsList():
                trace.setHidden(hidden)
            for name in section.contours:
                section.modified_contours.add(name)
            # In-place `setHidden` from outside `Section`; see hideObjects.
            section.resyncColumnarStore()
            section.save()
        
        if log_event:
            self.addLog(None, None, f"{'Hide' if hidden else 'Unhide'} all traces in series")

        self.modified = True

    def importObjectGroups(self, other, regex_filters=[], group_filters=[]):
        """Import the object groups from another series.
        
            Params:
                other (Series): the other series
                regex_filters (list): the regex filters for the objects to include
        """
        self.object_groups.merge(other.object_groups, regex_filters, group_filters)
    
    def importZtraceGroups(self, other, regex_filters=[]):
        """Import the ztrace groups from another series.
        
            Params:
                other (Series): the other series
                regex_filters (list): the regex filters for the ztraces to include
        """
        self.ztrace_groups.merge(other.ztrace_groups, regex_filters)
    
    def importHostTree(self, other, regex_filters=[], restrict_to=[]):
        """Import the host tree from another series.
        
            Params:
                other (Series): the other series
                regex_filters (list): regex filters for objects
                group_filters (list): group filters for objects
        """
            
        self.host_tree.merge(other.host_tree, regex_filters, restrict_to)
    
    def importUserCols(self, other, regex_filters=[], restrict_to=[]):
        """Import user columns."""
        # import the user columns
        merged_user_columns = updateDictLists(
            self.user_columns,
            other.user_columns
        )
        if self.user_columns != merged_user_columns:
            self.user_columns = merged_user_columns

        # import the user column object attributes
        for obj_name, obj_data in other.obj_attrs.items():

            if restrict_to and obj_name not in restrict_to:
                continue
            
            if obj_name not in self.data["objects"]:
                continue

            # check regex filters
            if not passesFilters(obj_name, regex_filters):
                continue

            if "user_columns" in obj_data:
                other_uc = obj_data["user_columns"]
                if obj_name not in self.obj_attrs:
                    self.obj_attrs[obj_name] = {}
                if "user_columns" not in self.obj_attrs[obj_name]:
                    self.obj_attrs[obj_name]["user_columns"] = {}
                self_uc = self.obj_attrs[obj_name]["user_columns"]

                for name, value in other_uc.items():
                    if name not in self_uc:
                        ## if the current series has a user_column setting already, do not override it
                        ## is there a better way to handle this?
                        self_uc[name] = value
    
    def importObjAttrs(self, other, regex_filters=[], restrict_to=[]):
        """Import the object attributes from another series.
        
            Params:
                other (Series): the other series
                regex_filters (list): the regex filters for the objects to include
        """

        for obj_name, obj_data in other.obj_attrs.items():

            if restrict_to and obj_name not in restrict_to:
                continue
            
            if obj_name not in self.data["objects"]:
                continue

            # check regex filters
            if not passesFilters(obj_name, regex_filters):
                continue

            for attr_name, attr_value in obj_data.items():
                # skip user column data
                if attr_name == "user_columns":
                    continue

                if obj_name not in self.obj_attrs:
                    self.obj_attrs[obj_name] = {}
                
                if attr_name not in self.obj_attrs[obj_name]:
                    self.obj_attrs[obj_name][attr_name] = attr_value
                # special case: overwrite self curation if other is more recent
                elif attr_name == "curation":
                    self_date = self.obj_attrs[obj_name]["curation"][-1]
                    other_date = attr_value[-1]
                    if other_date >= self_date:
                        self.obj_attrs[obj_name]["curation"] = attr_value
    
    def importTraces(
            self,
            other, 
            srange : tuple = None, 
            regex_filters : list = [],
            group_filters : list = [],
            threshold : float = 0.95, 
            flag_conflicts : bool = True,
            check_history : bool = True,
            import_obj_attrs : bool = True,
            keep_above : str = "self",
            keep_below : str = "",
            series_states=None,
            log_event=True):
        """Import all the traces from another series.
        
            Params:
                other (Series): the series to import from
                srange (tuple): the range of sections to include in import (exclusive; None for every section)
                regex_filters (list): regex filters for objects
                group_filters (list): group filters for objects
                threshold (float): the overlap threshold
                remove_old_overlaps (bool): True if old traces overlapping new traces should be removed
                flag_conflicts (bool): True if conflicts should be flagged
                check_history (bool): True if history should be checked
                import_obj_attrs (bool): True if object attributes should all be imported
                keep_above (str): the series that is favored for functional duplicates (above the overlap threshold; "self", "other", or "")
                keep_below (str): the series that is favored in the case of a conflict (overlap not reaching the threshold; "self", "other", or "")
                series_states (dict): optional dict of undo states for GUI
                log_event (bool): True if event should be logged
        """
        # # ensure that the two series have the same sections
        # if sorted(list(self.sections.keys())) != sorted(list(other.sections.keys())):
        #     return
        
        ## Get current date and time for tagging
        d, t = getDateTime()
        dt_str = d + "-" + t

        histories = LogSetPair(
            self.getFullHistory(),
            other.getFullHistory()
        )

        ## Supress logging for object creation.
        ##
        ## This must be restored even if the import raises: leaving it set turns
        ## off object create/delete logging for the REST OF THE SESSION, and the
        ## resulting holes in the log then corrupt the divergence detection of
        ## every later import. A crash part way through a merge is bad enough
        ## without it silently making the next merge unsafe too.
        self.data.supress_logging = True

        try:
            for snum, section in self.enumerateSections(
                message="Importing traces...",
                series_states=series_states
            ):
                ## Skip if section not requested or does not exist in other series
                in_srange = srange is None or snum in range(*srange)
                skip = not in_srange or snum not in other.sections

                if skip:
                    continue

                o_section = other.loadSection(snum)  # other section
                histories_param = histories if check_history else None  # skip history if checking is not requested

                section.importTraces(
                    o_section,
                    regex_filters,
                    group_filters,
                    threshold,
                    flag_conflicts,
                    histories_param,
                    keep_above,
                    keep_below,
                    dt_str
                )
        finally:
            ## Un-supress logging for object creation
            self.data.supress_logging = False

        ## Restrict object if with group filters
        restrict_to = []  # empty = no additional restrictions
        
        if group_filters:

            other_groups = other.object_groups.getGroupDict()
            
            for gf in group_filters:
                restrict_to += other_groups[gf]

        ## Import ALL object attributes
        if import_obj_attrs:
            
            self.importObjectGroups(other, regex_filters, group_filters)
            self.importHostTree(other, regex_filters, restrict_to)
            self.importObjAttrs(other, regex_filters, restrict_to)
            self.importUserCols(other, regex_filters, restrict_to)

        ## Import history
        if log_event:
            
            self.addLog(None, None, "Begin importing traces from another series")

            histories.importLogs(
                self,
                traces=True,
                ztraces=False,
                srange=srange,
                regex_filters=regex_filters
            )
            
            self.addLog(None, None, "Finish importing traces from another series")
        
        self.save()
    
    def importZtraces(self, other, regex_filters : list = [], import_attrs : bool = True, series_states=None, log_event=True):
        """Import all the ztraces from another series.
        
            Params:
                other (Series): the series to import from
                regex_filters (list): the filters for the objects to import
                import_attrs (bool): True if ztrace attrs (groups) should be imported
                series_states (SeriesStates): the series undo states from the GUI
                log_event (bool): True if event should be logged
        """
        if series_states:
            series_states.addState()
        
        # gather the mismatched calibrations
        cal_conversions = {}
        for snum in self.sections:
            if snum not in other.sections:
                continue
            s_mag = self.data["sections"][snum]["mag"]
            o_mag = other.data["sections"][snum]["mag"]
            if abs(o_mag - s_mag) > 1e-8:
                cal_conversions[snum] = (o_mag, s_mag)

        
        for o_zname, o_ztrace in other.ztraces.items():
            if not passesFilters(o_zname, regex_filters):
                continue

            # check to ensure all sections included
            sections_check = True
            for x, y, snum in o_ztrace.points:
                if snum not in self.sections:
                    sections_check = False
                    break
            if not sections_check:
                print(f"Skipping {o_zname}: includes sections not in this series.")
                continue

            # modify the ztrace scaling if necessary
            for snum, (o_mag, s_mag) in cal_conversions.items():
                o_ztrace.magScale(snum, o_mag, s_mag)

            # do not replace existing ztraces
            if o_zname not in self.ztraces:
                self.ztraces[o_zname] = o_ztrace.copy()
            # add a new ztrace if same name but dont overlap
            elif not self.ztraces[o_zname].overlaps(o_ztrace):
                n = 1
                while (f"{o_zname}-imported-{n}") in self.ztraces:
                    n += 1
                self.ztraces[f"{o_zname}-imported-{n}"] = o_ztrace.copy()
        
        # import the group data
        if import_attrs:
            self.importZtraceGroups(other, regex_filters)
        
        if log_event:
            # import the history
            histories = LogSetPair(
                self.getFullHistory(),
                other.getFullHistory()
            )
            self.addLog(None, None, "Begin importing ztraces from another series")
            histories.importLogs(
                self,
                traces=False,
                ztraces=True,
                regex_filters=regex_filters
            )
            self.addLog(None, None, "Finish importing ztraces from another series")
        
        self.save()
    
    def importTransforms(self, other, import_as : list, series_states=None, log_event=True):
        """Import transforms from another series.
        
            Params:
                other (series): the series to import transforms from
                import_as (list): the list of (alignment to import, name for alignment in current series)
                series_states (SeriesStates): the series undo states from the GUI
                log_event (bool): True if the event should be logged
        """
        # Which target names already exist, read before the loop. Section.save()
        # feeds section.tforms back into series.data (Series.alignments reads
        # that), so after the first save every imported name looks pre-existing
        # and the create/replace split would come out empty. Both GUI callers
        # already evaluate self.alignments to build the dialog, so reading it
        # here adds no failure mode of its own.
        existing_alignments = set(self.alignments)

        # breakable=False: this rewrites section.tforms on every section, so the
        # undo has to be all-or-nothing. A breakable series state can be
        # dissolved into per-section undos (SeriesStates.undoSection), which
        # would leave the imported alignment present on some sections and absent
        # on others -- a state the Series.alignments property rejects outright.
        for s_snum, s_section in self.enumerateSections(
            message="Importing alignments...",
            series_states=series_states,
            breakable=False
        ):
            if s_snum in other.sections:
                o_section = other.loadSection(s_snum)
                mags_match = abs(o_section.mag - s_section.mag) <= 1e-8
                for alignment, new_name in import_as:
                    if not mags_match:
                        o_section.tforms[alignment].magScale(o_section.mag, s_section.mag)
                    s_section.tforms[new_name] = o_section.tforms[alignment].copy()
            else:  # write blank if section not in other series
                for alignment, new_name in import_as:
                    s_section.tforms[new_name] = Transform.identity()
            s_section.save()

        # Logged after the loop, not before: enumerateSections can raise partway
        # through (a section that will not load), and a log line claiming an
        # import that did not finish is worse than no line at all.
        if log_event:
            # Target names, not source names. The log describes this series, and
            # a source name the user renamed on the way in names an alignment
            # that does not exist here. The two are the same name on every
            # import that does not rename, which is the common case.
            created = [new_name for _, new_name in import_as
                       if new_name not in existing_alignments]
            replaced = [new_name for _, new_name in import_as
                        if new_name in existing_alignments]
            if created:
                created_str = " ".join(created)
                self.addLog(None, None, f"Import alignments {created_str} from another series")
            if replaced:
                replaced_str = " ".join(replaced)
                self.addLog(None, None, f"Update alignments {replaced_str} from another series")

        self.save()
    
    def importBC(self, other, import_as : list, log_event=True):
        """Import brightness/contrast profiles from another series.
        
            Params:
                other (series): the series to import transforms from
                import_as (list): the list of (profile to import, name for profile in current series)
                log_event (bool): True if the event should be logged
        """
        for s_snum, s_section in self.enumerateSections(message="Importing brightness/contrast profiles..."):
            if s_snum in other.sections:
                o_section = other.loadSection(s_snum)
                for profile, new_name in import_as:
                    s_section.bc_profiles[new_name] = o_section.bc_profiles[profile].copy()
            else:  # write blank b/c if section not in other series
                for profile, new_name in import_as:
                    s_section.bc_profiles[new_name] = (0, 0)
            s_section.save()

        if log_event:
            profiles_str = " ".join(p[0] for p in import_as)
            self.addLog(None, None, f"Import brightness-contrast profiles {profiles_str} from another series")

        self.save()
    
    def importPalettes(self, other, import_as, log_event=True):
        """Import the palettes from another series.
        
            Params:
                other (Series): the series to import from
                import_as (list): the list of (palette to import, name for palette in current series)
                log_event (bool): True if event should be logged
        """
        for palette, new_name in import_as:
            trace_list = other.palette_traces[palette]
            self.palette_traces[new_name] = trace_list.copy()
        
        if log_event:
            palettes_str = " ".join(p[0] for p in import_as)
            self.addLog(None, None, f"Import palettes {palettes_str} from another series")
        
        self.save()
    
    def importFlags(self, other, srange, series_states=None, log_event=True):
        """Import flags from another series.
        
            Params:
                other (Series): the series to import from
                srange (tuple): the range of sections to import from
                series_states (SeriesStates): the series undo states from the GUI
                log_event (bool): True if event should be logged
        """
        for snum, section in self.enumerateSections(
            message="Importing flags...",
            series_states=series_states
        ):
            if snum not in other.sections:  # skip if section does not exist in other series
                continue
            if snum not in range(*srange):  # skip if not in requested section range
                continue

            new_flag_pool = section.flags.copy()
            o_section = other.loadSection(snum)  # sending section
            mags_match = abs(o_section.mag - section.mag) <= 1e-8

            for o_flag in o_section.flags:
                # adjust the flag to match magnification if necessary
                if not mags_match:
                    o_flag.magScale(o_section.mag, section.mag)
                eq_found = False
                for s_flag in section.flags:
                    if s_flag.equals(o_flag):
                        eq_found = True
                        # if two of the same found, use one with more comments
                        # otherwise, just keep the self flag
                        slen = len(s_flag.comments)
                        olen = len(o_flag.comments)
                        if olen > slen:
                            new_flag_pool.append(o_flag)
                            new_flag_pool.remove(s_flag)
                            section.flags_modified = True
                        break
                if not eq_found:
                    new_flag_pool.append(o_flag)
                    section.flags_modified = True

            if section.flags_modified:
                section.flags = new_flag_pool
                section.save()
        
        if log_event:
            self.addLog(None, None, "Import flags from another series")

    @staticmethod
    def getDefaultPaletteTraces() -> list:
        """Return the default palette trace list.
        
            Returns:
                (list): the list of the default palette traces
        """
        palette_traces = []
        for l in default_traces:
            palette_traces.append(Trace.fromList(l.copy()))
        return palette_traces * 2
    
    def getRecentSegGroup(self) -> str:
        """Return the most recent segmentation group name.
        
            Returns:
                (str): the name of the most recent segmentation group
        """
        g = None
        for group in self.object_groups.getGroupList():
            if group.startswith("seg_") and (
                g is None or group > g
            ):
                g = group
        return g
    
    def deleteDuplicateTraces(self, threshold : float, include_locked=False, series_states=None, log_event=True):
        """Delete all duplicate traces in the series (keep tags).
        
            Params:
                threshold (float): the threshold for overlapping traces to be considered duplicates
                series_states (dict): optional dict of undo states for GUI
                log_event (bool): True if event should be logged
        """
        removed = {}
        for snum, section in self.enumerateSections(
            message="Removing duplicate traces...",
            series_states=series_states
        ):
            found_on_section = False
            for cname in section.contours:
                if not include_locked and self.getAttr(cname, "locked"):
                    continue
                i = 1
                while i < len(section.contours[cname]):
                    trace1 = section.contours[cname][i]
                    # check against all previous traces
                    for j in range(i-1, -1, -1):
                        trace2 = section.contours[cname][j]
                        # if overlaps, remove trace and break
                        if trace1.overlaps(trace2, threshold=threshold,
                                           mag=section.mag):
                            if snum not in removed:
                                removed[snum] = set()
                            removed[snum].add(cname)
                            found_on_section = True
                            trace1.mergeTags(trace2)
                            section.removeTrace(trace2)
                            i -= 1
                            break
                    i += 1
            if found_on_section:
                # `section.removeTrace(trace2)` is a hooked mutation and the
                # store follows it, but `trace1.mergeTags(trace2)` above rewrote
                # `tags` in place on a trace the section keeps -- outside
                # `Section`, so nothing repaired trace1's row. It only diverges
                # when the two duplicates carry different tags, which is exactly
                # the messy series this clean-up is run on. Without the rebuild
                # the save below logs the drift instead of absorbing it silently
                # (D11), and the user's next edit to trace1 raises
                # `ColumnarDualWriteMismatch`.
                section.resyncColumnarStore()
                section.save()

        if log_event:
            self.addLog(None, None, "Delete all duplicate traces")

        return removed

    def addLog(self, obj_name : str, snum : int, event : str):
        """Add a log to the log set.
        
            Params:
                obj_name (str): the name of the modified object
                snum (int): the section number of the event
                event (str): the description of the event
        """
        self.log_set.addLog(self.user, obj_name, snum, event)

        # update the user data
        if obj_name:
            self.setAttr(obj_name, "last_user", self.user)
            self.editors.add(self.user)
    
    def getFullHistory(self, skip_corrupt : bool = False) -> LogSet:
        """Get all the logs for the series.

            Params:
                skip_corrupt (bool): True to drop the rows that will not parse
                    and keep the rest (the dropped rows land in the returned
                    set's skipped_rows); False, the default, to raise on the
                    first one. LogSet.fromList says which a caller wants.
            Returns:
                (LogSet): the object containing the full history
        """
        csv_fp = os.path.join(self.hidden_dir, "existing_log.csv")
        with open(csv_fp, "r", encoding="utf-8", errors="replace") as f:
            log_list = f.readlines()[1:]
        full_hist = LogSet.fromList(log_list, skip_corrupt=skip_corrupt)
        for log in self.log_set.all_logs:
            full_hist.addExistingLog(log)
        
        return full_hist

    def setCuration(self, names : list, cr_status : str, assign_to : str = ""):
        """Set the curation status for a set of objects.
        
            Params:
                names (list): the object names to mark as curated
                cr_status(str): the curation state to set
                asign_to (str): the user to assign to if Needs Curation
        """
        for name in names:
            if cr_status == "":
                self.setAttr(name, "curation", None)
                self.log_set.removeCuration(name)
            elif cr_status == "Needs curation":
                self.setAttr(name, "curation", (False, assign_to, getDateTime()[0]))
                # record the assignee in the log event so that
                # updateCurationFromHistory can restore it (older logs carry
                # the bare event and restore with no assignee)
                if assign_to:
                    event = f"Mark as needs curation (assigned to {assign_to})"
                else:
                    event = "Mark as needs curation"
                self.addLog(name, None, event)
            elif cr_status == "Curated":
                self.setAttr(name, "curation", (True, self.user, getDateTime()[0]))
                self.addLog(name, None, "Mark as curated")
    
    def reorderSections(self, d : dict = None, log_event=True):
        """Reorder the sections.
        
            Params:
                d (dict): old_snum : new_snum for every section
                log_event (bool): True if event should be logged
        """
        if not d:
            d = dict(tuple((snum, i) for i, snum in enumerate(self.sections.keys())))
        
        # rename the section files
        for old_snum, new_snum in d.items():
            os.rename(
                os.path.join(self.hidden_dir, f"{self.name}.{old_snum}"),
                os.path.join(self.hidden_dir, f"{self.name}.{new_snum}.temp")
            )
        # remove temp ext
        for f in os.listdir(self.hidden_dir):
            if f.endswith(".temp"):
                updated_f = f[:-len(".temp")]
                os.rename(
                    os.path.join(self.hidden_dir, f),
                    os.path.join(self.hidden_dir, updated_f)
                )
        
        # update the ztraces
        for ztrace in self.ztraces.values():
            pts = []
            for pt in ztrace.points:
                pts.append((pt[0], pt[1], d[pt[2]]))
            ztrace.points = pts
                
        # create the new sections dict
        self.sections = {}
        for snum in sorted(d.values()):
            self.sections[snum] = f"{self.name}.{snum}"

        self.current_section = d[self.current_section]

        if log_event:
            self.addLog(None, None, "Reorder sections")
    
    def insertSection(self, index : int, src : str, mag : float, thickness : float, log_event=True):
        """Create a new section.
        
            Params:
                index (int): the index of the new section
                src (str): the path to the image for the new section
                mag (float): the mag of the new section
                thickness (float): the thickness of the new section
                log_event (bool): True if event should be logged
        """
        # create the new section object
        max_snum = max(self.sections.keys()) + 1
        Section.new(
            self.name,
            max_snum,
            src,
            mag,
            thickness,
            self.hidden_dir
        )
        self.sections[max_snum] = f"{self.name}.{max_snum}"

        # reorder the sections
        if index in self.sections:
            reorder = dict(
                (n, n + 1 if n >= index else n) for n in self.sections
            )
        else:
            reorder = dict((n, n) for n in self.sections)
        reorder[max_snum] = index
        self.reorderSections(reorder, log_event=False)

        if log_event:
            self.addLog(None, None, "Insert section")
    
    def getAttr(self, name : str, attr_name : str, ztrace=False):
        """Get the attributes for an object in the series.
        
            Params:
                obj_name (str): the name of the object
                attr_name (str): the name of the attribute to get
            Returns:
                the request attribute
        """
        if ztrace:
            attrs = self.ztrace_attrs
        else:
            attrs = self.obj_attrs
        
        if not name in attrs or attr_name not in attrs[name]:
            # return defaults if not set
            if attr_name == "3D_mode":
                return "surface"
            if attr_name == "3D_opacity":
                return 1
            elif attr_name == "last_user":
                return ""
            elif attr_name == "curation":
                return None
            elif attr_name == "comment":
                return ""
            elif attr_name == "alignment":
                return None
            elif attr_name == "locked":
                return False
            elif attr_name == "user_columns":
                return {}
            else:
                return
        else:
            return attrs[name][attr_name]
    
    def setAttr(self, name : str, attr_name : str, value, ztrace=False):
        """Set the attributes for an object in the series.
        
            Params:
                obj_name (str): the name of the object
                attr_name (str): the name of the attribute to set
                value: the value to set for the attributes
        """
        if ztrace:
            attrs = self.ztrace_attrs
        else:
            attrs = self.obj_attrs
        
        if name not in attrs:
            attrs[name] = {}
        attrs[name][attr_name] = value
        if value is None:
            del(attrs[name][attr_name])
            if not attrs[name]:
                del(attrs[name])
    
    def removeObjAttrs(self, name : str):
        """Delete all attrs associated with an object name.

        (Automatically called when object is deleted.)
        
            Params:
                name (str): the name of the object
        """
        # object groups
        self.object_groups.removeObject(name)

        # obj_attrs
        #
        # pop, not del: this is the only one of the three cleanups here that
        # required the name to be present. ObjGroupDict.removeObject reaches
        # getObjectGroups, which returns an empty set for a name it does not
        # know, HostTree.removeObject returns early on one, and the sibling
        # renameObjAttrs guards with `if old_name in self.obj_attrs`. A del also
        # sits *between* the other two, so a missing entry did not fail cleanly:
        # it left object_groups stripped, host_tree untouched, and a KeyError
        # propagating out of Section.save().
        #
        # The invariant that made the del safe is still an invariant, and
        # tests/test_remove_obj_attrs_guard.py pins it rather than leaving it to
        # an incidental KeyError. The only caller, SeriesData.updateSection,
        # calls addLog(obj_name, None, "Delete object") on the line above, and
        # addLog writes setAttr(obj_name, "last_user", self.user), which creates
        # obj_attrs[obj_name]. That holds only while obj_name is truthy and
        # series.user is not None; neither is checked at the call site.
        self.obj_attrs.pop(name, None)

        # object host
        self.host_tree.removeObject(name)

    def renameObjAttrs(self, old_name, new_name):
        """Change the attibutes for an object that was renamed.

        (Automatically called when object is renamed.)
        
            Params:
                old_name (str): the original name of the object
                new_name (str): the new name for the object
        """
        # if new_name in self.data["objects"]:
        #     return  # do not overwrite if object exists
        
        # object groups
        groups = self.object_groups.getObjectGroups(old_name)
        for group in groups:
            self.object_groups.add(group, new_name)
        
        # import the object attributes
        if old_name in self.obj_attrs:
            if new_name not in self.obj_attrs:
                self.obj_attrs[new_name] = {}

            # find non-existing attributes and import them in
            old_attrs = self.obj_attrs[old_name]
            new_attrs = self.obj_attrs[new_name]
            for attr, value in old_attrs.items():
                if attr not in new_attrs:
                    new_attrs[attr] = value
            
            # find non-existing user columns and import them in
            if "user_columns" in old_attrs:
                if "user_columns" not in new_attrs:
                    new_attrs["user_columns"] = {}
                old_cols = old_attrs["user_columns"]
                new_cols = new_attrs["user_columns"]
                for col_name, opt in old_cols.items():
                    if col_name not in new_cols:
                        new_cols[col_name] = opt

            self.obj_attrs[new_name] = self.obj_attrs[old_name].copy()
        
        # rename obj hosts
        self.host_tree.renameObject(old_name, new_name)
    
    def getAlignments(self) -> list:
        """Return a list of alignment names."""
        snum = list(self.sections.keys())[0]  # grab valid section number
        sec_data = self.data["sections"]
        anames = list(sec_data[snum]["tforms"].keys())
        return anames

    def updateCurationFromHistory(self):
        """Update curation status of all objects from the history."""
        full_hist = self.getFullHistory().all_logs

        marked_objs = set()
        for log in reversed(full_hist):
            name = log.obj_name
            if not name or name in marked_objs:
                continue

            if "Mark as curated" in log.event:
                if name not in self.obj_attrs:
                    self.obj_attrs[name] = {}
                if "curation" not in self.obj_attrs[name] or not self.obj_attrs[name]["curation"][0]:  # overwrite if at previous step in curation flow
                    self.obj_attrs[name]["curation"] = (True, log.user, log.date)
                marked_objs.add(name)
            elif "Mark as needs curation" in log.event:
                if name not in self.obj_attrs:
                    self.obj_attrs[name] = {}
                if "curation" not in self.obj_attrs[name]:
                    # recover the assignee that setCuration records in the
                    # event text; logs from before the assignee was recorded
                    # carry the bare event and restore with no assignee
                    m = re.fullmatch(
                        r"Mark as needs curation \(assigned to (.+)\)",
                        log.event
                    )
                    assign_to = m.group(1) if m else ""
                    self.obj_attrs[name]["curation"] = (False, assign_to, log.date)
                marked_objs.add(name)
    
    def _settingsStore(self):
        """Return the SettingsStore backing this series' settings.

        Defaults to a lazily-created QSettings-backed store (behavior identical
        to the previous direct QSettings use); a caller or test may inject a
        different store via setSettingsStore().
        """
        store = getattr(self, "_settings_store", None)
        if store is None:
            store = _default_settings_store()
        return store

    def setSettingsStore(self, store):
        """Inject a SettingsStore for this series (e.g. headless use or tests).

        Pass None to fall back to the default QSettings-backed store.
        """
        self._settings_store = store

    def _progressReporterFactory(self):
        """Return the ProgressReporter factory backing this series' progress.

        Defaults to the lazily-resolved Qt-backed factory (behavior identical
        to the previous direct getProgbar use); a caller or test may inject a
        different factory (e.g. NullProgressReporter) via setProgressReporter().
        """
        factory = getattr(self, "_progress_reporter_factory", None)
        if factory is None:
            factory = _default_progress_reporter_factory()
        return factory

    def setProgressReporter(self, factory):
        """Inject a ProgressReporter factory for this series (headless/tests).

        ``factory`` is a callable ``(text, cancel) -> ProgressReporter`` (e.g.
        the NullProgressReporter class). Pass None to fall back to the default
        Qt-backed reporter.
        """
        self._progress_reporter_factory = factory

    def _notifier(self):
        """Return the Notifier backing this series' user notifications.

        Defaults to a lazily-created Qt-backed notifier (behavior identical to
        the previous inline notify()/QApplication guard); a caller or test may
        inject a different notifier (e.g. NullNotifier) via setNotifier().
        """
        notifier = getattr(self, "_notifier_impl", None)
        if notifier is None:
            notifier = _default_notifier()
        return notifier

    def setNotifier(self, notifier):
        """Inject a Notifier for this series (e.g. headless use or tests).

        Pass None to fall back to the default Qt-backed notifier.
        """
        self._notifier_impl = notifier

    def _surfaceSaveError(self, fp : str, err : Exception):
        """Show a 'Save failed' message to the user (best-effort, headless-safe).

            Params:
                fp (str): the filepath that failed to save
                err (Exception): the error that occurred
        """
        message = (
            f"Save failed: {err}\n\n"
            f"The existing file was left unchanged:\n{fp}"
        )
        try:
            from PyReconstruct.modules.backend.func.error_report import (
                build_error_report_from_exception,
            )
            report = build_error_report_from_exception(err)
        except Exception:
            report = message  # report builder must never mask the real error
        try:
            if self._notifier().notify_error(message, report):
                return
        except Exception:
            pass  # never let the notification itself mask the real error
        # headless: don't block on a dialog/input -- just report it
        print(message)

    @staticmethod
    def _fromDefaults(defaults : dict, option_name : str):
        """Return a value out of a class-level defaults dict, never by reference.

        `qsettings_defaults` and `qsettings_series_defaults` are shallow copies
        of the dicts in `default_settings.py`, so a list or dict value in one of
        them is a single object shared by every Series in the process. Five
        entries are mutable containers (`pointer`, `grid`, `flag_color`,
        `autoseg_color_palette`, `recently_opened_series`), and a caller that
        mutates what it was handed rewrites the shipped default for everyone
        else: `addToRecentSeries` does exactly that, with `remove`, `insert` and
        `pop` on the list it got back.

        Shallow is enough. Every mutable default is a flat list of scalars.
        """
        value = defaults[option_name]
        return copy(value) if isinstance(value, (list, dict)) else value

    def getOption(self, option_name : str, get_default=False):
        """Get an option from the series (or computer)

            Params:
                option_name (str): the name of the option
                get_default (bool): True if only default should be returned
        """
        ## Check for internal series option first
        if option_name in self.options:
            
            if get_default:
                opt = Series.getEmptyDict()["options"][option_name]
            else:
                raw = self.options[option_name]
                opt = copy(raw) if isinstance(raw, (list, dict)) else raw
                if "_columns" in option_name:
                    # All five *_columns options live here, so the check at the
                    # bottom of this method never ran for any of them: this
                    # branch returns first. Kept in both places so that an option
                    # moved to the settings store later stays covered.
                    #
                    # The check reads `opt`, the copy, not `self.options[...]`.
                    # Same shape either way today, but the copy is what the caller
                    # receives, so it is the thing worth validating.
                    _checkColumnsOption(option_name, opt)

            return opt

        ## Get sane settings and defaults
        if option_name in Series.qsettings_series_defaults:

            if self.isWelcomeSeries():  # return defaults if accessing series setting
                return Series._fromDefaults(
                    Series.qsettings_series_defaults, option_name
                )

            scope_code = self.code
            defaults = Series.qsettings_series_defaults

        elif option_name in Series.qsettings_defaults:

            scope_code = None
            defaults = Series.qsettings_defaults

        else:

            return None

        store = self._settingsStore()

        ## Get the option
        if get_default:
            return Series._fromDefaults(defaults, option_name)
        elif store.contains(scope_code, option_name):
            option_type = type(defaults[option_name])
            option = store.value(
                scope_code,
                option_name,
                str if option_type in (dict, list, tuple) else option_type
            )
            if option_type in (dict, list, tuple):
                option = json.loads(option)
        else:
            option = Series._fromDefaults(defaults, option_name)
            self.setOption(option_name, option)
        
        ## CHECKS FOR UPDATES

        ## Check for disallowing laplacian smoothing
        if option_name == "3D_smoothing" and option == "laplacian":
            option = "humphrey"
            self.setOption(option_name, option)

        ## Check for tables
        if "_columns" in option_name:
            _checkColumnsOption(option_name, option)

        return option
                    
    def setOption(self, option_name : str, value):
        """Set an option
        
            Params:
                options_name (str): the name of the option
                value: the value to set the option as
        """
        # check for internal series option first
        if option_name in self.options:
            self.options[option_name] = value
            return
        
        # convert format if necessary
        value_type = type(value)
        if value_type in (dict, list, tuple):
            value = json.dumps(value)
        
        # get the proper scope
        if option_name in Series.qsettings_series_defaults:
            if self.isWelcomeSeries():
                return  # prevent setting for the welcome series
            scope_code = self.code
        elif option_name in Series.qsettings_defaults:
            scope_code = None
        else:
            return

        self._settingsStore().set_value(scope_code, option_name, value)
    
    @property
    def user(self):
        return self.getOption("username")

    @user.setter
    def user(self, value):
        self.setOption("username", value)
    
    @property
    def avg_mag(self):
        return self.data.getAvgMag()

    @property
    def avg_thickness(self):
         return self.data.getAvgThickness()

    def exportTracePaletteCSV(self, fp : str, palette_name : str = None):
        """Export the trace palette as a CSV file.
        
            Params:
                fp (str): the filepath for the CSV file
                palette_name (str): the name of the palette to export (default: current palette)
        """
        if palette_name is None:
            palette_name = self.palette_index[0]
        
        traces = self.palette_traces[palette_name].copy()
        csv_str = "Name,Color,Fill,Tags,X,Y\n"

        for trace in traces:
            trace : Trace
            name = trace.name
            color = " ".join(str(n) for n in trace.color)
            fill = " ".join(trace.fill_mode)
            tags = " ".join(trace.tags)
            x = " ".join(str(x) for x, y in trace.points)
            y = " ".join(str(y) for x, y in trace.points)
            csv_str += ",".join([name, color, fill, tags, x, y]) + "\n"
        
        with open(fp, "w", encoding="utf-8") as f:
            f.write(csv_str)
    
    def importTracePaletteCSV(self, fp : str, palette_name : str = None):
        """Import the trace palette from a CSV file.
        
            Params:
                fp (str): the path to the CSV file
                palette_name (str): the name for the new palette (default: overwrite current)
        """
        if palette_name is None:
            palette_name = self.palette_index[0]
        
        # errors="replace": a palette CSV exported by an older build on a
        # non-UTF-8 locale is decoded leniently rather than crashing the import
        # (mirrors getFullHistory's log reader); new exports are always UTF-8.
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[1:]
        
        trace_list = []

        for line in lines:
            l = line.split(",")
            name = l[0]
            color = tuple(int(n) for n in l[1].split())
            fill = tuple(l[2].split())
            tags = set(l[3].split())
            x = [float(n) for n in l[4].split()]
            y = [float(n) for n in l[5].split()]

            t = Trace(name, color)
            t.fill_mode = fill
            t.tags = tags
            t.points = list(zip(x, y))
            trace_list.append(t)
        
        self.palette_traces[palette_name] = trace_list

    def exportObjectsCSV(self, output_fp: Union[str, Path]="", notify: bool=False) -> None:
        """Export all object data as CSV file."""

        self.objects.exportCSV(str(output_fp))

        if notify:

            print(f"CSV exported to: {str(output_fp)}")

    def exportZtracesCSV(self, output_fp: Union[str, Path]="", notify:bool=False) -> None:
        """Export all z-trace data as CSV file."""

        sep = "|"

        out_str = f"series{sep}ztrace{sep}start{sep}end{sep}length\n"

        for _, z in self.ztraces.items():

            start = z.getStart()
            end = z.getEnd()
            z_len = round(z.getDistance(self), 5)
            
            out_str += f"{self.code}{sep}{z.name}{sep}{start}{sep}{end}{sep}{z_len}\n"

        if output_fp:

            with open(str(output_fp), "w") as f:
                f.write(out_str)

        if notify:

            print(f"CSV exported to {str(output_fp)}")

    def getEditorsFromHistory(self):
        """Get the set of editors from the history of the series.

            Returns:
                (set): the usernames named by the rows that could be read

        A row that will not parse costs only itself. This is a union over the
        rows, so one bad row says nothing about the others, and abandoning the
        file on it -- what the bare `except: return set()` here used to do --
        took every OTHER user's well-formed entry with it and left the series
        claiming they had never edited it. One legacy object name holding the
        ", " Log.fromStr splits on is enough to trigger that, and __init__
        calls this exactly when the stored editors list is empty, so the empty
        set it returned was then stored as the answer.

        Failing to read the file at all is the different case and still yields
        an empty set: there are no other rows to keep.
        """
        editors = set()
        try:
            ls = self.getFullHistory(skip_corrupt=True)
        except OSError:
            print("ERROR: cannot read history. Skipping editors update...")
            return set()
        if ls.skipped_rows:
            print(
                f"WARNING: {len(ls.skipped_rows)} unreadable history row(s) "
                "skipped; editors from the remaining rows were kept."
            )
        for l in ls.all_logs:
            if l.user:
                editors.add(l.user)
        return editors

    def getBackupPath(self, comment : str = "", check_existing : bool = True):
        """Get the file path for a backup file for this series.
        
            Params:
                comment (str): an optional comment to add to the end of the filename.
                check_existing (bool): check for existing file and append numbers if exists
        """
        fname_list = []

        if self.getOption("backup_prefix"):
            s = self.getOption("backup_prefix_str")
            if s: fname_list.append(s)

        if self.getOption("backup_series"):
            fname_list.append(self.code)

        if self.getOption("backup_filename"):
            fname_list.append(self.name)
        
        now = datetime.utcnow() if self.getOption("utc") else datetime.now()

        if self.getOption("backup_date"):
            date = now.strftime(self.getOption("backup_date_str"))
            fname_list.append(date)
        
        if self.getOption("backup_time"):
            time = now.strftime(self.getOption("backup_time_str"))
            fname_list.append(time)
        
        if self.getOption("backup_user"):
            fname_list.append(self.user)

        if self.getOption("backup_suffix"):
            s = self.getOption("backup_suffix_str")
            if s: fname_list.append(s)
        
        if comment:
            fname_list.append(comment)
        
        dl = self.getOption("backup_delimiter")
        fname_list = [s.strip() for s in fname_list]
        fname = dl.join(fname_list)
        fname = dl.join(fname.split())

        folder = self.getOption("backup_dir")
        fp = os.path.join(folder, fname)

        if check_existing and os.path.isfile(f"{fp}.jser"):
            n = 1
            while os.path.isfile(f"{fp}-{n:02d}.jser"):
                n += 1
            fp = f"{fp}-{n:02d}.jser"
        else:
            fp += ".jser"

        return fp
    
    def addUserCol(self, col_name : str, opts : list, log_event=True):
        """Add a user-defined column to the series.
        
            Params:
                col_name (str): the name of the column to add
                opts (list): the possible strings to put into the column
        """
        col_name = col_name.replace(" ", "_")
        for i, opt in enumerate(opts):
            opts[i] = opt.replace(" ", "_")
        
        # refuse to add if already exists
        if col_name in self.user_columns:
            return
        
        self.user_columns[col_name] = opts
        
        if log_event:
            self.addLog(None, None, f"Add user column {col_name}")
    
    def removeUserCol(self, col_name : str, log_event=True):
        """Remove a user-defined column.
        
            Params:
                col_name (str): the name of the column to remove
        """
        if col_name in self.user_columns:
            del(self.user_columns[col_name])

        # iterate through all object attributes and remove the column data
        for attrs in self.obj_attrs.values():
            if "user_columns" in attrs and col_name in attrs["user_columns"]:
                del(attrs["user_columns"][col_name])
        
        if log_event:
            self.addLog(None, None, f"Delete user column {col_name}")
        
    def editUserCol(self, col_name : str, new_name : str, new_opts : list, log_event=True):
        """Edit a user-defined column.
        
            Params:
                col_name (str): the original name of the column
                new_name (str): the new name for the column
                new_opts (list): the new options for the column
        """
        new_name = new_name.replace(" ", "_")
        for i, opt in enumerate(new_opts):
            new_opts[i] = opt.replace(" ", "_")

        # refuse to edit if column does not exist or if new name already exists
        if col_name not in self.user_columns:
            return
        if new_name != col_name and new_name in self.user_columns:
            return
        
        if col_name != new_name:
            # rename the column in the user_columns dict
            self.user_columns[new_name] = self.user_columns[col_name]
            del(self.user_columns[col_name])
            # rename the column in all obj attrs
            for attrs in self.obj_attrs.values():
                if "user_columns" in attrs and col_name in attrs["user_columns"]:
                    attrs["user_columns"][new_name] = attrs["user_columns"][col_name]
                    del(attrs["user_columns"][col_name])
        col_name = new_name

        if self.user_columns[col_name] != new_opts:
            # replace the options in the user_columns dict
            self.user_columns[col_name] = new_opts
            # remove old options from all obj attrs
            for attrs in self.obj_attrs.values():
                if "user_columns" in attrs and col_name in attrs["user_columns"]:
                    if attrs["user_columns"][col_name] not in new_opts:
                        del(attrs["user_columns"][col_name])
        
        if log_event:
            self.addLog(None, None, f"Edit user column {new_name}")
    
    def getUserColAttr(self, obj_name : str, col_name : str):
        """Get the user-defined column attribute of an object.

            Params:
                obj_name (str): the name of the object
                col_name (str): the name of the user-defined column
        """
        column_data = self.getAttr(obj_name, "user_columns")
        if col_name not in column_data:
            return None
        else:
            return column_data[col_name]
    
    def setUserColAttr(self, obj_name : str, col_name : str, value : str):
        """Set the user defined column attribute of an object.
        
            Params:
                obj_name (str): the name of the object
                col_name (str): the column of the object
                value (str): the value to set the object column attribute
        """
        value = value.replace(" ", "_")
        column_data = self.getAttr(obj_name, "user_columns")
        if value:
            column_data[col_name] = value
        elif not value and col_name in column_data:
            del(column_data[col_name])
        self.setAttr(obj_name, "user_columns", column_data)
    
    def exportUserColsText(self, out_fp : str):
        """Export the user columns to a text file."""
        s = ""
        for col_name, opts in self.user_columns.items():
            s += f"{col_name}: {', '.join(opts)}\n"
        with open(out_fp, "w", encoding="utf-8") as f:
            f.write(s)
    
    def importUserColsText(self, fp : str):
        """Import user columns from a text file."""
        # FORMAT:
        # name: option, option, option
        # name: option, option, option
        new_columns = {}
        # errors="replace": tolerate a user-columns file exported by an older
        # build under a non-UTF-8 locale instead of failing the import.
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            # skip blank lines:
            if not line:
                continue
            try:
                col_name, opts_str = tuple(line.split(": "))
                col_name = col_name.replace(" ", "_")
                opts = opts_str.split(", ")
                opts = [opt.replace(" ", "_") for opt in opts]
                new_columns[col_name] = opts
            except:
                raise Exception("Incorrect user columns text formatting.")
        
        # update the user columns
        for col_name, opts in new_columns.items():
            if col_name not in self.user_columns:
                self.user_columns[col_name] = opts
    
    def deleteSections(self, section_numbers : list, log_event=True):
        """Delete sections in the series.

            Params:
                section_numbers (list): the section numbers to delete. Repeats
                    are collapsed; a number the series does not have raises
                    KeyError before anything is deleted.
                log_event (bool): True if the deletions should be logged
        """
        # Normalize and validate the whole request before deleting anything.
        #
        # Every pass of the loop below removes a file and an index entry, and the
        # z-trace repointing only runs once the loop has finished, so a raise
        # part-way through leaves a series that is half deleted: section files
        # gone, z-traces still carrying points on sections that no longer exist,
        # and no route back, because the caller has already accepted the
        # no-undo warning and saved. A repeated section number produced exactly
        # that, since the second copy reached self.sections[snum] after the first
        # had removed it. Measured on a 5-section series, deleteSections([2, 2]):
        # KeyError, s.2 deleted, and all four z-traces left with a point on
        # section 2.
        #
        # Repeats are the caller's normal failure mode rather than a hypothetical
        # one: the section list is a multi-column, cell-selectable table, so a
        # selected row yielded the same section number once per column until
        # DataTable.selectedRows started de-duplicating by row. That fix belongs
        # where it is, but the caller is not the right place for this operation's
        # atomicity to live.
        snums = list(dict.fromkeys(section_numbers))
        missing = [snum for snum in snums if snum not in self.sections]
        if missing:
            raise KeyError(
                f"cannot delete section(s) {missing}: not in this series"
            )

        for snum in snums:
            # delete the file
            filename = self.sections[snum]
            os.remove(os.path.join(self.getwdir(), filename))
            # delete link to file
            del(self.sections[snum])
            if log_event:
                self.addLog(None, snum, "Delete section")

        # remove ztrace links to sections
        deleted = set(snums)
        for ztrace in self.ztraces.values():
            pts = []
            for pt in ztrace.points:
                if pt[2] not in deleted:
                    pts.append(pt)
            ztrace.points = pts
    
    def splitObjectNames(self, name : str) -> list:
        """The object names `splitObject` would write its traces into.

        Numbered `_1`..`_N` over the object's trace count, zero-padded to that
        count's width, which is exactly how the split loop below names them: it
        reads the same `data.getCount(name)` for its padding and walks the same
        1..N, so the two cannot drift apart.

            Params:
                name (str): the object that would be split
            Returns:
                (list): the destination names, empty if the object has no traces
        """
        count = self.data.getCount(name)

        if not count:  # None for an unknown object, 0 for an empty one
            return []

        digits = len(str(count))

        return [f"{name}_{n:0{digits}d}" for n in range(1, count + 1)]

    def splitObject(self, name : str, series_states=None, log_event=True):
        """Split an object into one object per trace.

        Refuses outright if any generated destination is locked. All-or-nothing
        for the same reason as `copyObjects`: a split is one operation, and
        splitting all of it but the traces that collide would be worse than not
        splitting at all.

            Params:
                name (str): the name of the object to split
            Returns:
                (set): the names of the new objects, empty if refused
        """
        if self.lockedDestinations(self.splitObjectNames(name)):
            return set()

        n = 1
        digits = len(str(self.data.getCount(name)))
        new_names = set()

        ## Get original obj attrs
        alignment, obj_groups, host = self.objects.getSourceAttrs(name)

        for snum, section in self.enumerateSections(
            message="Splitting object...",
            series_states=series_states,
            section_numbers=self.getObjectSections([name])
        ):
            if name in section.contours:
                traces = section.contours[name].getTraces()
                for trace in traces:
                    section.removeTrace(trace, log_event=False)
                    trace = trace.copy()
                    trace.name = f"{trace.name}_{n:0{digits}d}"
                    new_names.add(trace.name)  # keep track of all the new object names
                    section.addTrace(trace, log_event=False)
                    n += 1
                section.save()

        ## Assign original attrs to new objects
        for obj in new_names:
            self.objects.assignCopyAttrs(obj, alignment, obj_groups, host)
        
        if log_event:
            self.addLog(name, None, "Split into individual objects per trace")
        
        # Drop the source's obj_attrs entry if the split emptied the object.
        #
        # The split leaves no traces under the source name, so the last
        # section.save() above reaches SeriesData.updateSection, which drops the
        # object from data["objects"] and calls removeObjAttrs(name) to clear its
        # group membership, its obj_attrs entry and its host_tree entry. addLog
        # then writes setAttr(name, "last_user", user), which re-creates
        # obj_attrs[name] *after* that cleanup, keyed on an object that no longer
        # exists. obj_attrs is serialized into the .jser, so the entry outlives
        # the session, accumulates one key per split, and re-attaches stale
        # provenance to any object later given this name.
        #
        # The log cannot simply be moved above the loop instead: updateSection
        # emits a "Delete object" log for the emptied source, and LogSet.addLog
        # drops every earlier log for that object name, so logging first would
        # lose the split event itself.
        #
        # deleteAllTraces and deleteObjects both end with a clean obj_attrs (the
        # same "Delete object" log is written by updateSection immediately before
        # removeObjAttrs, so their stamp is the one that gets cleared). A split
        # empties an object the same way and should leave the same nothing.
        if name not in self.data["objects"]:
            self.obj_attrs.pop(name, None)

        return new_names

    def setObjHosts(self, obj_names : list, host_names : list):
        """Set the host for object(s).
        
            Params:
                obj_names (list): the names of the objects with hosts to set
                host_name (list): the name of the host to set
        """
        # ensure that hosts exist
        for n in host_names:
            if n not in self.data["objects"]:
                raise Exception("Host object does not exist.")
        
        # check to ensure that objects are not hosts of each other
        for hn in host_names:
            if bool(set(obj_names) & set(self.getObjHosts(hn, traverse=True))):  # if any intersection exists between the two
                raise Exception("Objects cannot be hosts of each other.")

        for obj_name in obj_names:
            self.host_tree.clearHosts(obj_name)
            self.host_tree.add(obj_name, host_names.copy())
    
    def getObjHosts(self, obj_name : str, traverse=False, only_secondary=False):
        """Get the host(s) for an object.
        
            Params:
                obj_name (str): the name of the object to retreive the hosts for
                traverse (bool): True if all hosts should be returned
                only_secondary (bool): True if only secondary hosts should be included in the traverse
        """
        return self.host_tree.getHosts(obj_name, traverse, only_secondary)
    
    def clearObjHosts(self, obj_names : list):
        """Clear the host for object(s).
        
            Params:
                obj_names (list): the names of the objects whose hosts should be cleared
        """
        for obj_name in obj_names:
            self.host_tree.clearHosts(obj_name)
    
    def clearTracking(self):
        """Clear the tracking of modified ztraces and modified objects."""
        self.modified_ztraces = set()
        self.modified_objects = set()

    def initGroupViz(self) -> dict:
        """Get initial group visibility."""

        groups = self.object_groups.getGroupList()

        if not groups:
            
            return {}
        
        else:
            
            return {group: True for group in groups}

    @property
    def alignments(self):
        """Return the possible alignments for the series."""
        section_data_list = list(self.data["sections"].values())
        alignments = set(section_data_list[0]["tforms"].keys())
        for section_data in section_data_list[1:]:
            a = set(section_data["tforms"].keys())
            if alignments != a:
                raise Exception("Sections have differently named alignments.")
        return alignments
    
    @property
    def bc_profiles(self):
        """Return the possible brightness/contrast profiles for the series."""
        section_data_list = list(self.data["sections"].values())
        bc_profiles = set(section_data_list[0]["bc_profiles"].keys())
        for section_data in section_data_list[1:]:
            p = set(section_data["bc_profiles"].keys())
            if bc_profiles != p:
                raise Exception("Sections have differently named brightness/contrast profiles.")
        return bc_profiles

    
class SeriesIterator():

    def __init__(self, series : Series, show_progress : bool, message : str, series_states, breakable=True, section_numbers=None):
        """Create the series iterator object.

            Params:
                series (Series): the series object
                show_progress (bool): show progress dialog if True
                message (str): the message to show
                series_states (dict): section number : SectionStates (for use with GUI)
                breakable (bool): True if series state is breakable
                section_numbers (iterable): if given, restrict iteration to
                    these section numbers
        """
        self.series = series
        self.section = None
        self.show_progress = show_progress
        self.message = message
        self.series_states = series_states
        self.section_subset = None if section_numbers is None else set(section_numbers)
        if self.series_states is not None:
            self.series_states.addState(breakable)

    def __iter__(self):
        """Allow the user to iterate through the sections."""
        if self.section_subset is None:
            self.section_numbers = sorted(list(self.series.sections.keys()))
        else:
            # restrict to the requested subset (intersected with existing sections)
            self.section_numbers = sorted(
                n for n in self.section_subset if n in self.series.sections
            )
        self.sni = 0
        if self.show_progress:
            self.reporter = self.series._progressReporterFactory()(
                text=self.message,
                cancel=False
            )
        return self
    
    def __next__(self):
        """Return the next section."""
        # update the series states of the previous section if requested
        if self.series_states and self.section and (
            self.section.getAllModifiedNames() or 
            self.section.tformsModified() or
            self.section.flags_modified
        ):
            self.series_states[self.section.n].addState(
                self.section, self.series
            )
            self.series_states.addSectionUndo(self.section.n)

        if self.sni < len(self.section_numbers):
            if self.show_progress:
                    self.reporter.set_progress(self.sni / len(self.section_numbers) * 100)
            snum = self.section_numbers[self.sni]
            self.section = self.series.loadSection(snum)
            self.sni += 1

            # check if states have been initialized
            if self.series_states:
                self.series_states[self.section]
            
            return snum, self.section
        
        else:
            if self.show_progress:
                # self.sni == len(self.section_numbers) here, so the fraction
                # is always 1 -- except for an empty subset (e.g. every
                # requested section was invalid), where it would be 0/0
                self.reporter.set_progress(100)
            raise StopIteration


def updateDictLists(d1 : dict, d2 : dict):
    """In the cases where two dictionaries have values as lists, combine the two lists for each value.

    Deduplication preserves first-seen order (d1's values, then d2's additions):
    these lists are the option sets shown for user-defined columns, so a stable
    order matters, and set() iteration order is not stable across processes.
    """
    d = deepcopy(d1)
    for k, l in d2.items():
        if k not in d:
            d[k] = []
        # d[k] + l, minus duplicates -- NOT set(l), which would discard d1's
        # values entirely for any key present in both dicts
        seen = set()
        d[k] = [v for v in d[k] + l if not (v in seen or seen.add(v))]
    return d
