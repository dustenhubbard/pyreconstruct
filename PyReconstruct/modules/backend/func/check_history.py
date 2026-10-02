"""Find history rows in .jser files that PyReconstruct cannot read back.

Older versions could write a row split across lines (a line break in a name or
event) or with a comma in a user or object name. Those rows stay in the file.
This only reads files; it never writes to one.
"""

import io
from pathlib import Path

from PyReconstruct.modules.constants import fast_loads
from PyReconstruct.modules.datatypes.log import LogSet


class HistoryCheckError(Exception):
    """A file that could not be checked. The message is for the user."""


def unreadableRows(log_text: str) -> list:
    """Return (line number, raw text) for each history row that will not parse.

    The text is split the way Series.openJser and Series.getFullHistory split
    it: written to existing_log.csv, read back with universal newlines, and the
    first line skipped as the header. Line numbers count that header as line 1.
    """
    log_list = io.StringIO(log_text, newline=None).readlines()[1:]
    log_set = LogSet.fromList(log_list, skip_corrupt=True)
    return [
        (index + 2, row.rstrip("\n"))
        for index, row in zip(log_set.skipped_indexes, log_set.skipped_rows)
    ]


def checkJser(fp) -> list:
    """Return the unreadable history rows of one .jser file."""
    try:
        with open(fp, "rb") as f:
            jser_data = fast_loads(f.read())
    except OSError as e:
        raise HistoryCheckError(f"It could not be opened ({e.strerror})")
    except ValueError:
        raise HistoryCheckError("It is not a series file")
    if not isinstance(jser_data, dict):
        raise HistoryCheckError("It is not a series file")
    log_text = jser_data.get("log")
    if not log_text:
        return []
    if not isinstance(log_text, str):
        raise HistoryCheckError("Its history is not text")
    return unreadableRows(log_text)


def jserFiles(paths) -> list:
    """Return the .jser files named, and those in any folder named, sorted."""
    files = []
    for path in paths:
        path = Path(path)
        if path.is_dir():
            files.extend(sorted(
                p for p in path.rglob("*.jser")
                if p.is_file() and not any(
                    part.startswith(".") for part in p.relative_to(path).parts
                )
            ))
        else:
            files.append(path)
    return files


def _count(n, noun):
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def checkHistory(paths, out) -> int:
    """Print the unreadable history rows of each file to out.

    Returns 0 when every file was checked and none has an unreadable row,
    1 otherwise.
    """
    files = jserFiles(paths)
    if not files:
        print("No .jser files found.", file=out)
        return 1

    with_rows = 0
    failed = 0
    for fp in files:
        try:
            rows = checkJser(fp)
        except HistoryCheckError as e:
            print(f"{fp}: not checked. {e}.", file=out)
            failed += 1
            continue
        if rows:
            with_rows += 1
            print(f"{fp}: {_count(len(rows), 'unreadable history row')}", file=out)
            for line_num, raw in rows:
                print(f"  line {line_num}: {raw}", file=out)

    checked = len(files) - failed
    print(
        f"Checked {checked} of {_count(len(files), 'file')}. "
        f"{_count(with_rows, 'file')} had unreadable history rows. "
        "No file was changed.",
        file=out,
    )
    return 1 if (with_rows or failed) else 0
