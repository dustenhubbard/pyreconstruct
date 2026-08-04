"""The name filter every list, table and import path in the app shares.

One rule, stated once: a name passes when there are no filters, or when it
fullmatches at least one of them. It was written out by hand in nine places
before this module existed -- three in `series.py`, one each in `section.py`,
`log.py`, `host_tree.py`, `obj_group_dict.py`, and once per table in
`gui/table/{object,trace,ztrace,flag}.py` -- which is how the import dialog and
the tables were able to disagree about what a filter means without anyone
touching either.

`fullmatch`, not `search`: a filter names the whole object, so "d0" does not
select "d001". Callers that want a prefix write "d0.*".
"""

import re


def passesFilters(s, re_filters) -> bool:
    """Check whether a name passes a set of regex filters.

        Params:
            s (str): the name to test
            re_filters (list): the regex filters; empty or None means no
                filtering, and everything passes
        Returns:
            (bool): True if the name passes
    """
    if not re_filters:
        return True
    for rf in re_filters:
        if bool(re.fullmatch(rf, s)):
            return True
    return False
