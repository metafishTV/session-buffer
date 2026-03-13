#!/usr/bin/env python3
"""
Slide extraction from video files.

Extracts unique slides from lecture/presentation videos using frame
comparison with structural similarity (SSIM). Outputs PNG files of
each unique slide to a target directory.

Dependencies:
  - opencv-python-headless (~30MB) — demand-install
  - yt-dlp (already a distill dependency) — for YouTube URLs

Usage:
  python distill_slides.py "<video_path_or_url>" --outdir <figures_dir> [--threshold 0.85]
  python distill_slides.py --probe   # check if opencv is installed

Technique:
  1. If URL: download via yt-dlp to temp file
  2. Sample frames at regular intervals (default: 1 per second)
  3. Convert to grayscale, resize to standard width for comparison
  4. Compare consecutive frames using SSIM
  5. When SSIM drops below threshold, a new slide has appeared
  6. Save the first frame of each new slide as PNG
  7. Output a manifest JSON with slide metadata
"""

import sys
import os
import json
import argparse
import subprocess
import tempfile

COMPARE_WIDTH = 480  # resize to this width for SSIM comparison
DEFAULT_THRESHOLD = 0.85  # SSIM below this = new slide
DEFAULT_SAMPLE_RATE = 1.0  # seconds between frame samples
MIN_SLIDE_DURATION = 2.0  # ignore slides shorter than this (seconds)


def probe():
    """Check if opencv-python-headless is available."""
    try:
        import cv2  # noqa: F401
        from importlib.metadata import version
        ver = version('opencv-python-headless')
        print(f"PROBE: opencv {ver}")
        sys.exit(0)
    except ImportError:
        pass
    try:
        import cv2  # noqa: F401
        from importlib.metadata import version
        ver = version('opencv-python')
        print(f"PROBE: opencv {ver}")
        sys.exit(0)
    except ImportError:
        print("PROBE: no_backend")
        sys.exit(2)


def download_video(url, tmpdir):
    """Download video via yt-dlp, return local path."""
    out_template = os.path.join(tmpdir, "video.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "-o", out_template,
        "--no-warnings",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except FileNotFoundError:
        # Try yt-dlp as standalone command
        cmd[0:2] = ["yt-dlp"]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)

    # Find downloaded file
    for f in os.listdir(tmpdir):
        if f.startswith("video."):
            return os.path.join(tmpdir, f)
    raise FileNotFoundError("yt-dlp produced no output file")


def compute_ssim_gray(img1, img2):
    """Compute SSIM between two grayscale images of same size.

    Simplified SSIM — no scikit-image dependency. Uses the standard
    SSIM formula with 11x11 Gaussian window approximated by cv2.GaussianBlur.
    """
    import cv2
    import numpy as np

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    mu1 = cv2.GaussianBlur(img1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(img2, (11, 11), 1.5)

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(img1 ** 2, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(img2 ** 2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(img1 * img2, (11, 11), 1.5) - mu1_mu2

    numerator = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

    ssim_map = numerator / denominator
    return float(ssim_map.mean())


def extract_slides(video_path, outdir, threshold=DEFAULT_THRESHOLD,
                   sample_rate=DEFAULT_SAMPLE_RATE,
                   min_duration=MIN_SLIDE_DURATION,
                   source_label=None):
    """Extract unique slides from video, return manifest dict."""
    import cv2
    import numpy as np

    os.makedirs(outdir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps > 0 else 0
    frame_interval = max(1, int(fps * sample_rate))

    slides = []
    prev_gray = None
    current_slide_start = 0.0
    slide_frame = None
    frame_idx = 0
    slide_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval != 0:
            frame_idx += 1
            continue

        timestamp = frame_idx / fps
        # Resize for comparison
        h, w = frame.shape[:2]
        scale = COMPARE_WIDTH / w
        small = cv2.resize(frame, (COMPARE_WIDTH, int(h * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        is_new_slide = False
        if prev_gray is None:
            is_new_slide = True
        else:
            ssim = compute_ssim_gray(prev_gray, gray)
            if ssim < threshold:
                is_new_slide = True

        if is_new_slide:
            # Save previous slide if it lasted long enough
            if slide_frame is not None:
                slide_duration = timestamp - current_slide_start
                if slide_duration >= min_duration:
                    slide_count += 1
                    fname = f"slide_{slide_count:03d}_{_ts(current_slide_start)}.png"
                    fpath = os.path.join(outdir, fname)
                    cv2.imwrite(fpath, slide_frame)
                    slides.append({
                        "file": fname,
                        "timestamp": current_slide_start,
                        "duration": round(slide_duration, 1),
                        "slide_number": slide_count,
                    })

            # Start tracking new slide
            current_slide_start = timestamp
            slide_frame = frame.copy()

        prev_gray = gray
        frame_idx += 1

    # Save final slide
    if slide_frame is not None:
        final_duration = duration - current_slide_start if duration > 0 else min_duration
        if final_duration >= min_duration:
            slide_count += 1
            fname = f"slide_{slide_count:03d}_{_ts(current_slide_start)}.png"
            fpath = os.path.join(outdir, fname)
            import cv2 as cv2_write
            cv2_write.imwrite(fpath, slide_frame)
            slides.append({
                "file": fname,
                "timestamp": current_slide_start,
                "duration": round(final_duration, 1),
                "slide_number": slide_count,
            })

    cap.release()

    manifest = {
        "source": source_label or os.path.basename(video_path),
        "video_duration": round(duration, 1),
        "total_frames_sampled": frame_idx // frame_interval if frame_interval > 0 else 0,
        "slides_extracted": len(slides),
        "threshold": threshold,
        "sample_rate": sample_rate,
        "slides": slides,
    }

    # Write manifest
    manifest_path = os.path.join(outdir, "_slide_manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    return manifest


def _ts(seconds):
    """Format seconds as MM-SS for filenames."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}-{s:02d}"


def main():
    parser = argparse.ArgumentParser(description="Extract slides from video")
    parser.add_argument("source", nargs="?", help="Video path or URL")
    parser.add_argument("--outdir", required=False, help="Output directory for slide PNGs")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"SSIM threshold for new slide detection (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--sample-rate", type=float, default=DEFAULT_SAMPLE_RATE,
                        help=f"Seconds between frame samples (default: {DEFAULT_SAMPLE_RATE})")
    parser.add_argument("--label", default=None, help="Source label for manifest")
    parser.add_argument("--probe", action="store_true", help="Check if opencv is installed")

    args = parser.parse_args()

    if args.probe:
        probe()

    if not args.source:
        print("Error: source path or URL required", file=sys.stderr)
        sys.exit(1)

    if not args.outdir:
        print("Error: --outdir required", file=sys.stderr)
        sys.exit(1)

    source = args.source
    is_url = source.startswith("http://") or source.startswith("https://")
    tmpdir = None

    try:
        if is_url:
            tmpdir = tempfile.mkdtemp(prefix="distill_slides_")
            print(f"Downloading video from URL...", file=sys.stderr)
            video_path = download_video(source, tmpdir)
            print(f"Downloaded: {os.path.basename(video_path)}", file=sys.stderr)
        else:
            video_path = os.path.abspath(source)
            if not os.path.exists(video_path):
                print(f"Error: file not found: {video_path}", file=sys.stderr)
                sys.exit(1)

        print(f"Extracting slides (threshold={args.threshold})...", file=sys.stderr)
        manifest = extract_slides(
            video_path, args.outdir,
            threshold=args.threshold,
            sample_rate=args.sample_rate,
            source_label=args.label,
        )

        print(json.dumps(manifest, indent=2))
        print(f"\n{manifest['slides_extracted']} slides extracted to {args.outdir}",
              file=sys.stderr)

    finally:
        # Clean up temp download
        if tmpdir and os.path.exists(tmpdir):
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
