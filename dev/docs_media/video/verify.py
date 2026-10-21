#!/usr/bin/env python3
"""Decode rendered MP4s, measure them, and make one-frame-per-second sheets."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def measure(path, ffprobe="ffprobe"):
    command = [ffprobe, "-v", "error", "-count_frames", "-show_streams",
               "-show_format", "-of", "json", str(path)]
    result = json.loads(subprocess.check_output(command))
    videos = [s for s in result["streams"] if s["codec_type"] == "video"]
    if len(videos) != 1:
        raise ValueError(f"{path}: expected one video stream")
    video = videos[0]
    return {"width": video["width"], "height": video["height"],
            "fps": video["avg_frame_rate"], "duration": float(video["duration"]),
            "frames": int(video["nb_read_frames"]), "codec": video["codec_name"],
            "pixel_format": video["pix_fmt"],
            "audio_streams": sum(s["codec_type"] == "audio" for s in result["streams"]),
            "bytes": Path(path).stat().st_size, "sha256": sha256(path),
            "probe_command": command}


def contact_sheet(path, info, ffmpeg="ffmpeg"):
    if info["fps"] != "60/1":
        raise ValueError("contact sheets require the renderer's 60 fps output")
    width = 512
    height = round(width * info["height"] / info["width"])
    command = [ffmpeg, "-v", "error", "-nostdin", "-i", str(path),
               "-vf", f"select=not(mod(n\\,60)),scale={width}:{height}:flags=lanczos",
               "-fps_mode", "vfr", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    raw = subprocess.check_output(command)
    frame_bytes = width * height * 3
    count = math.ceil(info["frames"] / 60)
    if len(raw) != count * frame_bytes:
        raise ValueError(f"{path}: incomplete contact sheet decode")
    sheet = Image.new("RGB", (width * 3, (height + 24) * math.ceil(count / 3)), "#f5f4ef")
    draw = ImageDraw.Draw(sheet)
    for index in range(count):
        frame = Image.frombytes("RGB", (width, height),
                                raw[index * frame_bytes:(index + 1) * frame_bytes])
        x, y = (index % 3) * width, (index // 3) * (height + 24)
        sheet.paste(frame, (x, y + 24))
        draw.text((x + 8, y + 5), f"{index} seconds", fill="#222222")
    return sheet, command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-sheet", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"videos": {}, "contact_sheet_sampling": "Decoded frames 0, 60, 120, ... at 60 fps"}
    first_sheet = None
    for path in args.videos:
        info = measure(path, args.ffprobe)
        sheet, command = contact_sheet(path, info, args.ffmpeg)
        sheet_path = args.output_dir / f"{path.stem}-contact-sheet.jpg"
        sheet.save(sheet_path, quality=95)
        info["contact_sheet"] = str(sheet_path.resolve())
        info["contact_sheet_command"] = command
        report["videos"][str(path.resolve())] = info
        if first_sheet is None:
            first_sheet = sheet
    if args.reference_sheet:
        with Image.open(args.reference_sheet) as reference:
            reference = reference.convert("RGB")
        panel_width = first_sheet.width
        reference = reference.resize((panel_width, round(reference.height * panel_width / reference.width)),
                                     Image.Resampling.LANCZOS)
        comparison = Image.new("RGB", (panel_width * 2, max(reference.height, first_sheet.height) + 32), "white")
        comparison.paste(reference, (0, 32))
        comparison.paste(first_sheet, (panel_width, 32))
        draw = ImageDraw.Draw(comparison)
        draw.text((12, 10), "Old contact sheet (original sampling)", fill="black")
        draw.text((panel_width + 12, 10), "Rebuilt renderer (exact integer seconds)", fill="black")
        comparison.save(args.output_dir / "comparison.jpg", quality=95)
        report["reference_sheet"] = {"path": str(args.reference_sheet.resolve()),
                                     "sha256": sha256(args.reference_sheet)}
    (args.output_dir / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
