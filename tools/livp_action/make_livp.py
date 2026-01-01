# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def run_cmd(cmd: list[str], label: str) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"{label} failed: {err}")


def has_audio(ffprobe_path: str, src: Path) -> bool:
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(src),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return False
    return bool((result.stdout or "").strip())


def build_video(
    ffmpeg_path: str,
    ffprobe_path: str,
    src: Path,
    dst: Path,
    max_duration: float,
    fps: int,
    max_width: int,
    max_height: int,
) -> None:
    vf = (
        f"scale=min({max_width},iw):min({max_height},ih):"
        "force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        f"fps={fps}"
    )
    audio = has_audio(ffprobe_path, src)
    if audio:
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            vf,
            "-t",
            f"{max_duration:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(dst),
        ]
    else:
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            vf,
            "-t",
            f"{max_duration:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(dst),
        ]
    run_cmd(cmd, "ffmpeg video")


def extract_still(ffmpeg_path: str, src: Path, dst: Path, cover_time: float) -> None:
    run_cmd(
        [
            ffmpeg_path,
            "-y",
            "-ss",
            f"{cover_time:.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dst),
        ],
        "ffmpeg still",
    )


def write_metadata(exiftool_path: str, image_path: Path, video_path: Path, content_id: str) -> None:
    run_cmd(
        [
            exiftool_path,
            "-m",
            "-overwrite_original",
            f"-QuickTime:ContentIdentifier={content_id}",
            "-QuickTime:LivePhoto=1",
            "-QuickTime:LivePhotoAuto=1",
            str(video_path),
        ],
        "exiftool video",
    )
    run_cmd(
        [
            exiftool_path,
            "-m",
            "-overwrite_original",
            f"-Apple:ContentIdentifier={content_id}",
            f"-XMP:AssetIdentifier={content_id}",
            str(image_path),
        ],
        "exiftool image",
    )


def pack_livp(photo_path: Path, video_path: Path, out_path: Path, internal_base: str) -> None:
    photo_name = f"{internal_base}.jpeg"
    video_name = f"{internal_base}.mov"
    with zipfile.ZipFile(out_path, "w") as zf:
        for src_path, arcname in (
            (photo_path, photo_name),
            (video_path, video_name),
        ):
            try:
                ts = src_path.stat().st_mtime
                dt = datetime.fromtimestamp(ts)
                date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
            except Exception:
                date_time = (1980, 1, 1, 0, 0, 0)
            info = zipfile.ZipInfo(filename=arcname, date_time=date_time)
            info.compress_type = zipfile.ZIP_STORED
            info.flag_bits = 0
            info.create_system = 0
            info.create_version = 0
            info.extract_version = 20
            info.external_attr = 0
            zf.writestr(info, src_path.read_bytes(), compress_type=zipfile.ZIP_STORED)


def build_livp(
    ffmpeg_path: str,
    ffprobe_path: str,
    exiftool_path: str,
    src: Path,
    out_dir: Path,
    index: int,
    cover_time: float,
    max_duration: float,
    fps: int,
    max_width: int,
    max_height: int,
) -> Path:
    content_id = str(uuid.uuid4()).upper()
    internal_base = f"IMG_{index:04d}.JPG"
    out_name = f"{src.stem}.livp"
    out_path = out_dir / out_name
    if out_path.exists():
        out_path = out_dir / f"{src.stem}_{index:04d}.livp"

    with tempfile.TemporaryDirectory(prefix="livp_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        tmp_mov = tmpdir_path / "livephoto.mov"
        tmp_jpeg = tmpdir_path / "livephoto.jpeg"
        build_video(
            ffmpeg_path,
            ffprobe_path,
            src,
            tmp_mov,
            max_duration,
            fps,
            max_width,
            max_height,
        )
        extract_still(ffmpeg_path, tmp_mov, tmp_jpeg, cover_time)
        write_metadata(exiftool_path, tmp_jpeg, tmp_mov, content_id)
        pack_livp(tmp_jpeg, tmp_mov, out_path, internal_base)

    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LIVP files on macOS.")
    parser.add_argument("--input", required=True, help="Input folder with source videos.")
    parser.add_argument("--output", required=True, help="Output folder for .livp files.")
    parser.add_argument("--cover-time", type=str, default="0.5", help="Cover frame time in seconds.")
    parser.add_argument("--max-duration", type=str, default="2.9", help="Max duration in seconds.")
    parser.add_argument("--fps", type=str, default="30", help="Output FPS.")
    parser.add_argument("--max-width", type=str, default="3840", help="Max width.")
    parser.add_argument("--max-height", type=str, default="2160", help="Max height.")
    args = parser.parse_args()

    def _parse_float(value: str, default: float, label: str) -> float:
        text = "" if value is None else str(value).strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc

    def _parse_int(value: str, default: int, label: str) -> int:
        text = "" if value is None else str(value).strip()
        if not text:
            return default
        try:
            return int(float(text))
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc

    try:
        cover_time = _parse_float(args.cover_time, 0.5, "--cover-time")
        max_duration = _parse_float(args.max_duration, 2.9, "--max-duration")
        fps = _parse_int(args.fps, 30, "--fps")
        max_width = _parse_int(args.max_width, 3840, "--max-width")
        max_height = _parse_int(args.max_height, 2160, "--max-height")
    except ValueError as exc:
        print(f"Argument error: {exc}")
        return 2

    ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg"
    ffprobe_path = shutil.which("ffprobe") or "ffprobe"
    exiftool_path = shutil.which("exiftool") or "exiftool"

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    if not input_dir.exists():
        print(f"Input folder not found: {input_dir}")
        return 1
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = [
        path
        for path in sorted(input_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS
    ]
    if not sources:
        print("No video files found in input folder.")
        return 1

    print(f"Found {len(sources)} video file(s).")
    for idx, src in enumerate(sources, start=1):
        print(f"Processing: {src.name}")
        try:
            out_path = build_livp(
                ffmpeg_path,
                ffprobe_path,
                exiftool_path,
                src,
                output_dir,
                idx,
                cover_time,
                max_duration,
                fps,
                max_width,
                max_height,
            )
            print(f"Output: {out_path.name}")
        except Exception as exc:
            print(f"Failed: {src.name} -> {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
