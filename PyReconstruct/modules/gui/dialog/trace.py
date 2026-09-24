from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QCheckBox,
    QComboBox,
    QRadioButton
)

from .color_button import ColorButton
from .shape_button import ShapeButton
from .helper import resizeLineEdit
from .quick_dialog import MultiInput

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.utils import notify

class TraceDialog(QDialog):

    def __init__(
            self,
            parent : QWidget, 
            traces : list[Trace]=[],
            name=None,
            color=None,
            color_mixed=False,
            tags=None,
            is_palette=False,
            is_obj_list=False,
            pos=None,
            tag_sets=None):
        """Create an attribute dialog.
        
            Params:
                parent (QWidget): the parent widget
                traces (list): a list of traces
                pos (tuple): the point to create the dialog
                tag_sets (TagSets): the series' tag sets. Each pick-one set
                    gets its own labeled dropdown; the pick-many values are
                    offered in the Tags rows. None or empty keeps plain rows.

        After exec(), ``tag_choices`` holds the pick-one rows' answer as
        ``TagSets.apply`` reads it: set name -> value, "" for cleared, None
        for a row the selection disagreed on and the user left alone. It is
        empty when the series has no pick-one set. The returned trace's
        ``tags`` is the free Tags rows' answer only, so a consumer combines
        the two with ``TagSets.resolve``.
        """
        super().__init__(parent)
        self.tag_sets = tag_sets
        self.tag_choices = {}

        # the pick-one sets, and every value they hold. Those values are shown
        # in their own dropdowns and hidden from the free Tags rows, so the
        # free rows carry only what no pick-one set governs.
        pick_one_names = tag_sets.pickOneSets() if tag_sets is not None else []
        pick_one_values = set()
        for set_name in pick_one_names:
            pick_one_values.update(tag_sets.tags(set_name))

        # move to desired position
        if pos:
            self.move(*pos)

        self.is_palette = is_palette
        self.is_obj_list = is_obj_list

        # True when the selection did not agree on a single set of tags, so the
        # tags field is displayed blank because there is nothing to display and
        # NOT because the traces have no tags. exec() needs the distinction: a
        # blank field means "no value chosen" here, and "clear the tags"
        # otherwise. MultiInput cannot carry it, since it renders both None and
        # an empty set as one empty row.
        self.tags_mixed = False

        # Same distinction per pick-one set: the value to seed its dropdown
        # with, and whether a blank seed means "the selection disagrees" (so an
        # untouched blank is "leave alone") rather than "no value" (so a blank
        # on OK clears the set).
        pick_one_seed = {}
        self.pick_one_mixed = {}

        # get the display values if traces have been provided
        if traces:
            trace = traces[0]
            name = trace.name
            color = trace.color
            ct = trace.copy()
            ct.resize(1)
            points = ct.points
            # the free part only: the pick-one values have their own rows
            tags = trace.tags - pick_one_values
            fill_style, fill_condition = trace.fill_mode
            for set_name in pick_one_names:
                pick_one_seed[set_name] = tag_sets.chosen(set_name, trace.tags)
                self.pick_one_mixed[set_name] = False

            # keep track of the traces passed
            self.traces = traces

            # only include radius for editing single palette traces
            if self.is_palette:
                assert(len(traces) == 1)

            for trace in traces[1:]:
                if trace.name != name:
                    name = "*"
                if trace.color != color:
                    color = None
                if trace.points != points:
                    points = None
                if trace.tags - pick_one_values != tags:
                    tags = set()
                    self.tags_mixed = True
                for set_name in pick_one_names:
                    if tag_sets.chosen(set_name, trace.tags) != pick_one_seed[set_name]:
                        pick_one_seed[set_name] = ""
                        self.pick_one_mixed[set_name] = True
                if trace.fill_mode[0] != fill_style:
                    fill_style = None
                if trace.fill_mode[1] != fill_condition:
                    fill_condition = None
        else:
            if not name:
                name = "*"
            if tags is None:
                # The caller had no single value to supply. The object list
                # passes tags=None for a multi-object selection, which is the
                # same "selection disagrees" case as the loop above.
                self.tags_mixed = True
                for set_name in pick_one_names:
                    pick_one_seed[set_name] = ""
                    self.pick_one_mixed[set_name] = True
            else:
                # The object list passes the union of an object's tags across
                # its traces. One value of a set means the traces agree on it;
                # two or more means they do not, so the row shows blank and
                # an untouched OK leaves every trace's own value alone.
                for set_name in pick_one_names:
                    present = [t for t in tag_sets.tags(set_name) if t in tags]
                    if len(present) == 1:
                        pick_one_seed[set_name] = present[0]
                        self.pick_one_mixed[set_name] = False
                    else:
                        pick_one_seed[set_name] = ""
                        self.pick_one_mixed[set_name] = len(present) > 1
                tags = set(tags) - pick_one_values
            if not tags:
                tags = set()
            fill_style = None
            fill_condition = None

        self.setWindowTitle("Set Attributes")

        name_row = QHBoxLayout()
        name_text = QLabel(self, text="Name:")
        self.name_input = QLineEdit(self)
        self.name_input.setText(name)
        name_row.addWidget(name_text)
        name_row.addWidget(self.name_input)

        color_row = QHBoxLayout()
        color_text = QLabel(self, text="Color:")
        # color_mixed marks a seed that is only the PREDOMINANT color of a
        # selection whose traces disagree; the swatch shows it as a diagonal
        # split so the discrepancy is visible before the user decides to
        # repaint (object-list path only; the trace path seeds None on
        # disagreement, which is a blank swatch).
        self.color_input = ColorButton(color, self, mixed=color_mixed)
        color_row.addWidget(color_text)
        color_row.addWidget(self.color_input)
        color_row.addStretch()

        if self.is_palette:
            shape_row = QHBoxLayout()
            shape_text = QLabel(self, text="Shape:")
            self.shape_input = ShapeButton(points, self)
            shape_row.addWidget(shape_text)
            shape_row.addWidget(self.shape_input)
            shape_row.addStretch()

        # one labeled, restricted dropdown per pick-one set, blank allowed.
        # Seeded BEFORE the change signals are connected, so only the user can
        # mark a row touched; a mixed row left untouched answers None.
        self.pick_one_inputs = {}
        self.pick_one_touched = {}
        pick_one_rows = QVBoxLayout()
        for set_name in pick_one_names:
            row = QHBoxLayout()
            row.addWidget(QLabel(self, text=f"{set_name}:"))
            combo = QComboBox(self)
            combo.addItem("")
            for value in tag_sets.tags(set_name):
                combo.addItem(value)
                tip = tag_sets.description(set_name, value)
                if tip:
                    combo.setItemData(combo.count() - 1, tip, Qt.ToolTipRole)
            combo.setCurrentText(pick_one_seed[set_name])
            self.pick_one_touched[set_name] = False
            combo.activated.connect(
                lambda _, n=set_name: self.pick_one_touched.__setitem__(n, True)
            )
            combo.currentIndexChanged.connect(
                lambda _, n=set_name: self.pick_one_touched.__setitem__(n, True)
            )
            row.addWidget(combo)
            self.pick_one_inputs[set_name] = combo
            pick_one_rows.addLayout(row)

        tags_text = QLabel(self, text="Tags:")
        # sorted because trace.tags is a set: unsorted, a tag lands on a
        # different row each time the dialog opens, so the row a user is part
        # way through editing is not the row they left off on
        known_tags = tag_sets.allTags() if tag_sets is not None else []
        known_tags = [t for t in known_tags if t not in pick_one_values]
        if known_tags:
            # dropdown rows: every pick-many tag with completion and its
            # description as a tooltip. Typed text outside the sets is still
            # accepted (pick many allows user values).
            self.tags_input = MultiInput(
                self,
                sorted(tags),
                combo=True,
                combo_items=known_tags,
                restrict_to_opts=False,
                combo_tooltips={t: tag_sets.describe(t) for t in known_tags},
            )
        else:
            self.tags_input = MultiInput(self, sorted(tags))

        # created here, SEEDED after the radios below: the radios' toggled
        # handler reaches these, so they must exist before any radio flips
        self.selected_input = QCheckBox("Fill when selected")
        self.unselected_input = QCheckBox("Fill when unselected")

        style_row = QHBoxLayout()
        style_text = QLabel(self, text="Fill:")
        self.style_none = QRadioButton("None")
        self.style_none.toggled.connect(self.checkDisplayCondition)
        self.style_transparent = QRadioButton("Transparent")
        self.style_transparent.toggled.connect(self.checkDisplayCondition)
        self.style_solid = QRadioButton("Solid")
        self.style_solid.toggled.connect(self.checkDisplayCondition)
        if fill_style == "none":
            self.style_none.setChecked(True)
        elif fill_style == "transparent":
            self.style_transparent.setChecked(True)
        elif fill_style == "solid":
            self.style_solid.setChecked(True)
        else:
            self.checkDisplayCondition()

        # The condition is seeded LAST. Seeding the radios above fired
        # checkDisplayCondition, whose force-check of both boxes is the reset
        # a real style switch wants -- but during construction it clobbered
        # the trace's stored condition, so a trace filled "when selected"
        # opened with both boxes ticked and an untouched OK silently wrote
        # "always" onto every selected trace (found 2026-08-28).
        self.selected_input.setChecked(fill_condition in ("selected", "always"))
        self.unselected_input.setChecked(
            fill_condition in ("unselected", "always")
        )
        style_row.addWidget(style_text)
        style_row.addWidget(self.style_none)
        style_row.addWidget(self.style_transparent)
        style_row.addWidget(self.style_solid)

        if self.is_palette:
            stamp_size_row = QHBoxLayout()
            stamp_size_text = QLabel(self, text="Stamp radius (microns):")
            self.stamp_size_input = QLineEdit(self)
            self.stamp_size_input.setText(str(round(trace.getRadius(), 6)))
            stamp_size_row.addWidget(stamp_size_text)
            stamp_size_row.addWidget(self.stamp_size_input)
        
        if self.is_obj_list:
            range_row = QHBoxLayout()
            range_text1 = QLabel(self, text="From section")
            range_text2 = QLabel(self, text="to")

            self.range_input1 = QLineEdit(self)
            self.range_input1.setText(str(min(parent.series.sections.keys())))
            resizeLineEdit(self.range_input1, "0000")
            self.range_input2 = QLineEdit(self)
            self.range_input2.setText(str(max(parent.series.sections.keys())))
            resizeLineEdit(self.range_input2, "0000")

            range_row.addWidget(range_text1)
            range_row.addWidget(self.range_input1)
            range_row.addWidget(range_text2)
            range_row.addWidget(self.range_input2)

        QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        buttonbox = QDialogButtonBox(QBtn)
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.reject)

        vlayout = QVBoxLayout()
        vlayout.setSpacing(10)
        vlayout.addLayout(name_row)
        vlayout.addLayout(color_row)
        if self.is_palette: vlayout.addLayout(shape_row)
        if self.pick_one_inputs: vlayout.addLayout(pick_one_rows)
        vlayout.addWidget(tags_text)
        vlayout.addWidget(self.tags_input)
        vlayout.addLayout(style_row)
        vlayout.addWidget(self.selected_input)
        vlayout.addWidget(self.unselected_input)
        if self.is_palette: vlayout.addLayout(stamp_size_row)
        if self.is_obj_list: vlayout.addLayout(range_row)
        vlayout.addWidget(buttonbox)

        self.setLayout(vlayout)
    
    def checkDisplayCondition(self):
        """Determine whether the "fill when selected" checkbox should be displayed."""
        if self.style_transparent.isChecked() or self.style_solid.isChecked():
            self.selected_input.show()
            self.selected_input.setChecked(True)
            self.unselected_input.show()
            self.unselected_input.setChecked(True)
        else:
            self.selected_input.hide()
            self.selected_input.setChecked(False)
            self.unselected_input.hide()
            self.unselected_input.setChecked(True)
    
    def accept(self):
        """Overwritten from parent class."""
        if self.is_palette:
            try:
                r = float(self.stamp_size_input.text())
            except ValueError:
                notify("Please enter a valid number.")
                return
            if r <= 0:
                # zero collapses every point onto the centroid; negative
                # mirrors the shape (found 2026-08-28)
                notify("Please enter a positive number.")
                return
        if self.is_obj_list:
            try:
                r1 = int(self.range_input1.text())
                r2 = int(self.range_input2.text())
            except ValueError:
                notify("Please enter a valid integer")
                return
            if r1 < 0 or r2 < 0 or r1 > r2:
                notify("Please enter a valid range.")
                return
        
        super().accept()
    
    def exec(self):
        """Run the dialog."""
        confirmed = super().exec()
        if confirmed:
            # create a dummy trace to return
            trace = Trace(None, None, None)

            # name
            name = self.name_input.text()
            if name == "*" or name == "":
                name = None
            trace.name = name

            # color
            color = self.color_input.getColor()
            if self.is_obj_list and not self.color_input.picked:
                # The swatch was seeded for display (the objects' current
                # color on the open section, or blank when they disagree or
                # are not there). Unless the user actually confirmed a color
                # in the picker, no new value was chosen: return None, which
                # every consumer reads as "leave the existing colors alone".
                # Same distinction the tags field draws with tags_mixed
                # below; without it, an untouched OK would write the one
                # seeded color onto every trace of a mixed-color object.
                color = None
            trace.color = color

            # tags
            tags = set(self.tags_input.getEntries())
            if self.tags_mixed and not tags:
                # The field was blank because the selection disagreed, and the
                # user left it blank, so no new value was chosen. Return None,
                # which every consumer reads as "leave the existing tags
                # alone". An empty set here means "replace with no tags" and
                # would erase the tags of every selected trace.
                tags = None
            trace.tags = tags

            # pick-one rows: value, "" for cleared, None for a mixed row the
            # user never touched. A pick-one value typed into a free Tags row
            # stands in for a blank dropdown, so the typed word is not undone
            # by the empty row beside it.
            self.tag_choices = {}
            for set_name, combo in self.pick_one_inputs.items():
                value = combo.currentText()
                if not value and self.pick_one_mixed[set_name] and not self.pick_one_touched[set_name]:
                    value = None
                if not value:
                    for typed in self.tag_sets.tags(set_name):
                        if tags is not None and typed in tags:
                            value = typed
                            break
                self.tag_choices[set_name] = value

            # shape
            if self.is_palette:
                points = self.shape_input.getShape()
                trace.points = points
            else:
                trace.points = None
            
            # fill mode
            if self.style_none.isChecked():
                style = "none"
                condition = "none"
            elif self.style_transparent.isChecked():
                style = "transparent"
            elif self.style_solid.isChecked():
                style = "solid"
            else:
                style = None
                condition = None
            
            if style in ("transparent", "solid"):
                sel = self.selected_input.isChecked()
                unsel = self.unselected_input.isChecked()
                if sel and unsel:
                    condition = "always"
                elif sel:
                    condition = "selected"
                elif unsel:
                    condition = "unselected"
                else:
                    style = "none"
                    condition = "none"
            
            trace.fill_mode = (style, condition)

            # radius
            if self.is_palette:
                stamp_size = float(self.stamp_size_input.text())
                trace.resize(stamp_size)
            
            # section range
            if self.is_obj_list:
                r1 = int(self.range_input1.text())
                r2 = int(self.range_input2.text())
                sections = tuple(range(r1, r2+1))
            
            # notify user if name is changed
            if trace.name and trace.name != self.name_input.text():
                notify(f'Invalid name "{self.name_input.text()}" changed to "{trace.name}".')

            if self.is_obj_list:
                return (trace, sections),  True
            else:
                return trace, True
        
        # user pressed cancel
        else:
            return None, False
