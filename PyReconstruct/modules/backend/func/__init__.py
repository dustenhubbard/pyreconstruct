from .import_transforms import importTransforms
from .import_swift_transforms import importSwiftTransforms
from .state_manager import SectionStates, SeriesStates
from .utils import (
    make_unique_id, determine_cpus, zarr_worker_count, MAX_ZARR_WORKERS,
    stdout_to_devnull,
)
from .large_datasets import scale_block, scale_array


# The XML converters import the GUI's progress bar, and so Qt. They load on
# first use, so the undo history (state_manager) imports with no Qt.
_XML_NAMES = ("xmlToJSON", "jsonToXML", "xmlExportFiles")


def __getattr__(name):
    if name in _XML_NAMES:
        from . import xml_json_conversions
        return getattr(xml_json_conversions, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
