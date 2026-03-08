#!/usr/bin/env python3
"""UTF-8 text extraction with encoding safety.

Usage:
    python distill_extract.py <pdf_path> --scan _distill_scan.json [--output _distill_text.txt]

Extracts text from all text pages identified by the scan. Writes to a UTF-8
file (never stdout) to avoid Windows cp1252 encoding errors with Greek,
math symbols, and diacritics.
"""

import argparse
import json
import sys


def extract_text(pdf_path, scan_data, output_path):
    import pymupdf

    doc = pymupdf.open(pdf_path)
    text_pages = scan_data.get("text_pages", [])

    with open(output_path, "w", encoding="utf-8") as out:
        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text("text")

            # Page header
            out.write(f"\n{'='*60}\n")
            out.write(f"PAGE {i + 1}")

            # Annotate page type from scan
            annotations = []
            if i in text_pages:
                annotations.append("text")
            if i in scan_data.get("tables", []):
                annotations.append("tables")
            if i in scan_data.get("complex_layout", []):
                annotations.append("complex_layout")
            if i in scan_data.get("scanned", []):
                annotations.append("scanned")
            if i in scan_data.get("equations", []):
                annotations.append("equations")
            if annotations:
                out.write(f" [{', '.join(annotations)}]")

            out.write(f"\n{'='*60}\n\n")

            stripped = text.strip()
            if stripped:
                out.write(stripped)
                out.write("\n")
            else:
                out.write("[No extractable text — scanned or image-only page]\n")

    doc.close()
    page_count = scan_data.get("page_count", len(doc) if not doc.is_closed else 0)
    print(f"Extracted {len(text_pages)} text pages (of {page_count} total) to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="PDF text extraction")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "--scan", required=True, help="Path to scan JSON from distill_scan.py"
    )
    parser.add_argument(
        "--output", default="_distill_text.txt", help="Output text file path"
    )
    args = parser.parse_args()

    with open(args.scan, "r", encoding="utf-8") as f:
        scan_data = json.load(f)

    extract_text(args.pdf_path, scan_data, args.output)


if __name__ == "__main__":
    main()
