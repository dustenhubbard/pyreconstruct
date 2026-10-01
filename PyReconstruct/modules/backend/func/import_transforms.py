import os

from PyReconstruct.modules.datatypes import Series, Transform
from PyReconstruct.modules.constants import getDateTime


class TransformImportError(Exception):
    """A transforms file that cannot be imported. The message is for the user."""


def importTransforms(series : Series, tforms_fp : str, series_states=None, log_event=True):
        """Import transforms from a text file.
        
            Params:
                series (Series): the series to import transforms to
                tforms_fp (str): the file path for the transforms file
                series_states (SereisStates): series states object from GUI
        """
        # read through file
        with open(tforms_fp, "r") as f:
            lines = f.readlines()
        tforms = {}
        for line_num, line in enumerate(lines, start=1):
            nums = line.split()
            if not nums:
                continue  # a blank line, such as an extra newline at the end
            try:
                if len(nums) != 7:
                    raise ValueError
                section_num = int(nums[0])
                tform = [float(n) for n in nums[1:]]
            except ValueError:
                raise TransformImportError(
                    f"Line {line_num} is not a section number followed by "
                    "six transform numbers."
                )
            if section_num not in series.sections:
                raise TransformImportError(
                    f"Line {line_num} is for section {section_num}, "
                    "which is not in this series."
                )
            tforms[section_num] = tform
        if not tforms:
            raise TransformImportError("The file has no transforms.")
        
        # set tforms
        fname = os.path.basename(tforms_fp)
        fname = fname[:fname.rfind(".")]
        d, t = getDateTime()
        new_alignment_name = f"{fname}-{d}"
        for section_num, section in series.enumerateSections(
            message="Importing transforms...",
            series_states=series_states,
            breakable=False
        ):
            if section_num in tforms:
                tform = tforms[section_num]
                # multiply pixel translations by magnification of section
                tform[2] *= section.mag
                tform[5] *= section.mag
            else:
                tform = section.tform.getList()
            section.tforms[new_alignment_name] = Transform(tform)
            section.save()
        series.alignment = new_alignment_name
        series.save()
        
        # log event
        if log_event:
             series.addLog(None, None, f"Import transforms to alignment {series.alignment}")
