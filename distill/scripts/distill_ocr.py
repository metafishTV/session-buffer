#!/usr/bin/env python3
"""OCR shim for scanned PDFs -- tries backends in order of preference.

Usage:
    python distill_ocr.py <pdf_path> --scan _distill_scan.json --output _distill_ocr.pdf [--pages 0,1,5]

Backends (tried in order):
  1. rapidocr     -- pure pip, no system binary needed (~80-100MB with onnxruntime)
  2. ocrmypdf     -- adds invisible text layer to PDF (requires Tesseract binary)
  3. pytesseract  -- renders pages via PyMuPDF, OCRs each (requires Tesseract binary)
  4. (none)       -- exits with code 2, signaling the SKILL to use vision fallback

Output:
  --output path receives either an OCR'd PDF (ocrmypdf) or a UTF-8 text file
  (all others). The script prints which backend was used and the page count.
  Exit code 0 = success, 1 = error, 2 = no backend available.
"""

import argparse
import json
import sys


def probe():
    """Quick probe: detect backend + version, print result, exit.

    Used by the Tool Manifest (Phase 1.7) for silent OCR backend detection.
    Cached in the project tooling profile so subsequent distillations skip this.
    """
    backend = detect_backend()
    if backend is None:
        print("PROBE: no_backend")
        sys.exit(2)
    version = "unknown"
    try:
        if backend == "rapidocr":
            import rapidocr
            version = getattr(rapidocr, '__version__', version)
        elif backend == "rapidocr_onnxruntime":
            import rapidocr_onnxruntime
            version = getattr(rapidocr_onnxruntime, '__version__', version)
        elif backend == "ocrmypdf":
            import ocrmypdf
            version = getattr(ocrmypdf, '__version__', version)
        elif backend == "pytesseract":
            import pytesseract
            version = str(pytesseract.get_tesseract_version())
    except Exception:
        pass
    print(f"PROBE: {backend} {version}")
    sys.exit(0)


def detect_backend():
    """Return the best available OCR backend name."""
    # 1. RapidOCR (new package name, v3+)
    try:
        from rapidocr import RapidOCR
        return "rapidocr"
    except ImportError:
        pass
    # 2. RapidOCR (old package name)
    try:
        from rapidocr_onnxruntime import RapidOCR
        return "rapidocr_onnxruntime"
    except ImportError:
        pass
    # 3. OCRmyPDF (requires Tesseract binary)
    try:
        import ocrmypdf
        return "ocrmypdf"
    except ImportError:
        pass
    # 4. pytesseract (requires Tesseract binary)
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return "pytesseract"
    except Exception:
        pass
    return None


def ocr_with_rapidocr(pdf_path, output_path, pages, scan_data, backend_pkg):
    """Render scanned pages as images, OCR with RapidOCR, write text file."""
    import pymupdf

    # Import from whichever package is available
    if backend_pkg == "rapidocr":
        from rapidocr import RapidOCR
    else:
        from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    doc = pymupdf.open(pdf_path)
    scanned_pages = pages if pages is not None else scan_data.get("scanned", [])
    text_parts = []

    for i, page_num in enumerate(sorted(scanned_pages)):
        if page_num >= len(doc):
            continue
        page = doc[page_num]
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")

        # RapidOCR accepts file path, bytes, or numpy array
        result = engine(img_bytes)

        # Extract text from result
        page_lines = []
        if backend_pkg == "rapidocr":
            # v3+ API: result is an object, iterate for text
            try:
                # Try v3 API: result has .txts or iterate directly
                if hasattr(result, 'txts') and result.txts:
                    page_lines = list(result.txts)
                elif result is not None:
                    # Fallback: iterate result items
                    for item in result:
                        if hasattr(item, 'text'):
                            page_lines.append(item.text)
                        elif isinstance(item, (list, tuple)) and len(item) >= 2:
                            page_lines.append(str(item[1]))
            except (TypeError, AttributeError):
                page_lines = [str(result)]
        else:
            # Old API: engine() returns (result_list, elapse)
            # result_list items are [bbox, text, confidence]
            if result and isinstance(result, tuple):
                result_list = result[0]
                if result_list:
                    for item in result_list:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            page_lines.append(str(item[1]))

        page_text = "\n".join(page_lines) if page_lines else "[no text detected]"
        text_parts.append(
            f"{'=' * 60}\nPAGE {page_num + 1} [ocr:rapidocr]\n{'=' * 60}\n{page_text}"
        )
        if (i + 1) % 5 == 0:
            print(f"  OCR progress: {i + 1}/{len(scanned_pages)} pages...")

    doc.close()

    # Ensure output is .txt not .pdf
    if output_path.endswith(".pdf"):
        output_path = output_path.rsplit(".", 1)[0] + ".txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(text_parts))

    return True, output_path


def ocr_with_ocrmypdf(pdf_path, output_path, pages):
    """Add OCR text layer to scanned PDF. Output is a searchable PDF."""
    import ocrmypdf

    kwargs = {
        "input_file": pdf_path,
        "output_file": output_path,
        "skip_text": True,       # Don't re-OCR pages that already have text
        "optimize": 0,           # No recompression -- keep it fast
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

    # Ensure output is .txt not .pdf
    if output_path.endswith(".pdf"):
        output_path = output_path.rsplit(".", 1)[0] + ".txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(text_parts))

    return True, output_path


def main():
    parser = argparse.ArgumentParser(description="OCR shim for scanned PDFs")
    parser.add_argument("pdf_path", help="Path to input PDF")
    parser.add_argument("--scan", required=True, help="Path to scan JSON from distill_scan.py")
    parser.add_argument("--output", required=True, help="Output path (PDF for ocrmypdf, text for others)")
    parser.add_argument("--pages", default=None, help="Comma-separated 0-based page indices (default: all scanned pages)")
    parser.add_argument("--probe", action="store_true", help="Quick probe: detect backend + version and exit")
    args = parser.parse_args()

    if args.probe:
        probe()
        # probe() calls sys.exit() — never reaches here

    with open(args.scan, "r", encoding="utf-8") as f:
        scan_data = json.load(f)

    pages = None
    if args.pages:
        pages = [int(p.strip()) for p in args.pages.split(",")]

    backend = detect_backend()

    if backend is None:
        print("NO_BACKEND: No OCR backend available.")
        print("Install one of (recommended first):")
        print("  pip install rapidocr onnxruntime  (no system binary needed, ~80-100MB)")
        print("  pip install ocrmypdf              (+ Tesseract binary, ~5MB)")
        print("  pip install pytesseract           (+ Tesseract binary, <1MB)")
        sys.exit(2)

    scanned_count = len(pages) if pages else len(scan_data.get("scanned", []))
    print(f"OCR backend: {backend}")
    print(f"Scanned pages to process: {scanned_count}")

    try:
        if backend in ("rapidocr", "rapidocr_onnxruntime"):
            success, out_path = ocr_with_rapidocr(
                args.pdf_path, args.output, pages, scan_data, backend
            )
            if success:
                print(f"OCR complete. Text written to {out_path}")
                print("OUTPUT_TYPE: text")
            else:
                print("RapidOCR failed.", file=sys.stderr)
                sys.exit(1)

        elif backend == "ocrmypdf":
            success = ocr_with_ocrmypdf(args.pdf_path, args.output, pages)
            if success:
                print(f"OCR complete. Searchable PDF written to {args.output}")
                print("OUTPUT_TYPE: pdf")
            else:
                print("ocrmypdf reported failure.", file=sys.stderr)
                sys.exit(1)

        elif backend == "pytesseract":
            text_output = args.output
            if text_output.endswith(".pdf"):
                text_output = text_output.rsplit(".", 1)[0] + ".txt"
            success, out_path = ocr_with_pytesseract(
                args.pdf_path, text_output, pages, scan_data
            )
            if success:
                print(f"OCR complete. Text written to {out_path}")
                print("OUTPUT_TYPE: text")
            else:
                print("pytesseract OCR failed.", file=sys.stderr)
                sys.exit(1)

    except Exception as e:
        print(f"OCR error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
