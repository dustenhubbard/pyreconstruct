"""Create neuroglancer-formatted zarrs from PyReconstruct jser files."""

import os
import argparse
import tomllib

def get_args ():
    """Get args for conversion."""

    parser = argparse.ArgumentParser(
        prog="ng-create-zarr",
        description=__doc__,
        epilog="example call: ng-create-zarr my_series.jser --groups dendrites spines",
    )

    ## Poitional args
    parser.add_argument("jser", type=str, nargs="?", help="Filepath of a valid jser file.")

    ## Optional args

    parser.add_argument(
        "--config",
        "-c",
        type=str,
        help="filepath to a toml config file"
    )

    parser.add_argument(
        "--start_section",
        "-s",
        type=int,
        default=None,
        help="the first section to include (default to second section in series to avoid calgrid)",
    )

    parser.add_argument(
        "--end_section",
        "-e",
        type=int,
        default=None,
        help="the last section to include (default last section in series)",
    )

    parser.add_argument(
        "--mag",
        "-m",
        type=float,
        default=None,
        help="output zarr lateral resolution in μm (default: the first section's image)",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional output path",
    )

    parser.add_argument(
        "--padding",
        "-p",
        type=int,
        default=50,
        help="padding (px) to include around group objects (default %(default)s px)",
    )

    parser.add_argument(
        "--groups",
        "-g",
        type=str,
        action="append",
        nargs="*",
        default=None,
        help="Object groups to include as labels (default %(default)s μm/vox)",
    )

    parser.add_argument(
        "--max_tissue",
        action="store_true",
        help="Inclue all possible tissue and black space",
    )

    parser.add_argument(
        "--labels_only",
        action="store_true",
        help="Export only labels",
    )

    args = parser.parse_args()

    ## Optional toml config file
    if args.config:
    
        with open(args.config, "rb") as fp:
            
            try:
                parser.set_defaults(**tomllib.load(fp))
            
            except tomllib.TOMLDecodeError:
                parser.error("Malformed toml config file.")
            
        if args.groups:
            parser.set_defaults(
                groups=None
            )  # override toml acting as defaults if --groups called
        
        args = parser.parse_args()

    if not args.jser or not os.path.exists(args.jser):
        parser.error("Please provide filepath to a valid jser.")

    if args.mag is not None and not float(args.mag) > 0:
        parser.error("--mag must be greater than 0.")

    return args


def parse_args(args):

    jser_fp = args.jser
    output_zarr = args.output
    start = args.start_section
    end = args.end_section
    mag = None if args.mag is None else float(args.mag)
    padding = int(args.padding)
    max_tissue = bool(args.max_tissue)
    labels_only = bool(args.labels_only)

    if start: start = int(start)
    if end: end = int(end)

    return jser_fp, output_zarr, start, end, mag, padding, max_tissue, labels_only
