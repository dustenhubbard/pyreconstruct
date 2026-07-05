from .text_widget import TextWidget
from .about import AboutWidget


def __getattr__(name):
    """Lazily expose CustomPlotter.

    Importing custom_plotter pulls in vedo/vtk/matplotlib (~0.5 s of import
    time), and it is only needed when the user opens the 3D viewer. Loading it
    on first attribute access keeps ``import ...gui.popup`` (done at startup for
    TextWidget/AboutWidget) cheap, while ``from ...gui.popup import CustomPlotter``
    still works for callers that want it.
    """
    if name == "CustomPlotter":
        from .custom_plotter import CustomPlotter
        return CustomPlotter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
