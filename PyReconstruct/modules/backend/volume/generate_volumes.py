from typing import Union

from .objects_3D import Surface, Spheres, Contours, Ztrace3D

from PyReconstruct.modules.datatypes import Series


Series_like_obj = Union[Series, str]  # can be type statement in >=3.12


def generateVolumes(series_like : Series_like_obj, objs : dict, ztraces : dict, progress=None):
    """Generate the volume items for a set of objects.
    
        Params:
            series_like (Series or str): The series of fp to a series containing object data
            objs (dict): a dict of objects to construct (dict containing name, color, alpha, tform)
            ztrace_names (list): the list of ztraces to construct (dict containing name, color, alpha, tform)
            progress (callable): optional, called with a 0-100 percent as the
                work advances. This function runs on the 3D worker thread, so
                it cannot show a bar itself; the caller's GUI side does that
                from these reports (fork #421). The section pass is the first
                80 percent, the meshing the last 20.
        Returns:
            (tuple): meshes, source series, and failures with name, type, and error
    """
    # option to use fp instead of series
    if isinstance(series_like, str):
        ## Null progress and notifier, not the Qt defaults: this function
        ## runs inside the 3D worker thread, and the default reporter builds
        ## a QProgressDialog parented to the main window -- a Qt widget
        ## constructed and driven off the GUI thread, which Qt forbids
        ## (intermittent cross-thread warnings and crashes while
        ## "Generating 3D..." ran; found 2026-08-28). The worker already
        ## shows its own progress bar on the GUI side.
        from PyReconstruct.modules.backend.notifier import NullNotifier
        from PyReconstruct.modules.backend.progress import NullProgressReporter
        series = Series.openJser(
            series_like,
            progress=NullProgressReporter,
            notifier=NullNotifier(),
        )
    else:
        series = series_like

    # check the obj names
    for d in objs.copy():
        if d["name"] not in series.data["objects"]:
            objs.remove(d)
    # check the ztrace names
    for d in ztraces.copy():
        if d["name"] not in series.ztraces:
            ztraces.remove(d)
    
    # create the 3D objects
    obj_data = {}
    for d in objs:
        name = d["name"]
        mode = series.getAttr(name, "3D_mode")
        color = d["color"] if "color" in d else None
        alpha = d["alpha"] if "alpha" in d else None
        tform = d["tform"] if "tform" in d else None
        args = (name, series, color, alpha, tform)
        if mode == "surface":
            obj_data[name] = Surface(*args)
        elif mode == "spheres":
            obj_data[name] = Spheres(*args)
        elif mode == "contours":
            obj_data[name] = Contours(*args)

    # iterate through all sections and gather points (and colors)
    report = progress if progress is not None else (lambda percent: None)
    report(0)
    section_numbers = sorted(series.sections.keys())
    for i, (snum, section) in enumerate(series.enumerateSections(show_progress=False)):
        report(80 * i / max(len(section_numbers), 1))
        for obj_name in obj_data.keys():
            if obj_name in section.contours:
                # get the transform sepcific to the object
                alignment = series.getAttr(obj_name, "alignment")
                if not alignment:
                    tform = section.tform
                else:
                    tform = section.tforms[alignment]
                for trace in section.contours[obj_name]:
                    # collect all points if generating a full surface
                    obj_data[obj_name].addTrace(trace, snum, tform)
    
    # create ztraces
    ztrace_data = {}
    for d in ztraces:
        name = d["name"]
        color = d["color"] if "color" in d else None
        alpha = d["alpha"] if "alpha" in d else None
        tform = d["tform"] if "tform" in d else None
        args = (name, series, color, alpha, tform)
        ztrace_data[name] = Ztrace3D(*args)


    # iterate through all objects and create 3D meshes
    mesh_data_list = []
    failures = []

    n_meshes = max(len(obj_data) + len(ztrace_data), 1)
    done = 0
    for kind, items in (("object", obj_data), ("ztrace", ztrace_data)):
        for name, item in items.items():
            report(80 + 20 * done / n_meshes)
            done += 1
            try:
                mesh = item.generate3D()
                if not len(mesh["vertices"]) or not len(mesh["faces"]):
                    raise ValueError("No mesh faces were generated.")
            except Exception as error:
                failures.append({"name": name, "type": kind, "error": str(error)})
            else:
                mesh_data_list.append(mesh)

    report(100)

    return (
        mesh_data_list,
        series,
        failures,
    )
