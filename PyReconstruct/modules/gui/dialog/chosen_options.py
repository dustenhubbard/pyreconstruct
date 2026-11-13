"""Store what a settings dialog's user changed, and nothing they left alone.

Until the old KHLab preferences are copied, a dialog shows the defaults in
their place. The copy never replaces a value already in the new store, so
storing every value a dialog shows would replace those preferences for good.
While the copy is pending, a dialog stores only the options whose values
changed after it opened, and options it did not show at opening.
"""
from copy import deepcopy

from PyReconstruct.modules.constants.settings_domain import user_action


def settings_copy_pending(series):
    """Whether the global or per-series store of `series` awaits its copy."""
    store = series._settingsStore()
    # a read first, so that a copy which can finish now does
    store.contains(None, "username")
    store.contains(series.code, "backup_dir")
    return not (store.may_save_defaults(None)
                and store.may_save_defaults(series.code))


def _comparable(value):
    # Series.setOption stores lists and tuples alike, as JSON arrays, and
    # a dialog may return 1.0 for a stored 1, which == already equates
    if isinstance(value, (list, tuple)):
        return [_comparable(item) for item in value]
    if isinstance(value, dict):
        return {key: _comparable(item) for key, item in value.items()}
    return value


def store_chosen_options(series, options, opening, copy_pending):
    """Store `options` as explicit user choices.

    While `copy_pending`, skip each option whose value matches `opening`.
    """
    with user_action():
        for key, value in options.items():
            if (not copy_pending or key not in opening
                    or _comparable(value) != _comparable(opening[key])):
                series.setOption(key, value)


class ChosenOptions:
    """The options a dialog shows when it opens, kept to compare on OK.

    Make it before the dialog reads the values it shows. A copy that
    finishes during those reads leaves the values read before it at their
    defaults, so the copy counts as pending for the whole dialog.
    """

    def __init__(self, series):
        self.series = series
        self.copy_pending = settings_copy_pending(series)
        self.opening = {}

    def read(self, *keys):
        """Read each option once, keep it as shown, and return the values.

        Build the dialog's controls from these values, not from new reads:
        a copy that finishes between two reads of one option would make
        the control show one value and OK compare with another.
        """
        values = {key: self.series.getOption(key) for key in keys}
        self.opening.update(deepcopy(values))
        return values

    def shown(self, opening):
        """Keep `opening`, the values the dialog's built controls show;
        return self. Values read from the series go through `read`."""
        self.opening = deepcopy(dict(opening))
        return self

    def store(self, options):
        """Store the accepted `options`; they become the new opening values."""
        store_chosen_options(self.series, options, self.opening, self.copy_pending)
        self.opening.update(deepcopy(options))
