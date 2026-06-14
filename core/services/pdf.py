from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from django.conf import settings
from django.urls import reverse

from core.models import DesignAsset, DesignAssetFile, PrintJob

# Canonical size order shown on the print pack size grid.
BASE_SIZES: list[str] = ["S", "M", "L", "XL", "XXL", "XXXL"]

# Normalisation map so 2XL/3XL inputs line up with the printed grid columns.
_SIZE_ALIASES: dict[str, str] = {
    "2XL": "XXL",
    "3XL": "XXXL",
    "4XL": "XXXXL",
    "XS": "XS",
}

# Fallback swatch colours keyed by lowercased colour name.
_COLOUR_HEX: dict[str, str] = {
    "black": "#1b1b1b",
    "white": "#ffffff",
    "off white": "#efe7d3",
    "off-white": "#efe7d3",
    "offwhite": "#efe7d3",
    "cream": "#efe7d3",
    "natural": "#efe7d3",
    "ivory": "#f2ead6",
    "navy": "#1f2a44",
    "red": "#c8102e",
    "maroon": "#7b1f2b",
    "blue": "#2b6cb0",
    "royal blue": "#1d4ed8",
    "sky blue": "#7dc2e8",
    "green": "#2e7d32",
    "bottle green": "#0b3d2e",
    "olive": "#5b6236",
    "sage": "#9caf88",
    "grey": "#9aa0a6",
    "gray": "#9aa0a6",
    "charcoal": "#36393f",
    "yellow": "#f4c20d",
    "mustard": "#d4a017",
    "pink": "#e75480",
    "beige": "#e3d4b3",
    "sand": "#d9c7a3",
    "brown": "#5b4636",
    "lavender": "#b497bd",
    "purple": "#6b3fa0",
    "orange": "#e8772e",
}


@dataclass
class PrintPackCard:
    """A single print pack page representing one design + colour combination."""

    design: Any
    colour: str
    sizes: dict[str, int] = field(default_factory=dict)
    asset: DesignAsset | None = None
    image_reader: Any | None = None

    @property
    def total_qty(self) -> int:
        return sum(self.sizes.values())


def to_google_drive_direct_view(url: str) -> str:
    """Convert a Google Drive share link into a direct-view link when possible."""
    if not url or "drive.google.com" not in url:
        return url
    marker = "/d/"
    if marker in url:
        file_id = url.split(marker, 1)[1].split("/", 1)[0]
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    return url


def _normalise_size(size: str | None) -> str:
    """Map raw size labels onto the canonical grid labels (e.g. 3XL -> XXXL)."""
    value = (size or "").strip().upper()
    return _SIZE_ALIASES.get(value, value)


def _resolve_print_job(print_job_id: str) -> PrintJob:
    """Resolve a print job by id, or by batch id for compatibility with older callers."""
    print_job = (
        PrintJob.objects.select_related("vendor", "batch")
        .prefetch_related("lines__printed_sku__design__assets", "lines__blank_sku")
        .filter(id=print_job_id)
        .first()
    )
    if print_job is not None:
        return print_job
    fallback = (
        PrintJob.objects.select_related("vendor", "batch")
        .prefetch_related("lines__printed_sku__design__assets", "lines__blank_sku")
        .filter(batch_id=print_job_id)
        .first()
    )
    if fallback is None:
        raise PrintJob.DoesNotExist(f"No PrintJob found for id or batch id {print_job_id}")
    return fallback


def _fetch_image_reader(url: str) -> Any | None:
    """Fetch a remote mockup image and return a ReportLab ImageReader, or None on failure."""
    if not url:
        return None
    try:
        import requests
        from PIL import Image
        from reportlab.lib.utils import ImageReader

        response = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BoldERP-PrintPack/1.0)"},
        )
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return ImageReader(buffer)
    except Exception:
        return None


def _build_cards(print_job: PrintJob) -> list[PrintPackCard]:
    """Group print job lines into per design+colour cards with summed size quantities."""
    grouped: dict[tuple[str, str], PrintPackCard] = {}
    for line in print_job.lines.all().order_by("created_at"):
        printed_sku = line.printed_sku
        design = printed_sku.design
        colour = printed_sku.colour or ""
        key = (str(design.id), colour.lower())
        card = grouped.get(key)
        if card is None:
            card = PrintPackCard(design=design, colour=colour)
            grouped[key] = card
        size = _normalise_size(printed_sku.size) or "NA"
        card.sizes[size] = card.sizes.get(size, 0) + int(line.qty_sent or 0)

    cards = sorted(grouped.values(), key=lambda c: (c.design.name.lower(), c.colour.lower()))
    for card in cards:
        card.asset = card.design.assets.filter(colour__iexact=card.colour).first()
        mockup_url = ""
        if card.asset and card.asset.mockup_url:
            mockup_url = to_google_drive_direct_view(card.asset.mockup_url)
        elif card.asset:
            mockup_file = (
                card.asset.files.filter(file_type=DesignAssetFile.FileType.MOCKUP)
                .order_by("placement", "created_at")
                .first()
            )
            if mockup_file and mockup_file.file_url:
                mockup_url = to_google_drive_direct_view(mockup_file.file_url)
        card.image_reader = _fetch_image_reader(mockup_url)
    return cards


def generate_print_pack_pdf(print_job_id: str) -> str:
    """Generate a Print Pack PDF for a print job and return its URL.

    Renders one page per design + colour combination in the Bold & Italic
    print pack layout using ReportLab, so it works on local Windows
    development without GTK/WeasyPrint dependencies.
    """
    print_job = _resolve_print_job(print_job_id)
    output_dir = Path(getattr(settings, "MEDIA_ROOT", Path(settings.BASE_DIR) / "media")) / "print_packs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"print_pack_{print_job.id}.pdf"

    cards = _build_cards(print_job)
    _write_print_pack_pdf(cards, output_path)

    pdf_url = reverse("print-pack-file", args=[output_path.name])
    print_job.pdf_url = pdf_url
    print_job.save(update_fields=["pdf_url", "updated_at"])

    if print_job.batch_id:
        print_job.batch.print_pack_path = str(output_path)
        print_job.batch.save(update_fields=["print_pack_path", "updated_at"])

    return pdf_url


def build_print_pack_pdf(print_job_id: str) -> str:
    """Compatibility alias for callers expecting the build_* name."""
    return generate_print_pack_pdf(print_job_id)


def _swatch_colour(colour_name: str, hex_value: str) -> Any:
    """Return a ReportLab colour for the swatch from an explicit hex or a name fallback."""
    from reportlab.lib.colors import HexColor

    candidate = (hex_value or "").strip()
    if candidate:
        if not candidate.startswith("#"):
            candidate = f"#{candidate}"
        try:
            return HexColor(candidate)
        except Exception:
            pass
    fallback = _COLOUR_HEX.get((colour_name or "").strip().lower(), "#cccccc")
    return HexColor(fallback)


def _draw_card(pdf: Any, page_w: float, page_h: float, card: PrintPackCard, index: int) -> None:
    """Draw one print pack card page onto the canvas."""
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth

    margin = 36.0
    left_col_right = 400.0

    # ---- Brand logo ----
    logo_y = page_h - margin - 24
    pdf.setFillColor(HexColor("#9aa0a6"))
    pdf.setFont("Times-BoldItalic", 34)
    pdf.drawString(margin, logo_y, "B")
    pdf.setFont("Helvetica-Bold", 6)
    pdf.setFillColor(HexColor("#8a8f98"))
    pdf.drawString(margin + 2, logo_y - 10, "B O L D   &   I T A L I C")

    # ---- Order title ----
    title_y = page_h - margin - 96
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawString(margin, title_y, f"Order #{index}")

    # ---- Details table ----
    design = card.design
    fit_value = getattr(design, "fit", "") or "Regular"
    material_value = getattr(design, "material", "") or "Cotton"
    print_areas = (card.asset.print_areas if card.asset and card.asset.print_areas else "") or "Front"

    rows = [
        ("NAME", design.name, False),
        ("MATERIAL", material_value, False),
        ("COLOR", card.colour or "-", True),
        ("FIT", fit_value, False),
        ("PRINT AREAS", print_areas, False),
    ]

    label_x = margin
    value_x = margin + 120
    value_max_w = left_col_right - 30 - value_x
    row_h = 30.0
    y = title_y - 26

    pdf.setLineWidth(0.7)
    for label, value, is_colour in rows:
        pdf.setStrokeColor(HexColor("#e2e4e8"))
        pdf.line(label_x, y, left_col_right - 20, y)
        cy = y - 20
        pdf.setFont("Helvetica", 8.5)
        pdf.setFillColor(HexColor("#9aa0a6"))
        pdf.drawString(label_x, cy, label)

        pdf.setFont("Helvetica-Bold", 12)
        pdf.setFillColor(black)
        original = str(value)
        text = original
        while text and stringWidth(text, "Helvetica-Bold", 12) > value_max_w:
            text = text[:-1]
        if text != original:
            text = text[:-1] + "\u2026"
        pdf.drawString(value_x, cy, text)

        if is_colour:
            swatch = _swatch_colour(card.colour, card.asset.colour_hex if card.asset else "")
            sx = value_x + stringWidth(text, "Helvetica-Bold", 12) + 10
            pdf.setFillColor(swatch)
            pdf.setStrokeColor(HexColor("#c4c4c4"))
            pdf.setLineWidth(0.8)
            pdf.rect(sx, cy - 3, 26, 15, fill=1, stroke=1)
            pdf.setFillColor(black)
        y -= row_h

    pdf.setStrokeColor(HexColor("#e2e4e8"))
    pdf.line(label_x, y, left_col_right - 20, y)

    # ---- Quantity heading ----
    qty_y = y - 40
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(margin, qty_y, f"Quantity - {card.total_qty}")

    # ---- Size grid ----
    extras = sorted(s for s, q in card.sizes.items() if s not in BASE_SIZES and q)
    columns = BASE_SIZES + extras
    cell_w = 46.0
    head_h = 24.0
    val_h = 28.0
    grid_x = margin
    head_top = qty_y - 22

    for i, col in enumerate(columns):
        x = grid_x + i * cell_w
        # header cell
        pdf.setFillColor(black)
        pdf.rect(x, head_top - head_h, cell_w, head_h, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawCentredString(x + cell_w / 2, head_top - head_h + 8, col)
        # value cell
        pdf.setFillColor(white)
        pdf.setStrokeColor(HexColor("#c4c4c4"))
        pdf.setLineWidth(0.9)
        pdf.rect(x, head_top - head_h - val_h, cell_w, val_h, fill=1, stroke=1)
        qty = card.sizes.get(col, 0)
        if qty:
            pdf.setFillColor(black)
            pdf.setFont("Helvetica-Bold", 13)
            pdf.drawCentredString(x + cell_w / 2, head_top - head_h - val_h + 9, str(qty))

    grid_bottom = head_top - head_h - val_h

    # ---- Mockup image (right side) ----
    mock_x0 = 415.0
    mock_x1 = page_w - margin
    mock_y0 = 64.0
    mock_y1 = page_h - margin - 64
    region_w = mock_x1 - mock_x0
    region_h = mock_y1 - mock_y0
    chest_point: tuple[float, float] | None = None

    if card.image_reader is not None:
        try:
            iw, ih = card.image_reader.getSize()
            scale = min(region_w / iw, region_h / ih)
            draw_w = iw * scale
            draw_h = ih * scale
            dx = mock_x0 + (region_w - draw_w) / 2
            dy = mock_y0 + (region_h - draw_h) / 2
            pdf.drawImage(
                card.image_reader,
                dx,
                dy,
                draw_w,
                draw_h,
                preserveAspectRatio=True,
                mask="auto",
            )
            chest_point = (dx + draw_w * 0.5, dy + draw_h * 0.62)
        except Exception:
            card.image_reader = None

    if card.image_reader is None:
        pdf.setFillColor(HexColor("#f4f4f4"))
        pdf.setStrokeColor(HexColor("#dddddd"))
        pdf.setLineWidth(1)
        pdf.rect(mock_x0, mock_y0, region_w, region_h, fill=1, stroke=1)
        pdf.setFillColor(HexColor("#999999"))
        pdf.setFont("Helvetica", 12)
        pdf.drawCentredString(
            mock_x0 + region_w / 2,
            mock_y0 + region_h / 2,
            "Mockup not available",
        )

    # ---- Placement note ----
    note = (card.asset.placement_note if card.asset and card.asset.placement_note else "").strip()
    note_y = grid_bottom - 36
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, note_y, "Placement")
    note_anchor = (margin + stringWidth("Placement", "Helvetica-Bold", 11) + 6, note_y + 2)
    if note:
        pdf.setFont("Helvetica", 9.5)
        pdf.setFillColor(HexColor("#444444"))
        wrapped = simpleSplit(note, "Helvetica", 9.5, left_col_right - 20 - margin)
        ly = note_y - 16
        for text_line in wrapped[:4]:
            pdf.drawString(margin, ly, text_line)
            ly -= 13

    # ---- Red pointer line to the chest ----
    if note and chest_point is not None:
        pdf.setStrokeColor(HexColor("#d12b2b"))
        pdf.setLineWidth(1.3)
        pdf.line(note_anchor[0], note_anchor[1], chest_point[0], chest_point[1])
        pdf.setFillColor(HexColor("#d12b2b"))
        pdf.circle(chest_point[0], chest_point[1], 2.4, fill=1, stroke=0)


def _write_print_pack_pdf(cards: list[PrintPackCard], output_path: Path) -> None:
    """Render all print pack cards to a multi-page landscape A4 PDF."""
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    page_w, page_h = landscape(A4)
    pdf = canvas.Canvas(str(output_path), pagesize=landscape(A4))

    if not cards:
        pdf.setFillColor(black)
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(40, page_h - 60, "Print Pack")
        pdf.setFont("Helvetica", 12)
        pdf.setFillColor(HexColor("#666666"))
        pdf.drawString(40, page_h - 90, "No lines found for this print job.")
        pdf.showPage()
        pdf.save()
        return

    for index, card in enumerate(cards, start=1):
        _draw_card(pdf, page_w, page_h, card, index)
        pdf.showPage()

    pdf.save()
