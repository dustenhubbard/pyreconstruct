from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QWidget,
    QDialog,
    QGridLayout,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QVBoxLayout,
    QScrollArea,
    QKeySequenceEdit,
    QStyle,
)
from PySide6.QtGui import QKeySequence, QAction

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.modifiers import (
    MODIFIER_KEYS,
    canonical,
    display_label,
    modifiers_to_string,
    resolve,
    usable_modifiers,
)
from PyReconstruct.modules.gui.utils import notify


#: Rows whose binding is a held modifier combination rather than a key sequence.
#: Keyed by the option name, valued by the placeholder shown when it is unbound.
MODIFIER_ROWS = {"focus_edit_modifier": "(no modifier: click alone edits nothing)"}

#: Keys that explicitly unbind the row, i.e. choose the documented "off" state.
#: A read-only `QLineEdit` swallows both and does nothing with them, so nothing
#: is taken away by giving them a meaning here.
UNBIND_KEYS = (Qt.Key_Backspace, Qt.Key_Delete)


class ModifierEdit(QLineEdit):
    """Capture whatever modifier combination the user holds.

    `QKeySequenceEdit` cannot do this. It drops a modifier-only key press on the
    floor and waits for a real key, and the strings that look like bare modifiers
    parse to *key codes* rather than modifier flags. `gui/modifiers.py` records
    both measurements. So the capture is written out here: accumulate the flags
    while modifier keys go down, commit the accumulation when one comes back up.

    Read-only, so the box cannot be typed into; it is filled by holding keys.

    **Unbinding is a gesture too.** An empty binding is a documented choice —
    `default_settings` says "empty means the edit click is off", `focus_edit_p`
    honours it, and `MODIFIER_ROWS` supplies a placeholder advertising it — but
    the accumulate/commit protocol above can only ever *add* flags, and
    `keyReleaseEvent` refuses to commit an empty accumulation. So the state was
    advertised with no gesture that reached it. Two are offered here, both
    landing on `setModifierString("")`:

    1. a trailing clear button, the affordance the key-sequence rows get from
       `setClearButtonEnabled(True)`; and
    2. `Backspace`/`Delete`, because that button cannot be reached from the
       keyboard.

    The button is built by hand rather than with `setClearButtonEnabled`, which
    does not work on a read-only box: Qt disables the clear action it installs
    (`clearAction->setEnabled(!isReadOnly())`) and disables an existing one when
    `setReadOnly(True)` is called later, so the button renders greyed and dead.
    Its action is also hardwired to `QLineEdit.clear`, which would blank the text
    while leaving `_value` — and therefore what `exec` harvests — untouched.
    `addAction(..., TrailingPosition)` is public API, is unaffected by
    read-only, and lets the row clear its *binding* rather than its text.
    """

    def __init__(self, value, parent=None, placeholder=""):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setPlaceholderText(placeholder)
        self._held = Qt.NoModifier
        self.clear_action = self.addAction(
            self.style().standardIcon(QStyle.SP_LineEditClearButton),
            QLineEdit.TrailingPosition,
        )
        self.clear_action.setToolTip(
            "Unbind, so that clicking alone edits nothing (Backspace)"
        )
        self.clear_action.triggered.connect(self.unbind)
        self.setModifierString(value)

    def modifierString(self) -> str:
        """The canonical stored form of the current binding."""
        return self._value

    def setModifierString(self, value):
        """Set the binding, dropping anything this platform cannot reach."""
        self._value = canonical(value)
        self.setText(display_label(self._value))
        # Nothing to clear when the row is already unbound, which mirrors the
        # key-sequence rows: Qt fades their clear button in with the text.
        self.clear_action.setVisible(bool(self._value))

    def unbind(self):
        """Choose the documented "off" state: no modifier, so no edit click.

        The accumulation is dropped along with the binding, so that letting go of
        a modifier held while unbinding cannot commit it straight back.
        """
        self._held = Qt.NoModifier
        self.setModifierString("")

    def keyPressEvent(self, event):
        """Accumulate. A non-modifier key is not a binding here, so it passes."""
        if event.key() in UNBIND_KEYS:
            self.unbind()
            event.accept()
            return

        flag = MODIFIER_KEYS.get(event.key())
        if flag is None:
            event.ignore()
            return

        # `usable_modifiers()` is what makes Meta unavailable on macOS rather
        # than merely discouraged: the flag never enters the accumulation, so
        # holding physical Control there leaves the existing binding alone.
        held = (flag | event.modifiers()) & usable_modifiers()
        if not held:
            event.ignore()
            return

        self._held |= held
        self.setText(display_label(modifiers_to_string(self._held)))
        event.accept()

    def keyReleaseEvent(self, event):
        """Commit what was accumulated, once the user starts letting go."""
        if event.key() not in MODIFIER_KEYS or not self._held:
            event.ignore()
            return

        self.setModifierString(modifiers_to_string(self._held))
        self._held = Qt.NoModifier
        event.accept()


class ShortcutsDialog(QDialog):

    def __init__(self, mainwindow : QWidget, series : Series):
        """Create a shortcuts dialog.
        
            Params:
                series (Series): the current sereis being used
        """
        super().__init__(mainwindow)
        self.mainwindow = mainwindow
        self.series = series

        grid = QGridLayout()
        self.act_widgets = {}
        self.modifier_widgets = {}

        for row, item in enumerate(help_shortcuts):
            if item is None:  # spacer
                grid.addWidget(QLabel(self, text=" "), row, 0)
            elif type(item) is str:  # header
                l = QLabel(self, text=item)
                f = l.font()
                f.setBold(True)
                l.setFont(f)
                grid.addWidget(l, row, 0)
            else:  # shortcut item
                sc, desc = tuple(item)
                if sc in MODIFIER_ROWS:
                    w = ModifierEdit(
                        self.effectiveBinding(sc), self, MODIFIER_ROWS[sc]
                    )
                    self.modifier_widgets[sc] = w
                elif sc.endswith("_act") and getattr(self.mainwindow, sc):
                    w = QKeySequenceEdit(self.series.getOption(sc), self)
                    w.setClearButtonEnabled(True)
                    self.act_widgets[sc] = w
                else:
                    w = QLabel(self, text=sc)
                grid.addWidget(w, row, 0)
                grid.addWidget(QLabel(self, text=desc), row, 1)
        
        QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        buttonbox = QDialogButtonBox(QBtn)
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.reject)

        reset_defaults_button = QPushButton("Reset Defaults")
        reset_defaults_button.clicked.connect(self.resetDefaults)
        buttonbox.addButton(reset_defaults_button, QDialogButtonBox.ResetRole)

        qsa = QScrollArea(self)
        w = QWidget(self)
        w.setLayout(grid)
        qsa.setWidget(w)

        vlayout = QVBoxLayout()
        vlayout.setSpacing(10)
        vlayout.addWidget(qsa)
        vlayout.addWidget(buttonbox)

        self.setLayout(vlayout)

    def effectiveBinding(self, name) -> str:
        """The modifier binding the user is actually getting, canonical form.

        Deliberately not the raw stored value. `resolve` is what `focus_edit_p`
        tests the click against, and it treats a binding that cannot fire on
        *this* platform as unreachable-so-fall-back rather than as off; only a
        deliberately empty binding means off. Seeding the row from the raw value
        instead breaks that distinction twice over, because `canonical` drops an
        unreachable flag rather than falling back:

        1. the row displays empty while the edit click is still working, so the
           dialog misreports the live state; and
        2. `exec` harvests every row whether or not the user touched it, so
           pressing OK on that untouched empty row persists `""` — which
           `resolve` then correctly reads as a deliberate, permanent unbinding.
           A stored `"meta"`, which on macOS is merely unreachable, becomes a
           silently dead edit click.

        Seeding from `resolve` fixes both: the row shows the fallback the user
        is really getting, and an untouched OK writes that same binding back.
        """
        return modifiers_to_string(
            resolve(
                self.series.getOption(name),
                self.series.getOption(name, get_default=True),
            )
        )

    def resetDefaults(self):
        """Reset the defaults for all fields."""
        for act, w in self.act_widgets.items():
            w.setKeySequence(self.series.getOption(act))
        for name, w in self.modifier_widgets.items():
            # `effectiveBinding`, not the raw option, for the same reason the
            # constructor uses it: this button is a second way to land an
            # unreachable stored value in the row, and the row is harvested on OK.
            w.setModifierString(self.effectiveBinding(name))
    
    def accept(self):
        """Called when user accepts the dialog."""
        # gather the modifiable actions
        modifiable_actions = []
        for act_name in self.act_widgets:
            modifiable_actions.append(getattr(self.mainwindow, act_name))
        
        # gather the static key sequences
        keyseqs = []
        for act in self.mainwindow.actions():
            if act.shortcut().toString() and act not in modifiable_actions:
                keyseqs.append(act.shortcut())
        
        # compare with the user-entered key sequences
        for input in self.act_widgets.values():
            ks = input.keySequence()
            if not ks.toString():
                continue
            if ks in keyseqs:
                notify(f"The keyboard shortcut '{ks.toString()}' is used more than once.")
                return
            keyseqs.append(ks)

        return super().accept()
    
    def exec(self):
        """Run the dialog."""
        confirmed = super().exec()

        if confirmed:
            shortcuts_dict = {}
            for act_name, keyseq in self.act_widgets.items():
                shortcuts_dict[act_name] = keyseq.keySequence().toString()
            # Modifier rows ride the same dict, and `resetShortcuts` stores them
            # without trying to hang them off a QAction. They are deliberately
            # not checked for collisions above: a held modifier is not a key
            # sequence and cannot duplicate one.
            for name, w in self.modifier_widgets.items():
                shortcuts_dict[name] = w.modifierString()
            return shortcuts_dict, True
        else:
            return None, False


def getStaticShortcuts(w : QWidget) -> list[QKeySequence]:
    """Get static shortcuts of the mainwindow."""
    keyseqs : list[QKeySequence] = []
    # get all of the static actions
    for aname in dir(w):
        if (
            aname.endswith("_act") and 
            aname not in Series.qsettings_defaults and
            type(getattr(w, aname)) is QAction
        ):
            qact : QAction = getattr(w, aname)
            keyseqs.append(qact.shortcut())
    # get all of the static shortcuts
    for sc in w.non_action_shortcuts:
        keyseqs.append(sc.key())
    
    return keyseqs
            

help_shortcuts = [
    "General",
    ("Delete/Backspace", "Delete selected traces"),
    ("", "Remove last point when polyline tracing or using scissors."),
    ("", "Delete selected entry in lists"),
    ("? (Shift+/)", "Display keyboard shortcuts"),
    ("alloptions_act", "View all options"),
    ("Page Up", "Display the next (higher) section"),
    ("Page Down", "Display the preceding (lower) section"),
    ("flicker_act", "Switch between current and last viewed section"),
    None,
    "View",
    ("focus_act", "Focus mode"),
    ("focus_edit_modifier", "Hold and click in focus mode to split or incorporate a trace"),
    ("hideall_act", "Hide trace layer"),
    ("showall_act", "Show all traces (ignore hidden)"),
    ("hideimage_act", "Hide image"),
    ("decbr_act", "Decrease brightness"),
    ("incbr_act", "Increase brightness"),
    ("deccon_act", "Decrease contrast"),
    ("inccon_act", "Increase contrast"),
    ("blend_act", "Section blend"),
    ("homeview_act", "Set view to image"),
    None,
    "Field Interactions",
    ("selectall_act", "Select all traces on section"),
    ("deselect_act", "Deselect all traces on section"),
    ("invertselection_act", "Invert which traces are selected on section"),
    ("edittrace_act", "Edit attributes of selected trace(s)"),
    ("mergetraces_act", "Merge selected traces"),
    ("mergeobjects_act", "Merge attributes of selected traces"),
    ("hidetraces_act", "Hide selected traces"),
    ("unhideall_act", "Unhide all hidden traces on current section"),
    ("pastetopalette_act", "Modify current palette button to match attributes of first selected trace"),
    ("pastetopalettewithshape_act", "Modify current palette button to match attributes and shape of first selected trace"),
    ("unlocksection_act", "Unlock current section"),
    ("changetform_act", "Modify transform on current section"),
    ("sethosts_act", "Set host(s) for selected trace(s)"),
    None,
    "Edit",
    ("undo_act", "Undo"),
    ("redo_act", "Redo"),
    ("copy_act", "Copy selected traces to clipboard"),
    ("copytosections_act", "Copy selected traces onto other sections"),
    ("addobjto3D_act", "Add selected object(s) to the 3D scene"),
    ("cut_act", "Cut selected traces to clipboard"),
    ("paste_act", "Paste clipboard traces into section"),
    ("pasteattributes_act", "Apply attributes of copied traces to selected trace(s)"),
    None,
    "Navigate",
    ("findobjectfirst_act", "Find first instance of a trace in the series"),
    ("findcontour_act", "Find a trace on the current section"),
    ("goto_act", "Go to a specific section number"),
    None,
    "File",
    ("open_act", "Open a series file"),
    ("save_act", "Save"),
    ("manualbackup_act", "Backup series"),
    ("newfromimages_act", "New series"),
    ("restart_act", "Restart"),
    ("quit_act", "Quit"),
    None,
    "Lists",
    ("objectlist_act", "Open Object List"),
    ("togglecuration_act", "Toggle curation columns in object list"),
    ("tracelist_act", "Open Trace List"),
    ("ztracelist_act", "Open Z-trace List"),
    ("sectionlist_act", "Open Section List"),
    ("flaglist_act", "Open Flag List"),
    ("changealignment_act", "Switch/modify alignments"),
    None,
    "Trace Palette",
    ("#, Shift+#", "Select a trace on the palette"),
    ("Ctrl+#, Ctrl+Shift+#", "Edit attributes of a single trace on the palette"),
    ("modifytracepalette_act", "Switch/modify palettes"),
    ("incpaletteup_act", "Increment palette {#} up"),
    ("incpalettedown_act", "Increment palette {#} down"),
    None,
    "Movements",
    ("Left/Right/Up/Down", "Translate selected traces or image (when no trace selected)"),
    ("Ctrl+Left/Right/Up/Down", "Translate traces or image by small step"),
    ("Shift+Left/Right/Up/Down", "Translate trace or image by large step"),
    ("Ctrl+Shift+Left/Right/Up/Down", "Rotate image around the mouse"),
    ("F1, Shift+F1, F2, Shift+F2", "Scale image in X and Y"),
    ("F3, Shift+F3, F4, Shift+F4", "Shear image in X and Y"),
    None,
    "Tool Palette",
    ("usepointer_act", "Use pointer tool"),
    ("usepanzoom_act", "Use pan/zoom tool"),
    ("useknife_act", "Use knife tool"),
    ("usectrace_act", "Use closed trace tool"),
    ("useotrace_act", "Use open trace tool"),
    ("usestamp_act", "Use stamp tool"),
    ("usegrid_act", "Use grid tool"),
    ("useflag_act", "Use flag tool"),
    ("usehost_act", "Use host tool"),
    None,
    "3D Scene:",
    ("? (Shift+/)", "Display shortcuts in 3D scene"),
]
