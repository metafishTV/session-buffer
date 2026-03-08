#!/usr/bin/env python3
"""distill_transcribe.py — Extract transcripts from audio/video sources.

Supports:
  - YouTube URLs (captions via yt-dlp, fallback to audio download + whisper)
  - Local audio/video files (transcription via faster-whisper)

Output: Timestamped transcript written to file (UTF-8, never stdout).

Usage:
    python distill_transcribe.py "<source>" --output transcript.txt [--model base]

    <source>: YouTube URL or local file path
    --output: Output file path (required)
    --model: Whisper model size (tiny/base/small/medium/large) default: base
    --language: Language code (e.g., en, fr) — auto-detected if omitted
    --metadata-only: Extract metadata only (YouTube), write JSON, no transcript

Dependencies:
    Required:  yt-dlp (pip install yt-dlp) — for YouTube sources
    Optional:  faster-whisper (pip install faster-whisper) — for transcription
               when captions are unavailable or for local audio/video files.
               Downloads ~150MB model on first use (base model). Runs on CPU.
"""

import sys
import os
import re
import json
import subprocess
import tempfile
import argparse
from pathlib import Path


def is_youtube_url(source: str) -> bool:
    """Check if source is a YouTube URL (or other yt-dlp-supported platform)."""
    youtube_patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=',
        r'(https?://)?(www\.)?youtu\.be/',
        r'(https?://)?(www\.)?youtube\.com/embed/',
        r'(https?://)?(www\.)?youtube\.com/shorts/',
        r'(https?://)?(www\.)?youtube\.com/live/',
    ]
    return any(re.match(p, source) for p in youtube_patterns)


def is_url(source: str) -> bool:
    """Check if source is any URL (for yt-dlp-supported platforms beyond YouTube)."""
    return source.startswith(('http://', 'https://'))


def format_timestamp(seconds: float) -> str:
    """Convert seconds to [HH:MM:SS] or [MM:SS] format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"[{hours}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes}:{secs:02d}]"


def extract_metadata(url: str) -> dict:
    """Extract metadata from a video URL using yt-dlp."""
    try:
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--no-download', url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            upload_date = data.get('upload_date', '')
            if upload_date and len(upload_date) == 8:
                formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
            else:
                formatted_date = upload_date

            duration = data.get('duration', 0)
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            secs = int(duration % 60)
            if hours > 0:
                duration_str = f"{hours}:{minutes:02d}:{secs:02d}"
            else:
                duration_str = f"{minutes}:{secs:02d}"

            return {
                'title': data.get('title', 'Unknown'),
                'uploader': data.get('uploader', data.get('channel', 'Unknown')),
                'upload_date': formatted_date,
                'duration': duration,
                'duration_formatted': duration_str,
                'description': (data.get('description', '') or '')[:500],
                'url': url,
                'platform': data.get('extractor', 'unknown'),
                'language': data.get('language', None),
            }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: metadata extraction failed: {e}", file=sys.stderr)

    return {
        'title': 'Unknown', 'uploader': 'Unknown', 'url': url,
        'upload_date': '', 'duration': 0, 'duration_formatted': '0:00',
    }


def extract_captions(url: str, language: str = None) -> str | None:
    """Try to extract captions from a video URL via yt-dlp.

    Attempts auto-generated subtitles first (more common on YouTube),
    then manually uploaded subtitles.
    """
    sub_langs = language if language else 'en'

    with tempfile.TemporaryDirectory() as tmpdir:
        sub_file = os.path.join(tmpdir, 'subs')

        # Try auto-generated subtitles first, then manual
        for sub_flag in ['--write-auto-subs', '--write-subs']:
            try:
                subprocess.run(
                    ['yt-dlp', sub_flag, '--sub-langs', sub_langs,
                     '--sub-format', 'vtt', '--skip-download',
                     '-o', sub_file, url],
                    capture_output=True, text=True, timeout=60,
                    cwd=tmpdir
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

            # Look for any downloaded subtitle file
            for f in Path(tmpdir).glob('*.vtt'):
                content = f.read_text(encoding='utf-8', errors='replace')
                parsed = parse_vtt(content)
                if parsed and len(parsed.strip()) > 50:
                    return parsed

    return None


def parse_vtt(vtt_content: str) -> str:
    """Parse WebVTT content into timestamped transcript.

    Deduplicates repeated caption segments (common in YouTube auto-captions
    which use rolling/overlapping display).
    """
    lines = []
    current_time = None
    current_text = []
    seen_texts = set()

    for line in vtt_content.split('\n'):
        line = line.strip()

        # Skip VTT headers
        if line.startswith('WEBVTT') or line.startswith('Kind:') or \
           line.startswith('Language:') or line.startswith('NOTE'):
            continue

        # Empty line = end of cue
        if not line:
            if current_time and current_text:
                text = ' '.join(current_text).strip()
                text = re.sub(r'<[^>]+>', '', text)  # Strip HTML tags
                if text and text not in seen_texts:
                    lines.append(f"{current_time} {text}")
                    seen_texts.add(text)
                current_text = []
            continue

        # Timestamp line: 00:00:01.234 --> 00:00:05.678
        time_match = re.match(
            r'(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*', line
        )
        if time_match:
            # Flush previous cue
            if current_time and current_text:
                text = ' '.join(current_text).strip()
                text = re.sub(r'<[^>]+>', '', text)
                if text and text not in seen_texts:
                    lines.append(f"{current_time} {text}")
                    seen_texts.add(text)
                current_text = []

            # Parse start timestamp
            start = line.split('-->')[0].strip()
            parts = start.replace('.', ':').split(':')
            if len(parts) >= 4:  # HH:MM:SS.mmm
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) >= 3:  # MM:SS.mmm
                seconds = int(parts[0]) * 60 + int(parts[1])
            else:
                seconds = 0
            current_time = format_timestamp(seconds)
            continue

        # Sequence number (skip)
        if line.isdigit():
            continue

        # Caption text
        if line:
            current_text.append(line)

    # Flush last cue
    if current_time and current_text:
        text = ' '.join(current_text).strip()
        text = re.sub(r'<[^>]+>', '', text)
        if text and text not in seen_texts:
            lines.append(f"{current_time} {text}")

    return '\n'.join(lines)


def download_audio(url: str, output_dir: str) -> str | None:
    """Download audio from a video URL using yt-dlp."""
    output_template = os.path.join(output_dir, 'audio.%(ext)s')
    try:
        result = subprocess.run(
            ['yt-dlp', '-x', '--audio-format', 'mp3', '--audio-quality', '5',
             '-o', output_template, url],
            capture_output=True, text=True, timeout=600
        )

        if result.returncode == 0:
            for f in Path(output_dir).glob('audio.*'):
                return str(f)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"Warning: audio download failed: {e}", file=sys.stderr)

    return None


def transcribe_with_whisper(audio_path: str, model_size: str = 'base',
                            language: str = None) -> str:
    """Transcribe audio file using faster-whisper.

    Auto-downloads the model on first use (~150MB for base).
    Runs entirely on CPU with int8 quantization for efficiency.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: faster-whisper is not installed.", file=sys.stderr)
        print("Install with: pip install faster-whisper", file=sys.stderr)
        sys.exit(1)

    print(f"Loading Whisper model ({model_size})...", file=sys.stderr)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print(f"Transcribing {os.path.basename(audio_path)}...", file=sys.stderr)
    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        vad_filter=True,  # Voice activity detection — skips silence
    )

    if not language and info.language:
        print(f"Detected language: {info.language} "
              f"({info.language_probability:.1%})", file=sys.stderr)

    lines = []
    for segment in segments:
        timestamp = format_timestamp(segment.start)
        text = segment.text.strip()
        if text:
            lines.append(f"{timestamp} {text}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Extract transcripts from audio/video sources for distillation'
    )
    parser.add_argument('source',
                        help='YouTube URL or local audio/video file path')
    parser.add_argument('--output', required=True,
                        help='Output file path')
    parser.add_argument('--model', default='base',
                        choices=['tiny', 'base', 'small', 'medium', 'large'],
                        help='Whisper model size (default: base)')
    parser.add_argument('--language', default=None,
                        help='Language code, e.g. en, fr (auto-detect if omitted)')
    parser.add_argument('--metadata-only', action='store_true',
                        help='Extract metadata only (YouTube), write JSON')
    args = parser.parse_args()

    source = args.source
    metadata = {}
    transcript = None

    # --- YouTube / URL sources ---
    if is_url(source):
        print("Extracting metadata...", file=sys.stderr)
        metadata = extract_metadata(source)
        print(f"  Title:    {metadata.get('title', 'Unknown')}", file=sys.stderr)
        print(f"  Uploader: {metadata.get('uploader', 'Unknown')}", file=sys.stderr)
        print(f"  Duration: {metadata.get('duration_formatted', '?')}",
              file=sys.stderr)

        if args.metadata_only:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"Metadata written to {args.output}", file=sys.stderr)
            return

        # Try captions first (fast, no transcription needed)
        print("Attempting caption extraction...", file=sys.stderr)
        transcript = extract_captions(source, args.language)

        if transcript:
            seg_count = len(transcript.splitlines())
            print(f"Captions extracted ({seg_count} segments)", file=sys.stderr)
            metadata['extraction_method'] = 'captions'
        else:
            print("No captions available. Downloading audio for transcription...",
                  file=sys.stderr)
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = download_audio(source, tmpdir)
                if audio_path:
                    transcript = transcribe_with_whisper(
                        audio_path, args.model, args.language
                    )
                    metadata['extraction_method'] = 'audio_transcription'
                else:
                    print("ERROR: Failed to download audio.", file=sys.stderr)
                    print("The video may be unavailable, private, or "
                          "region-restricted.", file=sys.stderr)
                    sys.exit(1)

    # --- Local file sources ---
    else:
        if not os.path.exists(source):
            print(f"ERROR: File not found: {source}", file=sys.stderr)
            sys.exit(1)

        print(f"Local file: {os.path.basename(source)}", file=sys.stderr)
        metadata = {
            'title': Path(source).stem,
            'source_file': source,
        }

        if args.metadata_only:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"Metadata written to {args.output}", file=sys.stderr)
            return

        transcript = transcribe_with_whisper(source, args.model, args.language)
        metadata['extraction_method'] = 'local_transcription'

    # --- Write output ---
    if transcript:
        header_lines = []
        if metadata.get('url'):
            header_lines.append(f"# Transcript: {metadata.get('title', 'Unknown')}")
            header_lines.append(f"# Source: {metadata.get('url')}")
            header_lines.append(f"# Uploader: {metadata.get('uploader', 'Unknown')}")
            if metadata.get('upload_date'):
                header_lines.append(f"# Date: {metadata['upload_date']}")
            header_lines.append(
                f"# Duration: {metadata.get('duration_formatted', 'unknown')}"
            )
            header_lines.append(
                f"# Extraction: {metadata.get('extraction_method', 'unknown')}"
            )
        else:
            header_lines.append(
                f"# Transcript: {os.path.basename(source)}"
            )
            header_lines.append(f"# Source: {source}")
            header_lines.append(
                f"# Extraction: {metadata.get('extraction_method', 'unknown')}"
            )

        header_lines.append("")  # Blank line before transcript body

        with open(args.output, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header_lines) + transcript)

        seg_count = len(transcript.splitlines())
        print(f"Transcript written to {args.output} ({seg_count} segments)",
              file=sys.stderr)
    else:
        print("ERROR: No transcript produced.", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
