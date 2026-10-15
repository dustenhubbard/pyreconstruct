import os
import json
import numpy as np

from PyReconstruct.modules.datatypes import Series, Transform
from PyReconstruct.modules.constants import getDateTime

from .import_transforms import TransformImportError


class IncorrectFormatError(TransformImportError):
    pass


class IncorrectSecNumError(TransformImportError):
    pass


class MissingScaleError(IncorrectFormatError):
    def __init__(self, scale):
        super().__init__(f"The SWiFT project has no transforms at scale {scale}.")


def cafm_to_matrix(t):
    """Convert c_afm to Numpy matrix."""
    return np.matrix([[t[0][0], t[0][1], t[0][2]],
                      [t[1][0], t[1][1], t[1][2]],
                      [0, 0, 1]])


def cafm_to_sanity(t, dim, scale_ratio=1, old_swift=False):
    """Convert c_afm to something sane."""

    # Convert to matrix
    t = cafm_to_matrix(t)

    # Transforms in older SWiFT project files are stored as inverted matrices
    if old_swift: t = np.linalg.inv(t)
    
    # Get translation of bottom left corner from img height (px)
    BL_corner = np.array([[0], [dim], [1]])  # original BL corner
    BL_translation = np.matmul(t, BL_corner) - BL_corner

    # Add BL corner translation to c_afm (x and y translation)
    t[0, 2] = BL_translation[0, 0] # x translation in px
    t[1, 2] = BL_translation[1, 0] # y translation in px

    # Flip y axis by changing signs of a2, b1, and b3
    t[0, 1] *= -1  # a2
    t[1, 0] *= -1  # b1
    t[1, 2] *= -1  # b3
    
    # Apply any scale ratio difference
    t[0, 2] *= scale_ratio
    t[1, 2] *= scale_ratio

    return t


def get_img_dim(scale_data):
    """Get image dimensions (height and width) from scale data."""
    return scale_data["swim_settings"]["img_size"]


def make_pyr_transforms(project_file, scale=1, cal_grid=False):
    """Return a list of PyReconstruct-formatted transformations."""

    swift_json = read_swift_project(project_file)

    try:
        pyr_transforms = stack_transforms(swift_json, scale)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError,
            np.linalg.LinAlgError):
        raise IncorrectFormatError(
            "The file is not a SWiFT project PyReconstruct can read."
        )

    if not pyr_transforms:
        raise IncorrectFormatError("The SWiFT project has no sections.")

    if cal_grid:
        pyr_transforms.insert(0, np.identity(3))

    return pyr_transforms


def read_swift_project(project_file):
    """Return the parsed JSON of a SWiFT project file."""
    try:
        with open(project_file, "r") as fp:
            swift_json = json.load(fp)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise IncorrectFormatError("The file is not a SWiFT project.")
    if not isinstance(swift_json, dict):
        raise IncorrectFormatError("The file is not a SWiFT project.")
    return swift_json


def swift_scales(swift_json):
    """Return the scales a SWiFT project lists, smallest first."""
    try:
        if swift_json.get("level_data"):  # new swift project file
            scales = [int(name[1:]) for name in swift_json["level_data"]]
        else:  # old swift project file
            scales = [int(name[6:]) for name in swift_json["data"]["scales"]]
    except (KeyError, TypeError, ValueError, AttributeError):
        raise IncorrectFormatError("The file is not a SWiFT project PyReconstruct can read.")
    if not scales:
        raise IncorrectFormatError("The SWiFT project lists no scales.")
    return sorted(scales)


def stack_transforms(swift_json, scale=1):
    """Return one transform per section of a SWiFT project, in stack order."""

    pyr_transforms = []  # list to hold transforms
    requested = scale

    stack_data = swift_json.get("stack")  # if exists

    if stack_data:  # new swift project file
    
        scale = f's{str(scale)}'  # requested scale as properly formatted string

        for section in stack_data:

            # Get all scales (or "levels")
        
            scales_all = section.get("levels") # all scales
            scale_req = scales_all.get(scale)  # requested scale
            scale_1 = scales_all.get("s1")     # scale 1
            if scale_req is None or scale_1 is None:
                raise MissingScaleError(requested if scale_req is None else 1)
            
            # When scaling, only height (px) is considered by this script.
            # Will change if aligning non-square images,
            # which is not currently supported by AlignEM-SWiFT.
            
            img_height_1, img_width_1 = get_img_dim(scale_1)
            img_height, img_width = get_img_dim(scale_req)
        
            height_ratio = img_height_1 / img_height
            width_ratio = img_width_1 / img_width  # left here for now 
        
            # Get section transform, make sane, append to list
            transform = scale_req.get("alt_cafm")
            transform = cafm_to_sanity(transform, dim=img_height, scale_ratio=height_ratio)
            pyr_transforms.append(transform)

    else:  # old swift project file

        scale = f'scale_{str(scale)}'
        scales_all = swift_json["data"]["scales"]
        
        if scale not in scales_all or "scale_1" not in scales_all:
            raise MissingScaleError(requested if scale not in scales_all else 1)
        scale_data = scales_all[scale]
        scale_data_1 = scales_all["scale_1"]
    
        stack_data = scale_data.get("stack")
        
        img_height_1, img_width_1 = scale_data_1.get('image_src_size')
        img_height, img_width = scale_data.get('image_src_size')

        height_ratio = img_height_1 / img_height
        width_ratio = img_width_1 / img_width

        for section in stack_data:
        
            # Get transform, make sane, append to list
            transform = section["alignment"]["method_results"]["cumulative_afm"]
            transform = cafm_to_sanity(transform, dim=img_height, scale_ratio=height_ratio, old_swift=True)
            pyr_transforms.append(transform)

    return pyr_transforms


def transforms_as_strings(recon_transforms, output_file=None):
    """Return transform matrices as string."""

    output = ''
    
    for i, t in enumerate(recon_transforms):
        string = f'{i} {t[0, 0]} {t[0, 1]} {t[0, 2]} {t[1, 0]} {t[1, 1]} {t[1, 2]}\n'
        output += string

    if output_file:
        with open(output_file, "w") as fp: fp.write(output)

    return output

        
def importSwiftTransforms(series: Series, project_fp: str, scale: int = 1, cal_grid: bool = False, series_states=None, log_event=True):
    """Import a SWiFT project's transforms as a new alignment.

    Returns a note for the user about where the cal grid transform went, or None.
    """

    new_transforms = make_pyr_transforms(project_fp, scale, cal_grid)
    new_transforms = transforms_as_strings(new_transforms)
    transforms_list = new_transforms.splitlines()

    # The SWiFT stack is in section order and its transforms are numbered from
    # 0, but a series can start at any section number (a series converted from
    # Reconstruct often starts at 1). Match them by position instead.
    section_nums = sorted(series.sections)

    if len(transforms_list) != len(section_nums):
        if cal_grid:
            stack_size = len(transforms_list) - 1
            message = (
                f"The SWiFT project has {stack_size} sections, so with the cal "
                f"grid this series needs {stack_size + 1}, and it has "
                f"{len(section_nums)}."
            )
        else:
            message = (
                f"The SWiFT project has {len(transforms_list)} sections, "
                f"and this series has {len(section_nums)}."
            )
        raise IncorrectSecNumError(message)

    # With the cal grid, the first transform is the identity and belongs to
    # the section marked as the cal grid. The stack goes to the others in order.
    note = None
    targets = section_nums
    if cal_grid:
        marked = calGridSections(series, section_nums)
        if len(marked) == 1:
            grid_num = marked[0]
        else:
            grid_num = section_nums[0]
            marked_text = f"{len(marked)} sections are" if marked else "No section is"
            note = (
                f"{marked_text} marked as the cal grid, so the identity "
                f"transform went to section {grid_num}, the first section."
            )
        targets = [grid_num] + [n for n in section_nums if n != grid_num]

    tforms = {}  # Empty dictionary to hold transformations
    
    for line, section_num in zip(transforms_list, targets):
        
        swift_sec, *matrix = line.split()
        
        if len(matrix) != 6:
            
            raise IncorrectFormatError(f"Project file (at index {swift_sec}) incorrect number of elements.")
        
        try:

            tforms[section_num] = [float(elem) for elem in matrix]
            
        except ValueError:
            
            raise IncorrectFormatError("Incorrect project file format.")
        
    # set tforms
    fname = os.path.basename(project_fp)
    fname = fname[:fname.rfind(".")]
    d, t = getDateTime()
    new_alignment_name = f"{fname}-{d}"
    
    for section_num, section in series.enumerateSections(
        message="Importing transforms...",
        series_states=series_states,
        breakable=False,
        writes_after=True,
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
        series.addLog(None, None, f"Import SWIFT transforms to alignment {series.alignment}")

    print("SWiFT transforms imported!")

    return note


def calGridSections(series: Series, section_nums):
    """Return the section numbers marked as the cal grid, in order."""
    marked = []
    for snum in section_nums:
        section_data = series.data["sections"].get(snum)
        if section_data is not None:
            is_grid = section_data.get("calgrid", False)
        else:  # series data was not loaded
            is_grid = series.loadSection(snum).calgrid
        if is_grid:
            marked.append(snum)
    return marked
