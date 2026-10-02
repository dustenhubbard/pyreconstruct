import os
import re
import json
from xml.sax.saxutils import escape

from PyReconstruct.modules.calc import reducePoints

from PyReconstruct.modules.constants import blank_section, blank_series_no_contours
from PyReconstruct.modules.gui.utils import getProgbar
from PyReconstruct.modules.constants import createNewSeriesDir
from PyReconstruct.modules.datatypes import (
    Series,
    Section,
    Transform,
    Trace,
    Ztrace
)
from PyReconstruct.modules.datatypes_legacy import (
    Transform as XMLTransform,
    process_series_file, 
    process_section_file,
    write_section,
    write_series
)

def xmlToJSON(series_fp : str) -> Series:
    """Convert a series in XML to JSON.
    
        Params:
            series_fp (str): the filepath for the xml series (.ser) file
    """
    # gather the section filepaths for this series only: a folder can hold
    # more than one series, and the hidden folder of an earlier conversion
    # can end in .ser too
    base = os.path.basename(series_fp)
    series_name = base[:-len(".ser")]
    xml_dir = os.path.dirname(series_fp) or "."
    # the hidden folder below has to be a folder inside xml_dir: a folder,
    # ".ser" or "..ser" would make it the xml folder itself or its parent
    real_xml_dir = os.path.realpath(xml_dir)
    real_hidden = os.path.realpath(os.path.join(xml_dir, "." + series_name))
    if (
        not os.path.isfile(series_fp)
        or not base.lower().endswith(".ser")
        or not series_name
        or os.path.dirname(real_hidden) != real_xml_dir
        or real_hidden == real_xml_dir
    ):
        raise ValueError(f"{series_fp} is not a legacy series (.ser) file.")
    section_fps = {}
    json_fp = ""

    print("Gathering files...")
    
    files = [
        f for f in sorted(os.listdir(xml_dir))
        if os.path.isfile(os.path.join(xml_dir, f))
    ]
    # the prefix is matched in any case, as a case-insensitive disk would;
    # if two files differ only in case, the one matching the .ser wins. If
    # another .ser differs from this one only in case (a case-sensitive
    # disk), the sections in the other case are its own, so match exactly.
    prefix = series_name + "."
    other_case_ser = any(
        f != base and f.lower() == base.lower()
        and not os.path.samefile(os.path.join(xml_dir, f), series_fp)
        for f in files
    )
    for f in files:
        fp = os.path.join(xml_dir, f)
        if f.lower().endswith(".json"):
            continue
        if (
            (f.startswith(prefix) if other_case_ser
             else f.lower().startswith(prefix.lower()))
            and re.fullmatch(r"[0-9]+", f[len(prefix):])
        ):
            snum = int(f[len(prefix):])
            if snum not in section_fps or f.startswith(prefix):
                section_fps[snum] = fp
    if not section_fps:
        raise ValueError(
            f"No section files for {base} were found. "
            f"They are named {series_name}.1, {series_name}.2, and so on."
        )

    # the reconcropper alignments: the .json named for this series (in the
    # same case if another .ser differs only in case), or else the only .json
    # in the folder unless it is named for another series there
    def stem(f):
        return f[:f.rfind(".")]
    json_fps = [f for f in files if f.lower().endswith(".json")]
    named = [
        f for f in json_fps
        if stem(f) == series_name
        or (not other_case_ser and stem(f).lower() == series_name.lower())
    ]
    named.sort(key=lambda f: stem(f) != series_name)  # exact case first
    other_series = {
        stem(f).lower() for f in files
        if f.lower().endswith(".ser")
        and not os.path.samefile(os.path.join(xml_dir, f), series_fp)
    }
    json_is_named = bool(named)
    if named:
        json_fp = os.path.join(xml_dir, named[0])
    elif len(json_fps) == 1 and stem(json_fps[0]).lower() not in other_series:
        json_fp = os.path.join(xml_dir, json_fps[0])

    print("Creating hidden folder...")
    
    # create the hidden folder containing the JSON files
    sname = os.path.basename(series_fp)
    sname = sname[:sname.rfind(".")]
    hidden_dir = createNewSeriesDir(xml_dir, sname)

    # set up progress
    progbar = getProgbar(
        "Converting series..."
    )
    progress = 0
    final_value = len(section_fps) + 1
    if json_fp: final_value += 1

    print("Converting series...")
    
    # convert the series file
    json_series_fp = seriesXMLToJSON(
        series_fp, list(section_fps.values()), hidden_dir
    )
    if progbar.wasCanceled(): return
    progress += 1
    progbar.setValue(progress/final_value * 100)

    # get the reconcropper data
    alignment_dict = None
    if json_is_named:
        alignment_dict = getReconcropperData(json_fp)
    elif json_fp:
        # the only .json in the folder may not be a reconcropper file
        try:
            alignment_dict = getReconcropperData(json_fp)
        except Exception as e:
            print(f"Skipping {json_fp}: not reconcropper data ({e!r})")
    if progbar.wasCanceled(): return
    progress += 1
    progbar.setValue(progress/final_value * 100)

    # convert the section files and gather section names and tforms
    print("Converting section files...")

    sections = {}
    section_tforms = {}

    for snum, section_fp in sorted(section_fps.items()):
        
        sections[snum] = f"{sname}.{snum}"
        tform = sectionXMLtoJSON(
            section_fp, alignment_dict, hidden_dir, sections[snum]
        )

        section_tforms[snum] = tform

        if progbar.wasCanceled(): return
        progress += 1
        progbar.setValue(progress/final_value * 100)
    
    # create an empty log file
    with open(os.path.join(hidden_dir, "existing_log.csv"), "w", encoding="utf-8") as f:
        f.write("Date, Time, User, Obj, Sections, Event")
    
    # open the series file, modify current section and ztraces
    series = Series(json_series_fp, sections)
    series.current_section = min(series.sections.keys())

    # modify the ztraces
    for ztrace in series.ztraces.values():
        new_points = []
        for point in ztrace.points:
            x, y, snum = point
            if snum in section_tforms:
                new_point = (
                    *section_tforms[snum].map(x, y, inverted=True),
                    snum
                )
                new_points.append(new_point)
        ztrace.points = new_points
    
    # log create the first log in the series
    series.addLog(None, None, "Create series from XML files")

    return series


def seriesXMLToJSON(series_fp, section_fps, hidden_dir):
    # grab the series file
    print("Processing series file...")
    xml_series = process_series_file(series_fp)
    # create an empty JSON series
    series_dict = Series.getEmptyDict()

    # get the current section
    ## TODO: Set to first available section
    series_dict["current_section"] = xml_series.index

    # get the view window
    series_dict["window"] = list(xml_series.viewport[:2]) + [1, 1]
    
    # import the palette
    series_dict["palette_traces"] = []
    for xml_contour in xml_series.contours:
        trace = Trace.fromXMLObj(
            xml_contour,
        )
        series_dict["palette_traces"].append(trace.getList())
    if not series_dict["palette_traces"]:  # legacy series with no palette contours
        series_dict["palette_traces"] = [
            t.getList() for t in Series.getDefaultPaletteTraces()
        ]
    series_dict["current_trace"] = series_dict["palette_traces"][0]
    
    # import ztraces
    series_dict["ztraces"] = {}
    for xml_zcontour in xml_series.zcontours:
        series_dict["ztraces"][xml_zcontour.name] = Ztrace.dictFromXMLObj(xml_zcontour)

    # get the series filename and save
    # always a lowercase .ser, the name crash recovery looks for
    fname = os.path.basename(series_fp)
    fname = fname[:fname.rfind(".")] + ".ser"
    json_series_fp = os.path.join(hidden_dir, fname)
    with open(json_series_fp, "w") as f:
        json.dump(series_dict, f)
    return json_series_fp


def getReconcropperData(json_fp):
    with open(json_fp, "r") as f:
        json_data = json.load(f)
    
    alignment_dict = {}

    for item in json_data:
        if item.startswith("LOCAL") or item.startswith("ALIGNMENT"):
            for section_name in json_data[item]:
                # get the transform data
                xcoef = json_data[item][section_name]["xcoef"]
                ycoef = json_data[item][section_name]["ycoef"]
                leg_tform = XMLTransform(xcoef=xcoef, ycoef=ycoef)
                tform_list = leg_tform.getTformList()

                # store the transform data
                aname = item
                if section_name not in alignment_dict:
                    alignment_dict[section_name] = {}
                alignment_dict[section_name][aname] = tform_list
                
    return alignment_dict


def sectionXMLtoJSON(section_fp, alignment_dict, hidden_dir, out_name=None):

    # # grab the section file
    # try:
        
    xml_section = process_section_file(section_fp)
    fname = os.path.basename(section_fp)

    # except Exception as e:

    #     notify(f"A problem has been encountered while importing:\n\n{section_fp}\n\nError:\n\n{e}")

    # get an empty section dict
    section_dict = Section.getEmptyDict()

    # get image data
    if xml_section.images:
        image = xml_section.images[0] # assume only one image
    else:
        image = None

    if image:

        section_dict["src"] = image.src
        section_dict["mag"] = image.mag
        xml_tform = image.transform
        tform = Transform(
            list(xml_tform.tform()[:2,:].reshape(6))
        )
        
    else:

        print(f"Section: {fname} does not contain any image data.")
        section_dict["src"] = ""
        section_dict["mag"] = 0.00254
        xml_tform = None
        tform = Transform.identity()

    # get thickness
    section_dict["thickness"] = xml_section.thickness

    # get transform data
    section_dict["tforms"] = {}
    if alignment_dict and fname in alignment_dict:
        section_dict["tforms"] = alignment_dict[fname]
    else:
        section_dict["tforms"] = {}
    
    section_dict["tforms"]["default"] = tform.getList()
    section_dict["align_locked"] = xml_section.alignLocked

    # get trace/contour data
    contours = section_dict["contours"]  # for ease of access
    for xml_contour in xml_section.contours:
        trace = Trace.fromXMLObj(
            xml_contour,
            xml_tform,
        )
        if len(trace.points) > 1:
            # reduce the points on the trace
            trace.points = reducePoints(
                trace.points,
                closed=trace.closed,
                mag=2/section_dict["mag"]
            )
            if trace.name in contours:
                contours[trace.name].append(trace.getList(include_name=False))
            else:
                contours[trace.name] = [trace.getList(include_name=False)]
    
    # save the section
    with open(os.path.join(hidden_dir, out_name or fname), "w") as f:
        json.dump(section_dict, f)
    
    # return the section's transform
    return tform


def jsonToXML(series : Series, new_dir : str, name : str = None):
    """Convert a json series to xml for use in legacy Reconstruct
    
        Params:
            original_series (Series): series to convert
            new_dir (str): directory to store the new files
            name (str): file name stem for the .ser and section files
                (defaults to the series name)
    """
    if not name:
        name = series.name

    ## Convert sections
    for snum, section in series.enumerateSections(message="Exporting series as XML..."):
        thickness = sectionJSONtoXML(series, section, new_dir, name)

    final_sec = str(snum)

    ## Convert series
    seriesJSONtoXML(series, new_dir, thickness, final_sec, name)
    

def xmlExportFiles(series : Series, new_dir : str, name : str = None):
    """Return the paths jsonToXML would write, and other section files there.

        Params:
            series (Series): series to convert
            new_dir (str): directory the files would go to
            name (str): file name stem (defaults to the series name)
        Returns:
            (list, list): existing files the export would replace, and
                existing <name>.<number> files the export would not write,
                which legacy Reconstruct would still read as sections
    """
    if not name:
        name = series.name
    new_dir = new_dir or "."

    targets = [f"{name}.ser"] + [f"{name}.{n}" for n in sorted(series.sections)]
    replaced = [t for t in targets if os.path.exists(os.path.join(new_dir, t))]

    by_lower = {t.lower(): t for t in targets}
    section_file = re.compile(re.escape(name) + r"\.\d+", re.IGNORECASE)
    try:
        listing = sorted(os.listdir(new_dir))
    except OSError:
        listing = []

    def is_target(f):
        """True if f is a file the export writes (by any case on this disk)."""
        if f in targets:
            return True
        t = by_lower.get(f.lower())
        if not t or t not in replaced:
            return False
        try:
            return os.path.samefile(os.path.join(new_dir, f), os.path.join(new_dir, t))
        except OSError:
            return False

    extra = [f for f in listing if section_file.fullmatch(f) and not is_target(f)]

    return replaced, extra


def seriesJSONtoXML(series : Series, new_dir : str, thickness: str, last_section: str, name : str = None):
    
    ## Create blank series and replace text as needed
    xml_text = blank_series_no_contours
                        
    xml_text = xml_text.replace("[SECTION_NUM]", str(series.current_section))
    xml_text = xml_text.replace("[SECTION_THICKNESS]", thickness)
    xml_text = xml_text.replace("[LAST3DSECTION]", last_section)
    xml_text = xml_text.replace("[LASTTHUMBSECTION]", last_section)

    xml_palette = []

    for trace in series.palette_traces[series.palette_index[0]]:
        xml_palette.append(trace.getXMLObj(legacy_format=True))
        
    all_contours = '\n'.join(xml_palette)

    xml_text = xml_text.replace("[CONTOURS]", all_contours)

    ## Create series file
    series_fp = os.path.join(new_dir, (name or series.name) + ".ser")
    with open(series_fp, "w") as f:
        f.write(xml_text)
    
    ## Load series file and insert ztraces
    xml_series = process_series_file(series_fp)
    for ztrace in series.ztraces.values():
        xml_series.zcontours.append(ztrace.getXMLObj(series))
    
    ## Set section thickness, written in full like the section files
    xml_series.defaultThickness = float(series.avg_thickness)
    
    write_series(
        xml_series,
        directory=os.path.dirname(series_fp),
        outpath=series_fp,
        overwrite=True
    )
        

def sectionJSONtoXML(series : Series, section : Section, new_dir : str, name : str = None):

    sec_index      = str(section.n)
    # both written in full: rounding to 4 places made a 0.00254 mag into
    # 0.0025, which scales the image 1.6% off its traces, and a 0.04787
    # thickness into 0.0479
    sec_thickness  = str(float(section.thickness))
    sec_mag        = str(float(section.mag))
    sec_src        = section.src
    sec_locked     = section.align_locked
    
    ## create blank xml section
    xml_text = blank_section

    xml_text = xml_text.replace("[SECTION_INDEX]", sec_index)
    xml_text = xml_text.replace("[SECTION_THICKNESS]", sec_thickness)
    xml_text = xml_text.replace("[TRANSFORM_DIM]", "3")  # always affine
    xml_text = xml_text.replace("[XCOEF]", "0 1 0 0 0 0")  # to be replaced
    xml_text = xml_text.replace("[YCOEF]", "0 0 1 0 0 0")  # to be replaced
    xml_text = xml_text.replace("[IMAGE_MAG]", sec_mag)
    # escaped because the text is parsed as XML below; the parsed image
    # then gets the plain sec_src, which the writer escapes itself
    xml_text = xml_text.replace("[IMAGE_SOURCE]", escape(sec_src, {'"': "&quot;"}))
    xml_text = xml_text.replace("[IMAGE_LENGTH]", "100000")
    xml_text = xml_text.replace("[IMAGE_HEIGHT]", "100000")

    ## Save file
    section_fp = os.path.join(
        new_dir,
        f"{name or series.name}.{sec_index}"
    )

    with open(section_fp, "w") as xml_file:
        xml_file.write(xml_text)
    
    ## Load xml section and input data
    xml_section = process_section_file(section_fp)
    
    xml_section.images[0].src = sec_src
    xml_section.images[0].mag = sec_mag
    xml_section.alignLocked = sec_locked
    xml_section.thickness = sec_thickness

    t = section.tform.getList()

    xcoef = [t[2], t[0], t[1]]
    ycoef = [t[5], t[3], t[4]]

    xml_tform = XMLTransform(xcoef=xcoef, ycoef=ycoef).inverse
    xml_section.images[0].transform = xml_tform

    xml_section.contours = []

    for trace in section.tracesAsList():
        xml_section.contours.append(trace.getXMLObj(xml_tform))

    write_section(
        xml_section,
        directory=os.path.dirname(section_fp),
        outpath=section_fp,
        overwrite=True
    )

    return sec_thickness  # to pass to seriesJSONToXML

