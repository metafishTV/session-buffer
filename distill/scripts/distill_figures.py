#!/usr/bin/env python3
"""Cropped figure extraction with verification manifest.

Usage:
    python distill_figures.py <pdf_path> --scan _distill_scan.json --outdir <figures_dir> [--manifest _manifest.json]

Extracts cropped figures, tables, and visual elements from PDF pages
identified by the scan. Produces a manifest listing all extracted items.
"""

import argparse
import json
import os
import re
import sys


def extract_figures(pdf_path, scan_data, outdir, manifest_path):
    import pymupdf

    os.makedirs(outdir, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    manifest = []

    # Collect all pages that may have figures: tables, complex_layout,
    # scanned, equations, plus any text page with images
    figure_pages = set()
    figure_pages.update(scan_data.get("tables", []))
    figure_pages.update(scan_data.get("complex_layout", []))
    figure_pages.update(scan_data.get("scanned", []))
    figure_pages.update(scan_data.get("equations", []))

    # Also check all text pages for embedded images
    for i in scan_data.get("text_pages", []):
        page = doc[i]
        if page.get_images(full=True):
            figure_pages.add(i)

    fig_counter = 0
    tab_counter = 0
    visual_counter = 0
    eq_counter = 0

    CAPTION_SEARCH_PTS = 80
    CAPTION_OVERLAP_PTS = 20

    for page_num in sorted(figure_pages):
        page = doc[page_num]
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        text_dict = page.get_text("dict")
        text_blocks = [b for b in text_dict["blocks"] if b["type"] == 0]

        # ---- Detection channels ----

        items = []  # list of (crop_rect, label, caption_text, item_type)

        # Channel 1: Vector drawings
        try:
            clusters = page.cluster_drawings(x_tolerance=5, y_tolerance=5)
            for rect in clusters:
                r = pymupdf.Rect(rect)
                if r.width * r.height > 0.05 * page_area:
                    items.append((r, None, None, "vector"))
        except Exception:
            pass

        # Channel 2: Raster images
        for img in page.get_images(full=True):
            try:
                bbox = page.get_image_bbox(img)
                if bbox and bbox.width * bbox.height > 0.05 * page_area:
                    # Avoid duplicates with vector clusters
                    is_dup = False
                    for existing_rect, _, _, _ in items:
                        overlap = existing_rect & bbox
                        if overlap and overlap.width * overlap.height > 0.5 * bbox.width * bbox.height:
                            is_dup = True
                            break
                    if not is_dup:
                        items.append((bbox, None, None, "raster"))
            except Exception:
                continue

        # Channel 3: Caption-based detection
        caption_pattern = re.compile(
            r'^(Figure|Fig\.|Table|Equation|Eq\.)\s+(\d+)', re.IGNORECASE
        )
        for block in text_blocks:
            block_text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("text", "")
                block_text += " "
            block_text = block_text.strip()

            match = caption_pattern.match(block_text)
            if match:
                caption_type = match.group(1).lower().rstrip(".")
                caption_num = match.group(2)
                caption_rect = pymupdf.Rect(block["bbox"])

                # Try to associate with an existing visual element
                associated = False
                for idx, (rect, label, cap, itype) in enumerate(items):
                    # Caption within CAPTION_SEARCH_PTS below, or CAPTION_OVERLAP_PTS above
                    if (
                        abs(caption_rect.y0 - rect.y1) < CAPTION_SEARCH_PTS
                        or abs(rect.y0 - caption_rect.y1) < CAPTION_OVERLAP_PTS
                    ):
                        # Extend the crop to include caption
                        combined = rect | caption_rect
                        items[idx] = (combined, f"{caption_type}_{caption_num}", block_text, itype)
                        associated = True
                        break

                if not associated:
                    # Text-only table/figure — crop from caption through content
                    items.append((caption_rect, f"{caption_type}_{caption_num}", block_text, "caption_only"))

        # ---- Equation detection (text-block coordinate crop) ----
        if page_num in scan_data.get("equations", []):
            eq_pattern = re.compile(r'\\(frac|int|sum|partial|begin\{equation)')
            for block in text_blocks:
                block_text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "")
                    block_text += " "
                if eq_pattern.search(block_text) or re.search(
                    r'[\u222B\u2211\u220F\u2202\u2207\u221A\u221E\u2248\u2260\u2264\u2265]',
                    block_text,
                ):
                    eq_rect = pymupdf.Rect(block["bbox"])
                    # Avoid duplicating already-captured items
                    is_dup = False
                    for existing_rect, _, _, _ in items:
                        overlap = existing_rect & eq_rect
                        if overlap and overlap.width * overlap.height > 0.5 * eq_rect.width * eq_rect.height:
                            is_dup = True
                            break
                    if not is_dup:
                        items.append((eq_rect, None, block_text[:80], "equation"))

        # ---- Crop, render, and label ----
        for crop_rect, label, caption_text, item_type in items:
            # Assign label if not already set
            if label is None:
                if item_type == "equation":
                    eq_counter += 1
                    label = f"eq_{eq_counter:02d}"
                else:
                    visual_counter += 1
                    label = f"visual_{visual_counter:02d}"
            else:
                # Parse label to update counters
                if label.startswith("fig"):
                    fig_counter += 1
                elif label.startswith("tab"):
                    tab_counter += 1

            filename = f"{label}_p{page_num + 1}.png"
            filepath = os.path.join(outdir, filename)

            # Add small padding (5pt) and clamp to page bounds
            padded = pymupdf.Rect(
                max(crop_rect.x0 - 5, page_rect.x0),
                max(crop_rect.y0 - 5, page_rect.y0),
                min(crop_rect.x1 + 5, page_rect.x1),
                min(crop_rect.y1 + 5, page_rect.y1),
            )

            dpi = 200
            try:
                pix = page.get_pixmap(clip=padded, dpi=dpi)
                pix.save(filepath)
            except MemoryError:
                # Reduce DPI on memory error
                dpi = 150
                try:
                    pix = page.get_pixmap(clip=padded, dpi=dpi)
                    pix.save(filepath)
                except MemoryError:
                    dpi = 100
                    pix = page.get_pixmap(clip=padded, dpi=dpi)
                    pix.save(filepath)

            manifest.append({
                "filename": filename,
                "page": page_num + 1,
                "label": label,
                "item_type": item_type,
                "caption": caption_text,
                "crop": [round(padded.x0, 1), round(padded.y0, 1),
                         round(padded.x1, 1), round(padded.y1, 1)],
                "dpi": dpi,
            })

        # Full-page fallback for scanned pages with no extracted items
        if page_num in scan_data.get("scanned", []):
            page_items = [m for m in manifest if m["page"] == page_num + 1]
            if not page_items:
                filename = f"page_{page_num + 1}.png"
                filepath = os.path.join(outdir, filename)
                dpi = 150
                if page_num in scan_data.get("equations", []):
                    dpi = 200
                    filename = f"page_{page_num + 1}_equations_dpi200.png"
                    filepath = os.path.join(outdir, filename)
                pix = page.get_pixmap(dpi=dpi)
                pix.save(filepath)
                manifest.append({
                    "filename": filename,
                    "page": page_num + 1,
                    "label": f"page_{page_num + 1}",
                    "item_type": "full_page_fallback",
                    "caption": None,
                    "crop": None,
                    "dpi": dpi,
                })

    doc.close()

    # Write manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Extracted {len(manifest)} items to {outdir}")
    print(f"Manifest written to {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="PDF figure extraction")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "--scan", required=True, help="Path to scan JSON from distill_scan.py"
    )
    parser.add_argument("--outdir", required=True, help="Output directory for figures")
    parser.add_argument(
        "--manifest", default="_manifest.json", help="Output manifest JSON path"
    )
    args = parser.parse_args()

    with open(args.scan, "r", encoding="utf-8") as f:
        scan_data = json.load(f)

    extract_figures(args.pdf_path, scan_data, args.outdir, args.manifest)


if __name__ == "__main__":
    main()
