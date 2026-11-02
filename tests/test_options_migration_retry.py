from pathlib import Path

import pytest
from PyReconstruct.modules.constants import settings_domain as SD
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from test_settings_migration_retry import domain, fail_legacy  # noqa: F401  (fixture)

pytestmark = pytest.mark.gui


@pytest.mark.parametrize('pending', [False, True])
def test_options_preserves_untouched_theme(qapp, series_jser, domain, monkeypatch, pending):  # noqa: F811  (fixture)
    app, make = domain
    old = make('KHLab')
    old.setValue('theme', 'qdark')
    old.sync()
    old_bytes = Path(old.fileName()).read_bytes()
    state = fail_legacy(monkeypatch, app)
    state['fail'] = pending
    series = Series.openJser(str(series_jser))
    series.setSettingsStore(QSettingsStore())
    dialog = AllOptionsDialog(None, series)
    try:
        dialog.all_widgets['fill_opacity'].inputs[0].widget.setText('0.3')
        assert dialog.accept() is True
        state['fail'] = False
        SD.settings_for('theme')
        actual = make('PyReconstruct').value('theme')
        print(f'options pending={pending} untouched_theme={actual!r} changed_opacity={series.getOption("fill_opacity")!r}')
        assert Path(old.fileName()).read_bytes() == old_bytes
        assert series.getOption('fill_opacity') == 0.3
        assert actual == 'qdark'
    finally:
        dialog.close()
        series.close()


@pytest.mark.parametrize('pending', [False, True])
def test_options_saves_explicit_username(qapp, series_jser, domain, monkeypatch, pending):  # noqa: F811  (fixture)
    app, make = domain
    old = make('KHLab')
    old.setValue('username', 'legacy-user')
    old.sync()
    old_bytes = Path(old.fileName()).read_bytes()
    state = fail_legacy(monkeypatch, app)
    state['fail'] = pending
    series = Series.openJser(str(series_jser))
    series.setSettingsStore(QSettingsStore())
    dialog = AllOptionsDialog(None, series)
    try:
        dialog.all_widgets['user'].inputs[0].widget.setText('chosen-user')
        assert dialog.accept() is True
        before_retry = make('PyReconstruct').value('username')
        state['fail'] = False
        SD.settings_for('username')
        actual = make('PyReconstruct').value('username')
        print(f'username pending={pending} before_retry={before_retry!r} recovered={actual!r}')
        assert Path(old.fileName()).read_bytes() == old_bytes
        assert actual == 'chosen-user'
    finally:
        dialog.close()
        series.close()


@pytest.mark.parametrize('unique_dev_key', [False, True])
def test_completed_series_copy_allows_layout_saves(domain, monkeypatch, unique_dev_key):  # noqa: F811  (fixture)
    app, make = domain
    monkeypatch.setenv('PYRECON_APP_NAME', app + ' Dev')
    stable_name, dev_name = SD.series_app(app, 'SER1'), SD.series_app(app + ' Dev', 'SER1')
    old_stable, old_dev = make('KHLab', stable_name), make('KHLab', dev_name)
    old_stable.setValue('backup_dir', '/stable/backups')
    old_dev.setValue('backup_dir', '/dev/backups')
    if unique_dev_key:
        old_dev.setValue('autobackup', False)
    old_stable.sync()
    old_dev.sync()
    store = QSettingsStore()
    store._settings('SER1')
    destination, dev = make('PyReconstruct', stable_name), make('PyReconstruct', dev_name)
    assert destination.contains(SD.ORG_MIGRATION_MARKER)
    assert dev.contains(SD.ORG_MIGRATION_MARKER)
    assert destination.value('backup_dir') == '/stable/backups'
    store.set_value('SER1', 'list_layout', '{"objects":"floating"}')
    print(f'fold unique_dev_key={unique_dev_key} pending={SD.store_copy_pending(stable_name)} folded={dev.contains(SD.FOLD_MARKER)} layout={destination.value("list_layout")!r}')
    assert destination.value('list_layout') == '{"objects":"floating"}'


@pytest.mark.parametrize("page,key,value", [
    ("knife", "knife_ignore_secondary_click", False),
    ("autoseg_colors", "autoseg_color_seed", 17),
    ("backup", "backup_delimiter", "!"),
])
def test_options_preserves_untouched_value_in_an_edited_page(
    qapp, series_jser, domain, monkeypatch, page, key, value  # noqa: F811  (fixture)
):
    app, make = domain
    old = make("KHLab")
    old.setValue(key, value)
    old.sync()
    old_bytes = Path(old.fileName()).read_bytes()
    state = fail_legacy(monkeypatch, app)
    series = Series.openJser(str(series_jser))
    series.setSettingsStore(QSettingsStore())
    dialog = AllOptionsDialog(None, series)
    try:
        widget = dialog.all_widgets[page]
        if page == "knife":
            widget.inputs[0].widget.setText("13")
        elif page == "autoseg_colors":
            widget.colors[0] = [1, 2, 3]
        else:
            widget.default_auto_cb.setChecked(not widget.default_auto_cb.isChecked())
        assert dialog.accept() is True
        assert not make("PyReconstruct").contains(key)
        state["fail"] = False
        assert series.getOption(key) == value
        assert Path(old.fileName()).read_bytes() == old_bytes
        if page == "knife":
            assert series.getOption("knife_del_threshold") == 13
        elif page == "autoseg_colors":
            assert series.getOption("autoseg_color_palette")[0] == [1, 2, 3]
        else:
            assert series.getOption("default_autobackup") is True
    finally:
        dialog.close()
        series.close()


def test_reset_defaults_explicitly_replaces_pending_preferences(
    qapp, series_jser, domain, monkeypatch  # noqa: F811  (fixture)
):
    app, make = domain
    old = make("KHLab")
    old.setValue("theme", "qdark")
    old.setValue("username", "legacy-user")
    old.sync()
    state = fail_legacy(monkeypatch, app)
    series = Series.openJser(str(series_jser))
    series.setSettingsStore(QSettingsStore())
    dialog = AllOptionsDialog(None, series)
    try:
        dialog.resetDefaults()
        assert dialog.accept() is True
        assert make("PyReconstruct").value("theme") == "default"
        assert not make("PyReconstruct").contains("username")
        state["fail"] = False
        assert series.getOption("theme") == "default"
        assert series.user == "legacy-user"
    finally:
        dialog.close()
        series.close()


@pytest.mark.parametrize("layout", [None, "not json", "[]", '{}'])
def test_completed_series_fold_releases_rejected_or_removed_values(
    domain, monkeypatch, layout  # noqa: F811  (fixture)
):
    app, make = domain
    monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    stable_name = SD.series_app(app, "SER1")
    dev_name = SD.series_app(app + " Dev", "SER1")
    if layout is not None:
        old = make("KHLab", dev_name)
        old.setValue("list_layout", layout)
        old.sync()
    if layout == '{}':
        with SD.user_action():
            SD.GuardedSettings(make("PyReconstruct", stable_name)).remove("list_layout")
    store = QSettingsStore()
    store._settings("SER1")
    destination, dev = make("PyReconstruct", stable_name), make("PyReconstruct", dev_name)
    assert not dev.contains(SD.FOLD_MARKER)
    assert not SD.store_copy_pending(stable_name)
    store.set_value("SER1", "list_layout", '{"objects":"floating"}')
    assert destination.value("list_layout") == '{"objects":"floating"}'



def test_repeated_palette_edits_save_a_return_to_the_opening_seed(
    qapp, series_jser, domain, monkeypatch  # noqa: F811  (fixture)
):
    app, make = domain
    old = make("KHLab")
    old.setValue("autoseg_color_seed", 17)
    old.sync()
    state = fail_legacy(monkeypatch, app)
    series = Series.openJser(str(series_jser))
    series.setSettingsStore(QSettingsStore())
    dialog = AllOptionsDialog(None, series)
    try:
        page = dialog.all_widgets["autoseg_colors"]
        for seed in (5, 0):
            page.seed_edit.setText(str(seed))
            assert page.accept(close=False)
            page.set()
            assert make("PyReconstruct").value("autoseg_color_seed", type=int) == seed
        state["fail"] = False
        assert series.getOption("autoseg_color_seed") == 0
    finally:
        dialog.close()
        series.close()



def test_completed_copy_keeps_backup_preferences_when_series_code_changes(
    qapp, series_jser, tmp_path
):
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    series = Series.openJser(str(series_jser))
    store = DictSettingsStore()
    series.setSettingsStore(store)
    series.setOption("backup_dir", str(tmp_path))
    dialog = AllOptionsDialog(None, series)
    try:
        dialog.all_widgets["series_code"].inputs[0].widget.setText("changed-code")
        assert dialog.accept() is True
        assert series.code == "changed-code"
        assert store.value("changed-code", "backup_dir", str) == str(tmp_path)
    finally:
        dialog.close()
        series.close()



def test_first_use_copies_backup_preferences_before_series_code_changes(
    qapp, series_jser, tmp_path, domain  # noqa: F811  (fixture)
):
    app, make = domain
    series = Series.openJser(str(series_jser))
    series.setSettingsStore(QSettingsStore())
    old_global = make("KHLab")
    old_global.setValue("theme", "qdark")
    old_global.sync()
    old = make("KHLab", SD.series_app(app, series.code))
    old.setValue("backup_dir", str(tmp_path))
    old.sync()
    source_bytes = [Path(s.fileName()).read_bytes() for s in (old_global, old)]
    dialog = AllOptionsDialog(None, series)
    try:
        dialog.all_widgets["series_code"].inputs[0].widget.setText("changed-code")
        assert dialog.accept() is True
        assert series.getOption("backup_dir") == str(tmp_path)
        assert [Path(s.fileName()).read_bytes() for s in (old_global, old)] == source_bytes
    finally:
        dialog.close()
        series.close()
