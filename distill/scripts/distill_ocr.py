#!/usr/bin/env python3
"""OCR shim for scanned PDFs — tries backends in order of preference.

Usage:
    python distill_ocr.py <pdf_path> --scan _distill_scan.json --output _distill_ocr.pdf [--pages 0,1,5]

Backends (tried in order):
  1. ocrmypdf  — adds invisible text layer to PDF, output is an OCR'd PDF
  2. pytesseract — renders pages via PyMuPDF, OCRs each, writes text file
  3. (none) — exits with code 2, signaling the SKILL to use vision fallback

Output:
  --output path receives either an OCR'd PDF (ocrmypdf) or a UTF-8 text file
  (pytesseract). The script prints which backend was used and the page count.
  Exit code 0 = success, 1 = error, 2 = no backend available.
"""

import argparse
import json
import os
import sys
import tempfile


def detect_backend():
    """Return the best available OCR backend name."""
    try:
        import ocrmypdf
        return "ocrmypdf"
    except ImportError:
        pass
    try:
        import pytesseract
        # Verify tesseract binary is reachable
        pytesseract.get_tesseract_version()
        return "pytesseract"
    except Exception:
        pass
    return None


def ocr_with_ocrmypdf(pdf_path, output_path, pages):
    """Add OCR text layer to scanned PDF. Output is a searchable PDF."""
    import ocrmypdf

    kwargs = {
        "input_file": pdf_path,
        "output_file": output_path,
        "skip_text": True,       # Don't re-OCR pages that already have text
        "optimize": 0,           # No recompression — keep it fast
        "progress_bar": False,
    }
    if pages is not None:
        kwargs["pages"] = ",".join(str(p + 1) for p in pages)  # ocrmypdf uses 1-based

    result = ocrmypdf.ocr(**kwargs)
    return result == ocrmypdf.ExitCode.ok or result == 0


def ocr_with_pytesseract(pdf_path, output_path, pages, scan_data):
    """Render scanned pages as images, OCR with Tesseract, write text file."""
    import pymupdf
    import pytesseract
    from PIL import Image
    import io

    doc = pymupdf.open(pdf_path)
    scanned_pages = pages if pages is not None else scan_data.get("scanned", [])
    text_parts = []

    for i, page_num in enumerate(sorted(scanned_pages)):
        if page_num >= len(doc):
            continue
        page = doc[page_num]
        pix = page.get_pixmap(dpi=300)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        page_text = pytesseract.image_to_string(img)
        text_parts.append(f"{'=' * 60}\nPAGE {page_num + 1} [ocr:pytesseract]\n{'=' * 60}\n{page_text}")
        if (i + 1) % 5 == 0:
            print(f"  OCR progress: {i + 1}/{len(scanned_pages)} pages...")

    doc.close()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(text_parts))

    return True


def main():
    parser = argparse.ArgumentParser(description="OCR shim for scanned PDFs")
    parser.add_argument("pdf_path", help="Path to input PDF")
    parser.add_argument("--scan", required=True, help="Path to scan JSON from distill_scan.py")
    parser.add_argument("--output", required=True, help="Output path (PDF for ocrmypdf, text for pytesseract)")
    parser.add_argument("--pages", default=None, help="Comma-separated 0-based page indices (default: all scanned pages)")
    args = parser.parse_args()

    with open(args.scan, "r", encoding="utf-8") as f:
        scan_data = json.load(f)

    pages = None
    if args.pages:
        pages = [int(p.strip()) for p in args.pages.split(",")]

    backend = detect_backend()

    if backend is None:
        print("NO_BACKEND: Neither ocrmypdf nor pytesseract available.")
        print("Install one of:")
        print("  pip install ocrmypdf    (+ Tesseract binary)")
        print("  pip install pytesseract (+ Tesseract binary)")
        sys.exit(2)

    scanned_count = len(pages) if pages else len(scan_data.get("scanned", []))
    print(f"OCR backend: {backend}")
    print(f"Scanned pages to process: {scanned_count}")

    try:
        if backend == "ocrmypdf":
            success = ocr_with_ocrmypdf(args.pdf_path, args.output, pages)
            if success:
                print(f"OCR complete. Searchable PDF written to {args.output}")
                print("OUTPUT_TYPE: pdf")
            else:
                print("ocrmypdf reported failure.", file=sys.stderr)
                sys.exit(1)

        elif backend == "pytesseract":
            # pytesseract outputs text, not PDF — adjust output extension
            text_output = args.output
            if text_output.endswith(".pdf"):
                text_output = text_output.rsplit(".", 1)[0] + ".txt"
            success = ocr_with_pytesseract(args.pdf_path, text_output, pages, scan_data)
            if success:
                print(f"OCR complete. Text written to {text_output}")
                print("OUTPUT_TYPE: text")
            else:
                print("pytesseract OCR failed.", file=sys.stderr)
                sys.exit(1)

    except Exception as e:
        print(f"OCR error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
