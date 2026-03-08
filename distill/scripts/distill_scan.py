#!/usr/bin/env python3
"""PDF content profiling — page-by-page classification.

Usage:
    python distill_scan.py <pdf_path> [--output _distill_scan.json]

Produces a per-page content profile: text presence, tables, complex layout,
scanned/empty pages, and equations. Output is JSON.
"""

import argparse
import json
import re
import sys

def scan_pdf(pdf_path):
    import pymupdf

    doc = pymupdf.open(pdf_path)
    scan = {
        "has_text": False,
        "tables": [],
        "complex_layout": [],
        "scanned": [],
        "equations": [],
        "text_pages": [],
        "confidence_notes": [],
        "page_count": len(doc),
    }

    for i, page in enumerate(doc):
        text = page.get_text("text")
        blocks = page.get_text("dict")["blocks"]
        text_blocks = [b for b in blocks if b["type"] == 0]
        stripped = text.strip()

        # Text presence
        if len(stripped) > 50:
            scan["has_text"] = True
            scan["text_pages"].append(i)
        else:
            scan["scanned"].append(i)
            if len(stripped) > 0:
                scan["confidence_notes"].append(
                    f"page {i} has minimal text — may be partially scanned or image-heavy"
                )

        # Table detection: 3+ text blocks with 3+ distinct aligned left-edge
        # x-columns with at least 30pt gap between them, OR pipe/tab/multi-space delimiters
        table_method = None
        if len(text_blocks) >= 3:
            left_edges = sorted(set(round(b["bbox"][0], 0) for b in text_blocks))
            if len(left_edges) >= 3:
                gaps = [left_edges[j + 1] - left_edges[j] for j in range(len(left_edges) - 1)]
                if any(g >= 30 for g in gaps):
                    scan["tables"].append(i)
                    table_method = "alignment"
        if re.search(r'\|.*\|', text) or re.search(r'\t.*\t', text):
            if i not in scan["tables"]:
                scan["tables"].append(i)
                table_method = "delimiter"
        if re.search(r'\S {3,}\S.*\S {3,}\S', text):
            if i not in scan["tables"]:
                scan["tables"].append(i)
                if table_method is None:
                    table_method = "spacing"
                    scan["confidence_notes"].append(
                        f"table on page {i} detected by spacing heuristic — may include non-table content"
                    )

        # Complex layout: 2+ x-position clusters separated by >100pt
        if len(text_blocks) >= 4:
            x_pos = sorted(set(round(b["bbox"][0], -1) for b in text_blocks))
            if len(x_pos) >= 2:
                gaps = [x_pos[j + 1] - x_pos[j] for j in range(len(x_pos) - 1)]
                if any(g > 100 for g in gaps):
                    scan["complex_layout"].append(i)

        # Equation detection: LaTeX commands, Unicode math, $$ blocks
        eq_method = None
        if re.search(r'\\(frac|int|sum|partial|begin\{equation)', text):
            scan["equations"].append(i)
            eq_method = "latex"
        if re.search(
            r'[\u222B\u2211\u220F\u2202\u2207\u221A\u221E\u2248\u2260\u2264\u2265]',
            text,
        ):
            if i not in scan["equations"]:
                scan["equations"].append(i)
                eq_method = "unicode"
                scan["confidence_notes"].append(
                    f"equations on page {i} detected by symbol presence — may be inline notation rather than display equations"
                )
        if re.search(r'\$\$.*?\$\$', text, re.DOTALL):
            if i not in scan["equations"]:
                scan["equations"].append(i)

    doc.close()
    return scan


def main():
    parser = argparse.ArgumentParser(description="PDF content profiling")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "--output", default="_distill_scan.json", help="Output JSON path"
    )
    args = parser.parse_args()

    scan = scan_pdf(args.pdf_path)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(scan, f, indent=2)

    # Print summary to stdout
    n = scan["page_count"]
    t = len(scan["text_pages"])
    tb = len(scan["tables"])
    cl = len(scan["complex_layout"])
    s = len(scan["scanned"])
    e = len(scan["equations"])
    print(f"{n} pages scanned: {t} text, {tb} tables, {cl} complex layout, {s} scanned/empty, {e} equations.")
    for note in scan["confidence_notes"]:
        print(f"  Note: {note}")


if __name__ == "__main__":
    main()
