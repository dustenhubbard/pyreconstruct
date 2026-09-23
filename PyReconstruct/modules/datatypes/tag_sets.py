"""Tag sets: the named vocabularies behind the tags dropdown.

A tag set is a name, a mode, an ordered list of tag values, and an optional
description per value. The series carries them under the top-level key
``tag_sets``, beside ``user_columns``:

    "tag_sets": {
        "Protrusion type": {
            "mode": "one",
            "tags": ["spine", "shaft", "branched"],
            "descriptions": {"spine": "A protrusion with a head and a neck."}
        },
        "Qualifiers": {"mode": "many", "tags": ["estimated"], "descriptions": {}}
    }

A tag set never changes what a tag IS. A tag stays a plain string in
``Trace.tags`` and the section files do not change, so every older build reads
every file. The set only tells the attribute dialogs which strings to offer and,
for a pick-one set, that choosing one value means the trace does not carry its
siblings.

Modes:

- ``"one"``: pick one. The dialog shows a restricted dropdown with a blank
  choice, and ``apply`` removes the set's other values from a trace when one is
  chosen. This is what a custom category is today, moved to the trace level.
- ``"many"``: pick many. The dialog offers the values with completion and
  still accepts typed text. This is what tags are today.

Loading is lenient on purpose. An entry that is not shaped like the example is
dropped and the rest of the sets load, because a set is convenience vocabulary
and the tags already on traces are the data. Losing a set costs a retype; a
series that refuses to open costs a day.
"""
from copy import deepcopy

MODE_ONE = "one"
MODE_MANY = "many"
MODES = (MODE_ONE, MODE_MANY)


def _cleanTags(tags) -> list:
    """Strings only, stripped, non-empty, first-seen order, no duplicates."""
    cleaned = []
    seen = set()
    for tag in tags or []:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
    return cleaned


def _cleanDescriptions(descriptions, tags : list) -> dict:
    """Keep a description only for a tag that is in the set."""
    if not isinstance(descriptions, dict):
        return {}
    cleaned = {}
    for tag in tags:
        text = descriptions.get(tag)
        if isinstance(text, str) and text.strip():
            cleaned[tag] = text.strip()
    return cleaned


class TagSets():

    def __init__(self, data : dict = None):
        """Build the tag sets from their stored form.

            Params:
                data (dict): the ``tag_sets`` mapping from the series file
        """
        self._sets = {}
        if not isinstance(data, dict):
            return
        for name, entry in data.items():
            normalized = self._normalize(name, entry)
            if normalized is not None:
                self._sets[name.strip()] = normalized

    @staticmethod
    def _normalize(name, entry):
        """One stored entry as the in-memory shape, or None if it is unusable."""
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(entry, dict):
            return None
        mode = entry.get("mode", MODE_MANY)
        if mode not in MODES:
            mode = MODE_MANY
        tags = _cleanTags(entry.get("tags", []))
        return {
            "mode": mode,
            "tags": tags,
            "descriptions": _cleanDescriptions(entry.get("descriptions"), tags),
        }

    # ------------------------------------------------------------------ reads

    def __contains__(self, name : str) -> bool:
        return name in self._sets

    def __len__(self) -> int:
        return len(self._sets)

    def __iter__(self):
        return iter(self._sets)

    def __eq__(self, other) -> bool:
        if not isinstance(other, TagSets):
            return NotImplemented
        return self._sets == other._sets

    def names(self) -> list:
        """The set names, in stored order."""
        return list(self._sets)

    def get(self, name : str) -> dict:
        """A copy of one set: mode, tags, descriptions. None if absent."""
        entry = self._sets.get(name)
        return deepcopy(entry) if entry is not None else None

    def mode(self, name : str) -> str:
        return self._sets[name]["mode"]

    def tags(self, name : str) -> list:
        return list(self._sets[name]["tags"])

    def description(self, name : str, tag : str) -> str:
        """The description of a tag in a set, or "" if it has none."""
        entry = self._sets.get(name)
        if entry is None:
            return ""
        return entry["descriptions"].get(tag, "")

    def describe(self, tag : str) -> str:
        """The description of a tag from the first set that describes it."""
        for entry in self._sets.values():
            text = entry["descriptions"].get(tag)
            if text:
                return text
        return ""

    def allTags(self) -> list:
        """Every known tag, set order then tag order, each once."""
        return _cleanTags(
            tag for entry in self._sets.values() for tag in entry["tags"]
        )

    def setsFor(self, tag : str) -> list:
        """The names of the sets that hold a tag."""
        return [name for name, entry in self._sets.items() if tag in entry["tags"]]

    def pickOneSets(self) -> list:
        """The names of the pick-one sets, in stored order."""
        return [name for name, entry in self._sets.items() if entry["mode"] == MODE_ONE]

    def pickManySets(self) -> list:
        """The names of the pick-many sets, in stored order."""
        return [name for name, entry in self._sets.items() if entry["mode"] == MODE_MANY]

    def chosen(self, name : str, tags : set) -> str:
        """The value a pick-one set holds in a trace's tags, or "".

        More than one of the set's values present (a file edited by hand or by
        an older build) returns the first in set order, so the dialog shows a
        value rather than a blank that would read as "leave alone".
        """
        for tag in self._sets[name]["tags"]:
            if tag in tags:
                return tag
        return ""

    # ----------------------------------------------------------------- writes

    def add(self, name : str, mode : str, tags : list, descriptions : dict = None) -> bool:
        """Add a set. Refused (False) if the name is taken or unusable."""
        if not isinstance(name, str) or not name.strip() or name.strip() in self._sets:
            return False
        if mode not in MODES:
            return False
        name = name.strip()
        tags = _cleanTags(tags)
        self._sets[name] = {
            "mode": mode,
            "tags": tags,
            "descriptions": _cleanDescriptions(descriptions, tags),
        }
        return True

    def edit(self, name : str, new_name : str = None, mode : str = None,
             tags : list = None, descriptions : dict = None) -> bool:
        """Change a set in place, keeping its position in the order.

        Any argument left None keeps its current value. Refused (False) if the
        set does not exist, the new name is taken, or the mode is unknown.
        """
        if name not in self._sets:
            return False
        entry = self._sets[name]
        if new_name is None or new_name.strip() == name:
            new_name = name
        else:
            new_name = new_name.strip()
            if not new_name or new_name in self._sets:
                return False
        if mode is None:
            mode = entry["mode"]
        elif mode not in MODES:
            return False
        tags = _cleanTags(tags) if tags is not None else list(entry["tags"])
        if descriptions is None:
            descriptions = entry["descriptions"]
        new_entry = {
            "mode": mode,
            "tags": tags,
            "descriptions": _cleanDescriptions(descriptions, tags),
        }
        # rebuild to keep the set's position when it is renamed
        self._sets = {
            (new_name if k == name else k): (new_entry if k == name else v)
            for k, v in self._sets.items()
        }
        return True

    def remove(self, name : str) -> bool:
        """Remove a set. False if there was none."""
        if name not in self._sets:
            return False
        del self._sets[name]
        return True

    def apply(self, tags : set, choices : dict) -> set:
        """A trace's tags after the dialog's pick-one choices are applied.

            Params:
                tags (set): the trace's current tags
                choices (dict): set name -> the value chosen, "" for blank, or
                    None to leave that set alone
            Returns:
                (set) a NEW set; the input is not modified

        Choosing a value removes the set's other values and adds the chosen
        one. Choosing blank ("") removes the set's values and adds nothing.
        None leaves the trace's tags for that set exactly as they are, which is
        what a dialog opened on a mixed selection must pass.
        """
        result = set(tags)
        for name, value in choices.items():
            if value is None or name not in self._sets:
                continue
            entry = self._sets[name]
            if entry["mode"] != MODE_ONE:
                continue
            result.difference_update(entry["tags"])
            if value:
                result.add(value)
        return result

    def merge(self, other) -> bool:
        """Union another series' sets into this one. True if anything changed.

        A set present on both sides keeps this side's mode and description text
        and gains the other side's tags, first-seen order. A set present only on
        the other side is copied whole.
        """
        changed = False
        for name, theirs in other._sets.items():
            if name not in self._sets:
                self._sets[name] = deepcopy(theirs)
                changed = True
                continue
            mine = self._sets[name]
            tags = _cleanTags(mine["tags"] + theirs["tags"])
            descriptions = dict(theirs["descriptions"])
            descriptions.update(mine["descriptions"])
            descriptions = _cleanDescriptions(descriptions, tags)
            if tags != mine["tags"] or descriptions != mine["descriptions"]:
                mine["tags"] = tags
                mine["descriptions"] = descriptions
                changed = True
        return changed

    def renameTag(self, name : str, old : str, new : str) -> bool:
        """Rename one value inside a set, keeping its description and position."""
        if name not in self._sets:
            return False
        entry = self._sets[name]
        new = new.strip() if isinstance(new, str) else ""
        if old not in entry["tags"] or not new:
            return False
        if new != old and new in entry["tags"]:
            return False
        entry["tags"] = [new if t == old else t for t in entry["tags"]]
        if old in entry["descriptions"]:
            entry["descriptions"][new] = entry["descriptions"].pop(old)
        return True

    # ------------------------------------------------------------------ output

    def getDict(self) -> dict:
        """The stored form: a plain dict safe to write as JSON."""
        return deepcopy(self._sets)

    def copy(self):
        return TagSets(self.getDict())
