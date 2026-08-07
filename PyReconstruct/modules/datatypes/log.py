import re

from pathlib import Path
from datetime import datetime

from PyReconstruct.modules.constants import getDateTime, remove_days_from_today

from .filters import passesFilters


## What a row of the log begins with, and the only thing about the format that
## every reader here is entitled to rely on. Log.__str__ writes
## f"{date}, {time}, ..." unconditionally, and both fields come from
## getDateTime's "%y-%m-%d" / "%H:%M", which strftime zero-pads: two digits per
## component, always, for every representable instant. So "a line that does NOT
## open with this stamp cannot be the start of a row this program wrote" is a
## structural fact about the writer, not a guess about the content.
##
## Deliberately laxer than the writer in one place: "%H" never emits a
## single-digit hour, but \d?\d accepts one anyway. The looseness only ever
## widens what is REFUSED as a row start (see fromList's join guard, which
## fails safe), so it costs nothing on data this program wrote and covers a
## hand-edited or foreign-tool row that a stricter pattern would silently join.
ROW_START = re.compile(r"\d\d-\d\d-\d\d, \d?\d:\d\d, ")


## The CSV header line, byte for byte as every writer in the tree emits it:
## Series.openJser and Series.new (both in series.py) and xmlToJSON (in
## backend/func/xml_json_conversions.py) write this exact string and nothing
## else -- all three byte-identical. Readers must match it exactly. A substring
## test such as `"Date" in line` also matches an ordinary continuation line
## whose text happens to mention a date field, which is not a header and must
## not be treated as one.
LOG_HEADER = "Date, Time, User, Obj, Sections, Event"


## Log event prefixes that record a human deliberately removing annotation
## work. These are the only events that entitle an import to discard traces the
## other series still holds. Kept beside the Log class because the exact strings
## are written by Series/Section (see Series.editObjectAttributes,
## Section.deleteTraces, SeriesData's object bookkeeping) and read here.
REMOVAL_EVENTS = (
    "Delete object",
    "Delete trace(s)",
    "Rename object to",
)


class Log():

    def __init__(self, date : str, time : str, user : str, obj_name : str, section, event : str):
        """Create a single log entry.
        
            Params:
                date (str): the date of the log creation YY-MM-DD
                time (str): the time of the log creation HH:MM. The colon is
                    not cosmetic: it is what stops a mis-joined row from
                    reading a timestamp as a section range (see fromList).
                    getDateTime has written "%H:%M" since the log was created,
                    so no stored log carries the HHMM this line used to claim.
                user (str): the username of the person making the log
                obj_name (str): the name of the object being modified
                section (int OR list): the section or section ranges of the log
                event (str): the description of what happened
        """
        self.date = date
        self.time = time
        self.user = user
        self.obj_name = obj_name
        if type(section) is int:
            self.section_ranges = [(section, section)]
        elif type(section) is list:
            self.section_ranges = section
        elif section is None:
            self.section_ranges = None
        self.event = event
    
    def __eq__(self, other):
        """Compare log objects.
        
            Params:
                other (Log): the log to compare to
        """
        return str(self) == str(other)
    
    def __str__(self):
        if not self.obj_name:
            obj_name = "-"
        else:
            obj_name = self.obj_name
        
        if not self.section_ranges:
            section_ranges = "-"
        else:
            section_ranges = []
            for srange in self.section_ranges:
                if srange[0] == srange[1]:
                    section_ranges.append(str(srange[0]))
                else:
                    section_ranges.append(f"{srange[0]}-{srange[1]}")
            section_ranges = " ".join(section_ranges)

        row = f"{self.date}, {self.time}, {self.user}, {obj_name}, {section_ranges}, {self.event}"

        # One Log, one physical line -- enforced here rather than hoped for.
        #
        # Every reader of the log is line-oriented (fromList loops over rows,
        # exportLogHistory scans line by line for a date, the history table
        # reads what those produce), so a field carrying a literal newline used
        # to split ONE row across several lines and leave each reader to guess
        # where the row ended. They guessed, and guessed wrong: fromList's join
        # could fold the next user's whole row into the fragment and invent an
        # editor out of that row's timestamp, silently and on the default path.
        #
        # This is the single place a Log becomes text. getList,
        # getLogList(as_str=True) and LogSet.__str__ all route through here,
        # __eq__ compares through here, and the f-string above is the only row
        # formatter in the package -- checked, not assumed. So normalizing at
        # this line makes "a Log occupies one line" an invariant of the format
        # instead of a property of whichever callers remembered to sanitize.
        #
        # Which is where the newlines come from: the fields are free text from
        # dialogs. Trace.name routes through normalizeObjectName, but ztrace
        # and alignment names, brightness/contrast profile names, object group
        # names, user column names and values, the offloaded-log file path, the
        # section image-source name and series.user itself are plain strings
        # from QLineEdit/QInputDialog, which keep a pasted newline verbatim.
        # Enumerating and closing those call sites one at a time is a list that
        # can only get out of date; this is the chokepoint they all pass.
        #
        # "_" and not " ": a space adjacent to an existing comma manufactures
        # the ", " Log.fromStr splits on, which would trade a newline hazard
        # for a field-shift hazard rather than removing anything.
        #
        # All three terminators. A lone "\r" survives in a str but comes back
        # as "\n" once the file is read in universal-newline text mode -- which
        # is how getFullHistory reads existing_log.csv -- so leaving it here
        # only defers the split. "\r\n" is replaced first so a CRLF costs one
        # "_" rather than two.
        return row.replace("\r\n", "_").replace("\n", "_").replace("\r", "_")

    def fromStr(s : str):
        """Get a log object from a string.
        
            Params:
                s (str): the string
        """
        l = s.split(", ")

        # check for commas in event
        if len(l) > 6:
            l[5] = ", ".join(l[5:])
            l = l[:6]

        (
            date,
            time,
            user,
            obj_name,
            section_ranges,
            event
        ) = tuple(l)
        if obj_name == "-":
            obj_name = None

        if section_ranges == "-":
            section_ranges = None
        else:
            srs = section_ranges.split(" ")
            section_ranges = []
            for sr in srs:
                ends = sr.split("-")
                if len(ends) == 1:
                    section_ranges.append((int(sr), int(sr)))
                else:
                    section_ranges.append((int(ends[0]), int(ends[1])))
        
        return Log(date, time, user, obj_name, section_ranges, event.strip())
    
    def checkSectionRanges(self):
        """Iterate through the section ranges and combine adjacent ones."""
        i = 0
        while i < len(self.section_ranges) - 1:
            current = self.section_ranges[i]
            next = self.section_ranges[i+1]
            if current[1] >= next[0] - 1:
                new = (min(current + next), max(current + next))
                self.section_ranges[i] = new
                self.section_ranges.pop(i+1)
            else:
                i += 1
    
    def addSection(self, snum : int):
        """Add a section number to the section range.
        
            Params:
                snum (int) the section number to add
        """
        if self.section_ranges is None:
            raise Exception("Cannot add section number to non section-specific log.")
        loop_broken = True
        for i, srange in enumerate(self.section_ranges):
            loop_broken = True
            if snum < srange[0]:
                if snum == srange[0] - 1:
                    self.section_ranges[i] = (snum, srange[1])
                else:
                    self.section_ranges.insert(i, (snum, snum))
                break
            elif srange[0] <= snum <= srange[1]:
                break
            elif snum == srange[1] + 1:
                self.section_ranges[i] = (srange[0], snum)
                break
            loop_broken = False
        
        if not loop_broken:
            self.section_ranges.append((snum, snum))
        
        self.checkSectionRanges()
    
    def containsSection(self, snum : int):
        """Check if the logs section range contains the given section number.
        
            Params:
                snum (int): the section number
        """
        if not self.section_ranges:
            return False
        
        for n1, n2 in self.section_ranges:
            if snum in range(n1, n2+1):
                return True
        
        return False
    
    def trimSectionRange(self, srange):
        """Trim the section range of the log."""
        if not self.section_ranges:
            self.section_ranges = [(srange[0], srange[1]-1)]
            return True
        else:
            sections = range(*srange)
            new_section_ranges = []
            for s1, s2 in self.section_ranges.copy():
                if s1 and s2 in sections:
                    new_section_ranges.append((s1, s2))
                elif s1 in sections:
                    new_section_ranges.append((s1, srange[1]-1))
                elif s2 in sections:
                    new_section_ranges.append((srange[0], s2))
                elif s1 < srange[0] and s2 >= srange[1]:
                    new_section_ranges.append((srange[0], srange[1]-1))
            if new_section_ranges:
                self.section_ranges = new_section_ranges
                return True
            else:
                return False


class LogSet():

    def __init__(self):
        """Create the log set."""
        self.dyn_logs = {}  # organized by name and event
        self.all_logs = []
        # the raw rows fromList() dropped because they would not parse. Only
        # ever non-empty for a fromList(skip_corrupt=True) call; kept so the
        # caller can say how much history it lost instead of silently showing
        # a partial one.
        self.skipped_rows = []

    def addLog(self, user : str, obj_name : str, snum : int, event : str):
        """Add a log to the set.
        
            Params:
                user (str): the user creating the log
                obj_name (str): the name of the object associated with the log
                snum (int): the section number associated with the log
                event (str): the description of the event
        """
        # compare the user to the last log
        if self.all_logs and user != self.all_logs[-1].user:
            # clear dynamic log if so
            self.dyn_logs = {}
        
        if snum is not None:  # dynamic log
            obj_key = obj_name if obj_name else "-"
            if obj_key in self.dyn_logs and event in self.dyn_logs[obj_key]:
                self.dyn_logs[obj_key][event].addSection(snum)
            else:
                if obj_key not in self.dyn_logs:
                    self.dyn_logs[obj_key] = {}
                d, t = getDateTime()
                l = Log(d, t, user, obj_name, snum, event)
                self.all_logs.append(l)
                self.dyn_logs[obj_key][event] = l
        else:  # static log
            d, t = getDateTime()
            log = Log(d, t, user, obj_name, snum, event)

            # special cases: creating or deleting an object
            if event == "Create object":
                # check the previous log to see if traces were created
                if (
                    self.all_logs and
                    self.all_logs[-1].obj_name == obj_name and 
                    "Create trace(s)" in self.all_logs[-1].event):
                    event = self.all_logs[-1].event
                    self.all_logs[-1].event = event.replace("trace(s)", "object")
                else:
                    self.all_logs.append(log)
            elif event == "Delete object":
                # remove object from dynamic log
                if obj_name in self.dyn_logs:
                    del(self.dyn_logs[obj_name])
                # remove all previous logs associated with the object in a
                # single pass (the per-element list.remove() loop was O(n^2)
                # per deleted object)
                self.all_logs = [
                    l for l in self.all_logs
                    if not (l.obj_name == obj_name and "Create object" not in l.event)
                ]
                self.all_logs.append(log)
            # non-special cases
            else:
                self.all_logs.append(log)
        
    def addExistingLog(self, log : Log, track_dyn=False):
        """Add an existing log object to the set.
        
            Params:
                log (Log): the log to add to the set
                track_dyn (bool): True if log should be dynamically tracked
        """
        self.all_logs.append(log)
        if track_dyn:
            if log.section_ranges:
                obj_key = log.obj_name if log.obj_name else "-"
                if obj_key not in self.dyn_logs:
                    self.dyn_logs[obj_key] = {}
                self.dyn_logs[obj_key][log.event] = log
    
    def getLogList(self, as_str=False):
        """Return the stored logs as a list.
        
            Params:
                as_str (bool): True if the log should be returned in str format
            Returns:
                the log list in list or str format
        """
        if as_str:
            logs_str = []
            for log in self.all_logs:
                logs_str.append(str(log))
            return "\n".join(logs_str)
        else:
            return self.all_logs.copy()
    
    def __str__(self):
        return self.getLogList(as_str=True)

    def getList(self) -> list:
        """Return log set as a list"""
        log_list = self.getLogList()
        for i, log in enumerate(log_list):
            log_list[i] = str(log)
        
        return log_list
    
    def fromList(log_list : list, skip_corrupt : bool = False):
        """Get a log set from a list.

            Params:
                log_list (list): the list representation of the logs
                skip_corrupt (bool): False (the default) to raise on the first
                    row that will not parse. True to drop just that row, record
                    it in skipped_rows, and keep every other row.
            Returns:
                (LogSet): the parsed log set

        Which of the two behaviors is right is the caller's call, not this
        function's: a reader that shows the history to a user would rather
        raise than quietly present an incomplete one, while a reader that
        folds the rows into a set (Series.getEditorsFromHistory) loses every
        OTHER user's entry if one row costs the file. Hence the flag,
        defaulting to the historical all-or-nothing so no existing caller
        changes.

        "A bad row costs only itself" now holds for every shape, which took
        two separate changes and is worth stating as one claim because earlier
        versions of this docstring had to qualify it.

        A row holding FEWER than six comma fields is first joined to the lines
        after it by the continuation loop below, because a name or event
        carrying a literal newline reaches us split across the physical lines
        it was written to. That join used to be unguarded, so it took whatever
        followed -- including a well-formed row belonging to somebody else --
        and the two outcomes had to be described separately:

        * the join does NOT parse -- recovered by the handler below. Only the
          first physical line is recorded as skipped and the scan resumes at
          the line after it, so every line the failed join swept up gets a
          fresh attempt on its own, and skipped_rows holds one entry per lost
          file line.
        * the join DOES parse -- used to be lost silently. One fabricated Log
          stood in for both rows, nothing reached skipped_rows, and it fired
          on the default path too, where skip_corrupt never comes into it.

        The second is now closed at the source: the join refuses any line that
        opens with the "YY-MM-DD, HH:MM, " stamp Log.__str__ writes on every
        row (see ROW_START and the guard below), so an unrelated row can no
        longer be eaten as a continuation. What used to be a silent
        fabrication is a plain parse failure, which means it goes through the
        first bullet instead -- raising by default, recorded in skipped_rows
        under skip_corrupt, and in both cases leaving the following row to be
        read on its own.

        The residue is one genuinely irreducible case, and the guard fails
        safe on it: a pasted name whose own text contains a line that looks
        like a whole row is indistinguishable, byte for byte, from two real
        rows. There the guard truncates the name rather than inventing an
        editor from somebody else's timestamp.

        Log.__str__ no longer emits a multi-line row at all, so nothing
        written from here on can reach any of this. The guard is for what is
        already on disk, which is copied through byte for byte on every open
        and save and is therefore permanent. All of these shapes are pinned in
        tests/test_editors_from_corrupt_history.py.
        """
        log_set = LogSet()
        i = 0
        while i < len(log_list):
            # the physical line this attempt starts from. The continuation
            # loop below advances i as it consumes lines, so this is the only
            # record of where the attempt began once it has run.
            start = i
            log_str = log_list[i]
            if log_str.strip():
                try:
                    # A row begins where a row's date stamp begins, and nowhere
                    # else. This is the first of the two places the anchor is
                    # applied, and it is not redundant with the second: it
                    # catches the line that is reached as a START without being
                    # a row, which no join guard can see because no join runs.
                    #
                    # How such a line is reached: a name holding SEVERAL
                    # newlines splits its row into three or more physical
                    # lines. The head fails, the handler below hands the
                    # remaining fragments back one at a time, and a middle
                    # fragment can hold six comma fields all by itself -- at
                    # which point Log.fromStr reads it as a whole row and
                    # takes its fields for a date, a time and a USER. A pasted
                    # ztrace name of "x\\ny, z, w, v" is enough: the fragment
                    # "y, z, w, v, -, Offloaded log to x" parses, and "w"
                    # becomes an editor of the series. Measured on the writer's
                    # own output, not constructed by hand.
                    #
                    # Requiring the stamp costs nothing legitimate, because a
                    # genuine continuation is never reached here: it is
                    # consumed by the join below, from its own anchored head,
                    # before the loop can advance onto it. Only a fragment
                    # whose head already failed arrives as a start, and that
                    # fragment is exactly what must not be trusted.
                    if not ROW_START.match(log_str.strip()):
                        raise ValueError(
                            "log row does not begin with a date and time: "
                            f"{log_str.strip()[:60]!r}"
                        )

                    # Reassemble before parsing: a name holding a literal
                    # newline -- the "return key in name" this loop was written
                    # for -- reaches us split across the physical lines it was
                    # written to, so a short row is joined to the line after it
                    # until it has six comma fields.
                    #
                    # The join is anchored too, and this is the second place.
                    # It refuses to absorb a line
                    # that opens with the "YY-MM-DD, HH:MM, " stamp ROW_START
                    # describes, because Log.__str__ writes that stamp on every
                    # row unconditionally: a line carrying it is a row, not the
                    # tail of one.
                    #
                    # That is a structural guarantee about this program's own
                    # writer, not a heuristic about content, which is what
                    # makes it worth the behavior change. The rule it replaces
                    # was "keep going until six commas have accumulated", which
                    # says nothing about where rows begin, so it consumed the
                    # next row whenever that row's fields happened to line up.
                    # What it took depended on k, the number of ", " fields on
                    # the orphan: the concatenation puts the next row's field
                    # k-1 into the section-range slot, the only slot that must
                    # read as an integer, so k=1 always parsed (polluting the
                    # next row's date), k=2 parsed whenever the follower's
                    # obj_name was the "-" every series-level row writes or a
                    # numeric object name, and k=3/4 parsed on a numeric
                    # username or a colon-less time. k=2 was the live one:
                    # after it, getEditorsFromHistory reported the next row's
                    # TIME as an editor, with nothing in skipped_rows and no
                    # warning printed. Anchoring removes the whole family at
                    # once rather than excluding one k at a time, because it
                    # stops the join before the alignment can happen.
                    #
                    # The cost, stated plainly because it is a change every
                    # default caller sees, not just skip_corrupt ones: a short
                    # head that can never be completed now RAISES where it used
                    # to fabricate. That is strictly the better failure -- a
                    # caller can see a raise and cannot see a fabrication -- and
                    # it raises on LESS input than the unguarded join did, not
                    # more, since the shapes that used to parse into a
                    # fabricated Log were the ones getting through silently.
                    #
                    # One case is genuinely irreducible and the anchor does not
                    # pretend otherwise: a pasted name whose own text contains
                    # a line that looks like a whole row produces bytes
                    # identical to two real rows, and nothing in the file can
                    # tell them apart. The guard fails safe there -- it
                    # truncates the name -- where the unguarded join failed
                    # unsafe, inventing an editor nobody was.
                    #
                    # Why this still matters now that Log.__str__ cannot emit a
                    # multi-line row: the historical log is copied byte for
                    # byte on open and save and is never re-emitted from parsed
                    # objects, so a file corrupted by an older build stays
                    # corrupted forever. The write-side fix protects new data;
                    # this protects what is already on disk, plus hand-edited
                    # files and any route a future writer opens by accident.
                    #
                    while len(log_str.split(",")) < 6:
                        nxt = log_list[i+1]
                        if ROW_START.match(nxt.strip()):
                            # A row, not a continuation. Stop rather than eat
                            # it: log_str is still short of six fields, so
                            # Log.fromStr below raises ValueError, the handler
                            # records this line alone, and the scan resumes at
                            # nxt so it gets read as the row it is.
                            break
                        log_str += nxt.strip()
                        i += 1
                    log = Log.fromStr(log_str)
                except (ValueError, IndexError):
                    # ValueError: the row does not have six fields, or the
                    # section range does not read as one -- what a legacy
                    # object name holding the ", " fromStr splits on produces,
                    # since it shifts every field after it. IndexError: a
                    # continuation join that runs off the end of the list.
                    # Those two are the parse failures; anything else is not,
                    # and still propagates whatever skip_corrupt says.
                    if not skip_corrupt:
                        raise
                    # Record the FIRST physical line of the failed attempt, not
                    # the whole concatenation, and resume at the line after it
                    # rather than after everything the join consumed. The join
                    # is greedy, so those consumed lines may be perfectly
                    # well-formed rows belonging to other users; discarding
                    # them with the line that failed loses history nobody has
                    # any reason to lose, and undercounts the loss besides,
                    # since several file lines went into one entry.
                    #
                    # Safe by reachability rather than by judgement: this
                    # handler is only ever entered on an attempt that ALREADY
                    # raised, i.e. on input the previous code already gave up
                    # on entirely. There is no way for it to make a join that
                    # succeeds today succeed differently, so no caller whose
                    # log parses sees any change at all. What it can change is
                    # how much is salvaged from a log that does not -- which
                    # is the whole point.
                    #
                    # The lines handed back go through the same join, and that
                    # used to carry a caveat: on an ALREADY-failing log a
                    # recovered orphan could join FORWARD and fabricate, so a
                    # loud loss became a silent invented editor. The shape it
                    # needed was one pasted name splitting its row across three
                    # physical lines, leaving two orphan fragments of which the
                    # second was k=2, followed by a row whose obj_name was "-"
                    # or numeric -- an alignment named "\n, b\n, b" through
                    # Series.modifyAlignments did it, measured end to end.
                    #
                    # The anchored join closes that too, and closes it here
                    # rather than by a separate rule: the row such an orphan
                    # would have joined forward to carries the date stamp, so
                    # the join refuses it and the orphan fails alone. The
                    # recovery is now what it always claimed to be -- one
                    # skipped_rows entry per lost file line, no exceptions --
                    # because the one exception was that fabrication.
                    log_set.skipped_rows.append(log_list[start])
                    i = start + 1
                    continue
                log_set.addExistingLog(log)
            i += 1

        return log_set
    
    def removeCuration(self, obj_name : str):
        """Remove all curation logs in the session.
        
            Params:
                obj_name (str): the name of the object to remove curation for
        """
        for log in self.all_logs.copy():
            if (obj_name == log.obj_name and 
                ("curated" in log.event or "curation" in log.event)):
                self.all_logs.remove(log)
    
    def getLastIndex(self, snum : int, cname : str):
        """Scan the history and return the date for a contour on a given section.
        
            Params:
                snum (int): the section number
                cname (str): the contour name
        """
        i = len(self.all_logs) - 1
        for log in reversed(self.all_logs):
            if (
                log.obj_name == cname and 
                ("ztrace" not in log.event) and 
                (log.containsSection(snum) or (log.section_ranges is None))
            ):
                return i
            i -= 1
        return i

    @staticmethod
    def exportLogHistory(hidden_dir: str, output_fp: str, older_than: int) -> None:
        """Export log history as CSV for external storage.

        Rows older than `older_than` days move to `output_fp`; the rest are
        written back to existing_log.csv.

        This reads the file line by line, which is only the same thing as
        reading it row by row while every row occupies one line. Log.__str__
        now guarantees that for anything written from here on, but the
        historical log is copied through byte for byte on open and save and is
        never re-emitted, so a row split across two lines by an older build is
        on disk permanently. Such a line has no date in its first field, and
        feeding it to strptime raised an uncaught ValueError out of
        Series > Export Log History -- measured on real 2023 data, not
        hypothesized. So a line that does not open with a row's date stamp is
        treated as the continuation it is and follows the row above it,
        keeping the two halves together in whichever file that row went to.
        """

        existing_log = Path(hidden_dir) / "existing_log.csv"
        storage_log = Path(output_fp)
        new_log = existing_log.with_name("new_log.csv")

        if storage_log.exists(): storage_log.unlink()  # remove if already exists
        
        older_than = remove_days_from_today(older_than)

        with storage_log.open("a", encoding="utf-8") as external_store, new_log.open("a", encoding="utf-8") as new:

            with existing_log.open("r", encoding="utf-8", errors="replace") as log:

                # where the row currently being read was sent, so its
                # continuation lines can follow it. None until the first row.
                current = new

                for line in log.readlines():

                    if line.strip() == LOG_HEADER:

                        external_store.write(line)
                        new.write(line)

                    elif ROW_START.match(line):

                        log_date = line.split(",")[0].strip()
                        log_date = datetime.strptime(log_date, "%y-%m-%d").date()

                        current = external_store if log_date <= older_than else new
                        current.write(line)

                    else:

                        # A continuation of the row above: a field of that row
                        # held a literal newline. It is not a row and has no
                        # date of its own, so it goes wherever its row went.
                        current.write(line)

        new_log.replace(existing_log)  # overwrite old log
                        

class LogSetPair():

    def __init__(self, logset0 : LogSet, logset1 : LogSet):
        """Create a logset pair (ideally when dealing with two series).
        
            Params:
                logset1 (LogSet): the first logset (usually self)
                logset2 (LogSet): the second logset (usually other)
        """
        self.logset0 = logset0
        self.logset1 = logset1

        # get the index for the diverge
        i = 0
        while (
            i < len(self.logset0.all_logs) and
            i < len(self.logset1.all_logs) and
            self.logset0.all_logs[i] == self.logset1.all_logs[i]
        ):
            i += 1
        
        self.last_shared_index = i-1

        self.complete_match = (
            i == len(self.logset0.all_logs) == len(self.logset1.all_logs)
        )

        # per-side {obj_name: [post-divergence logs]}, built on first use
        self._post_divergence = [None, None]

    def _postDivergenceLogs(self, side : int) -> dict:
        """Index one side's post-divergence logs by object name.

        The per-contour history queries below are called once per contour per
        section -- around 120,000 times on a 318-section series -- and used to
        answer each call by reverse-scanning the WHOLE log via
        LogSet.getLastIndex. That made history-aware importing
        O(sections x contours x log length), i.e. linear in the log, which is
        worst for exactly the long-lived, heavily collaborated series the
        feature exists for. Only logs after the divergence point can matter, and
        only the ones naming the contour being asked about, so index them once.

            Params:
                side (int): 0 for logset0, 1 for logset1
            Returns:
                (dict): obj_name -> list of that object's post-divergence logs
        """
        if self._post_divergence[side] is None:
            logset = (self.logset0, self.logset1)[side]
            by_name = {}
            for i in range(self.last_shared_index + 1, len(logset.all_logs)):
                log = logset.all_logs[i]
                if log.obj_name:  # series-level events carry no object name
                    by_name.setdefault(log.obj_name, []).append(log)
            self._post_divergence[side] = by_name

        return self._post_divergence[side]
    
    def importLogs(
        self,
        series,
        traces=True,
        ztraces=True,
        srange=None,
        regex_filters=[],
    ):
        """
        Import the history data from the other logset into the series logset

            Params:
                series (Series): the series to modify the history for
                traces (bool): True if trace history should be imported
                ztraces (bool): True if the ztrace history should be imported
                srange (tuple): the range of sections (exclusive)
                regex_filters (list): the list of regex filters used to filter names
        """
        # filter out similar history
        for i in range(self.last_shared_index + 1, len(self.logset1.all_logs)):
            log = self.logset1.all_logs[i]

            # check for trace/ztrace status
            include_log = traces and ("ztrace" not in log.event)
            include_log |= ztraces and ("ztrace" in log.event)
            include_log &= bool(log.obj_name)
            if not include_log:
                continue  # skip if not desired status

            # check filters
            if not passesFilters(log.obj_name, regex_filters):
                continue # skip if does not pass filters

            # trim section range and check if contains sections within range
            if srange and not log.trimSectionRange(srange):
                continue

            # update both the self series logs
            series.log_set.addExistingLog(log)
            self.logset0.addExistingLog(log)

        # logset0 has grown, so any post-divergence index built over it is stale
        self._post_divergence = [None, None]

        if traces:
            # iterate through the series log and update the last users
            last_user_data = {}  # obj_name : (user, datetime)
            for log in self.logset0.all_logs[self.last_shared_index+1:]:
                log : Log
                if log.obj_name and ("ztrace" not in log.event):
                    user0, dt0 = log.user, (log.date + log.time)
                    # if obj name exists in data, check against date
                    if log.obj_name in last_user_data:
                        user1, dt1 = last_user_data[log.obj_name]
                        if dt0 >= dt1:
                            last_user_data[log.obj_name] = (user0, dt0)
                    # if it does not exist in data so far, store
                    else:
                        last_user_data[log.obj_name] = (user0, dt0)
            
            # update the series attributes
            for obj_name, (user, dt) in last_user_data.items():
                series.setAttr(obj_name, "last_user", user)
    
    def getModifiedSinceDiverge(self, cname : str, snum : int):
        """Get the information on which contours have been modified since diverge.
            Params:
                cname (str): the name of the contour to check
                snum (int): the section number of the contour
            Returns:
                (tuple): logset0 True/False, logset1 True/False
        """
        # determine which series have been modified since diverge
        modified_since_diverge = [False, False]
        for i in (0, 1):
            for log in self._postDivergenceLogs(i).get(cname, ()):
                if "ztrace" in log.event:
                    continue
                # a series-level log (no section range) applies to every section
                if log.section_ranges is not None and not log.containsSection(snum):
                    continue
                modified_since_diverge[i] = True
                break
        return tuple(modified_since_diverge)

    def getRemovedSinceDiverge(self, cname : str, snum : int):
        """Get which sides deliberately removed a contour since the diverge.

        getModifiedSinceDiverge answers "does this side's log mention this
        contour after the divergence point?", which collapses every kind of
        edit into one Boolean. This answers the narrower question a merge needs
        before it is allowed to throw annotation work away: "did a human on this
        side record *removing* this contour?" A removal recorded in the log is
        consented-to and may be propagated to the other series; the mere absence
        of a log entry never licenses a removal, because logs are trimmed, are
        rewritten when an object is deleted, and are suppressed outright while
        an import runs.

            Params:
                cname (str): the name of the contour to check
                snum (int): the section number of the contour
            Returns:
                (tuple): logset0 True/False, logset1 True/False
        """
        removed_since_diverge = [False, False]
        for i in (0, 1):
            for log in self._postDivergenceLogs(i).get(cname, ()):
                if "ztrace" in log.event:
                    continue
                if not log.event.startswith(REMOVAL_EVENTS):
                    continue
                # a series-level removal (section_ranges is None) applies to
                # every section; a section-specific one only to its own
                if log.section_ranges is not None and not log.containsSection(snum):
                    continue
                removed_since_diverge[i] = True
                break
        return tuple(removed_since_diverge)
