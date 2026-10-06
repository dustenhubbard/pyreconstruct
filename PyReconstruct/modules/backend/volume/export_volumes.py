"""Export 3D objects."""

import importlib.util
from pathlib import Path
from typing import List, Union

import numpy as np
import trimesh

from .objects_3D import Surface, Spheres, Contours

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.utils import notify


def collada_available() -> bool:
    """Return True when the optional 'pycollada' package is importable.

    Collada (.dae) export goes through trimesh's Collada writer, which imports
    'pycollada' lazily. That package is NOT bundled by PyInstaller, so a frozen
    ("packaged") build never has it available. Callers use this to gray out the
    .dae menu item up front instead of offering an export that can only fail.
    Uses ``find_spec`` so it merely checks importability without importing.
    """
    return importlib.util.find_spec("collada") is not None


def _objectProgress(series: Series, text: str):
    """A progress bar over a per-object pass, with a time estimate.

    The section pass in get_3D_meshes has its own bar; the mesh writing and
    measuring that follow it had none (fork #421 review), and on a large object
    the marching-cubes step is the slow half. A factory that predates the eta
    flag still works, without the estimate.
    """
    factory = series._progressReporterFactory()
    try:
        return factory(text=text, cancel=False, eta=True)
    except TypeError:
        return factory(text=text, cancel=False)


def export3DObjects(series: Series, obj_names : list, output_dir : str, export_type: str, notify_user: bool = True) -> None:
    """Export 3D objects.

        Params:
            series (Series): the series containing the object data
            obj_names (list): a list of objects to export
            output_dir (str): directory to place exported files
            export_type (str): export format
        Returns:
            void
    """

    ## Collada (.dae) export needs the optional 'pycollada' package (trimesh's
    ## Collada writer imports it lazily and otherwise raises a bare
    ## ModuleNotFoundError). The menu normally disables .dae when it is absent
    ## (see collada_available), but keep this as a backstop -- surface the
    ## requirement here, before any work, so the user gets a clear message
    ## instead of an unhandled traceback.
    if export_type == "dae":
        try:
            import collada  # noqa: F401  (provided by the 'pycollada' package)
        except ImportError:
            if notify_user:
                notify(
                    "Collada (.dae) export needs the optional 'pycollada' "
                    "package, which is not available in this installation.\n\n"
                    "In a pip/uv environment you can install it (e.g. "
                    "'pip install pycollada'); packaged (frozen) builds do not "
                    "include Collada support. Otherwise choose another export "
                    "format."
                )
            return

    ## Collect 3D objects (single pass over the sections)

    obj_data = get_3D_meshes(series, obj_names)

    ## Iterate through objects and export 3D meshes

    output_directory = Path(output_dir)

    skipped = []
    # finish() in a finally, not through the reporter's context manager: the
    # bar has no Cancel button and closes only at 100%, and __exit__ skips
    # finish() when the block raises. A failed write (unwritable folder, disk
    # full, a degenerate mesh) would otherwise leave the window blocked behind
    # it, the hang found 2026-08-28 in saveJser and enumerateSections.
    progress = _objectProgress(series, "Writing 3D meshes...")
    try:
        for i, (obj_name, obj_3D) in enumerate(obj_data.items()):
            progress.set_progress(100 * i / max(len(obj_data), 1))

            output_file = output_directory / f"{obj_name}.{export_type}"

            if type(obj_3D) is Surface or type(obj_3D) is Spheres:

                obj_3D.exportTrimesh(
                    output_file,
                    export_type,
                )
            else:
                # a contours-mode object has no mesh to write; claiming success
                # for it sent users hunting for files that were never made
                # (found 2026-08-28)
                skipped.append(obj_name)
    finally:
        progress.finish()

    if notify_user:

        message = f"Object(s) exported to directory:\n\n{Path(output_directory).absolute()}\n"
        if skipped:
            names = ", ".join(sorted(skipped))
            message += (
                f"\nNot exported (3D mode is 'contours', which has no mesh): "
                f"{names}. Switch their 3D mode to surface or spheres to "
                f"export them."
            )
        notify(message)


def export3DData(series: Series, obj_names: list, output_fp: str, notify_user: bool=True) -> None:
    """Export quantitative data from meshes."""

    sep = ","
    csv_str = f"Series{sep}Name{sep}MeshType{sep}SurfaceArea{sep}Volume\n"
    series_code = series.code

    errors = {}
    skipped = []

    ## Build all meshes in a single pass over the sections
    meshes = get_3D_meshes(series, obj_names)

    # same shape as the write loop above, so the bar closes on every road out
    progress = _objectProgress(series, "Measuring 3D meshes...")
    try:
        for i, obj in enumerate(obj_names):
            progress.set_progress(100 * i / max(len(obj_names), 1))

            # a contours-mode object is open slabs with no surface or volume;
            # counting it as an error kept the whole CSV from being written,
            # so the objects that did measure were lost too (found 2026-09-30)
            if type(meshes[obj]) is Contours:
                skipped.append(obj)
                continue

            try:

                obj_data = meshes[obj]
                obj_type = type(obj_data).__name__.lower()
                area, vol = obj_data.measure()

                surface_area = round(area, 5)
                volume = round(vol, 5)

                csv_str += f"{series_code}{sep}{obj}{sep}{obj_type}{sep}{surface_area}{sep}{volume}\n"

            except Exception as e:

                errors[obj] = e
    finally:
        progress.finish()

    skipped_note = ""
    if skipped:
        names = ", ".join(sorted(skipped))
        skipped_note = (
            f"\nNot measured (3D mode is 'contours', which has no surface or "
            f"volume): {names}. Switch their 3D mode to surface or spheres to "
            f"measure them."
        )

    # one object that fails to measure used to keep the whole CSV from being
    # written; the rows that did measure are written and the failures named
    error_note = ""
    if errors:
        print(errors)
        names = ", ".join(sorted(errors))
        error_note = f"\nCould not be measured (see console): {names}."

    measured = len(obj_names) - len(skipped) - len(errors)

    if measured or not obj_names:

        with open(output_fp, "w") as fp:
            fp.write(csv_str)

        if notify_user:
            notify(
                f"Data exported to:\n\n{Path(output_fp).absolute()}\n"
                + skipped_note + error_note
            )

    elif notify_user:

        notify("No data exported.\n" + skipped_note + error_note)


def _init_3D_obj(series: Series, obj_name: str) -> Union[Surface, Spheres, Contours]:
    """Create the initial (empty) 3D object for the object's configured mode."""

    mode = series.getAttr(obj_name, "3D_mode")

    if mode == "surface":
        return Surface(obj_name, series)

    elif mode == "spheres":
        return Spheres(obj_name, series)

    elif mode == "contours":
        return Contours(obj_name, series)


def get_3D_meshes(series: Series, obj_names: list) -> dict:
    """Get meshes for several objects in a SINGLE pass over the sections.

    Each section is loaded from disk once and its traces distributed to every
    requested object, instead of re-scanning the whole series once per object.

        Params:
            series (Series): the series containing the object data
            obj_names (list): the objects to build meshes for
        Returns:
            (dict): obj_name -> Surface/Spheres/Contours
    """
    obj_data = {name: _init_3D_obj(series, name) for name in obj_names}

    # precompute each object's alignment once (not once per section)
    alignments = {name: series.getAttr(name, "alignment") for name in obj_data}
    wanted = set(obj_data)

    # This runs on the GUI thread (the export menu entries), and it used to run
    # silently over every section (fork #421: "3D has no bar at all"). Show the
    # pass, with an estimate, and load only the sections that hold the objects.
    for snum, section in series.enumerateSections(
        message="Building 3D meshes...",
        section_numbers=sorted(series.getObjectSections(obj_names)),
    ):

        for obj_name in (wanted & section.contours.keys()):

            obj_alignment = alignments[obj_name]

            if not obj_alignment:
                tform = section.tform
            else:
                tform = section.tforms[obj_alignment]

            for trace in section.contours[obj_name]:
                obj_data[obj_name].addTrace(trace, snum, tform)

    return obj_data


def get_3D_mesh(series: Series, obj_name: str) -> Union[Surface, Spheres, Contours]:
    """Get mesh for a single object."""

    return get_3D_meshes(series, [obj_name])[obj_name]


def convert_vedo_to_tm(obj) -> trimesh.Trimesh:
    """Convert vtk/vedo meshes to trimesh meshes."""

    polydata = obj.msh.polydata()
    points = polydata.GetPoints()

    ## Scale cube be different yo
    if obj.name == "Scale Cube":

        n_points = points.GetNumberOfPoints()
        point_array = np.zeros((n_points, 3))

        for i in range(n_points):
            point_array[i] = points.GetPoint(i)

        mesh = trimesh.Trimesh(vertices=point_array)

        return mesh.convex_hull

    verts = np.array(
        [points.GetPoint(i) for i in range (points.GetNumberOfPoints())]
    )

    faces = []

    for i in range(polydata.GetNumberOfCells()):

        cell = polydata.GetCell(i)
        face = [cell.GetPointId(j) for j in range(cell.GetNumberOfPoints())]

        if len(face) == 3:  # make sure trianglulated

            faces.append(face)

    mesh = trimesh.Trimesh(
        vertices=verts,
        faces=np.array(faces)
    )

    return mesh


def return_mesh_mtl(obj, name: str = None) -> str:
    """Make mtl file string for an exported obj.

        Params:
            obj: the scene object (supplies the color)
            name (str): the material name (default: the object's name)
    """

    col_norm = list(
        map(lambda x: x/255, obj.color)
    )

    mtl_str = (
        f"newmtl {obj.name if name is None else name}\n"
        f"Ka {col_norm[0]} {col_norm[1]} {col_norm[2]}\n"
        f"Kd {col_norm[0]} {col_norm[1]} {col_norm[2]}\n"
        f"Ks 0.5 0.5 0.5\n"
        f"Ns 10.0\n"
    )

    return mtl_str


def combine_mtl_files(mtl_list: List[Path], combo_file: Path, remove: bool=True) -> None:
    """Combine multiple mtl files into a single file."""

    with (combo_file).open("w") as mtl_combo:

        for f in mtl_list:

            with f.open("r") as one_mtl:
                mtl_combo.write(one_mtl.read() + "\n")

            if remove:

                f.unlink()

    return None


def combine_obj_files(obj_list: List[Path], combo_file: Path, remove: bool=True) -> None:
    """Combine multiple obj files into a single file."""

    mtl_file = combo_file.with_suffix('.mtl')
    
    with combo_file.open("w") as obj_combo:

        pyrecon_plug = "# Exported from PyReconstruct 3D scene\n"
        mtl_info = f"mtllib {mtl_file.name}\n"

        obj_intro = pyrecon_plug
        
        if mtl_file.exists():
            obj_intro += mtl_info

        obj_combo.write(obj_intro)

    line_tracker = 0

    for f in obj_list:

        obj_lines = f.read_text().split("\n")
        del obj_lines[0:2]  # remove first two lines in obj file

        ## Adjust face indices
        obj_lines = list(
            map(lambda elem: alter_face_indices(elem, line_tracker), obj_lines)
        )

        with combo_file.open("a") as obj_combo:

            for line in obj_lines:
                obj_combo.write(line + "\n")
                
        n_verts = sum([l.startswith("v ") for l in obj_lines])
        line_tracker += n_verts

        if remove:
            
            f.unlink()

    return None


def alter_face_indices(obj_line, add):
    """Alter face indices when combining obj files."""

    if not obj_line.startswith("f "):

        return obj_line

    line_parts = obj_line.strip().split(" ")

    _, x, y, z = line_parts

    return f"f {int(x) + add} {int(y) + add} {int(z) + add}"
