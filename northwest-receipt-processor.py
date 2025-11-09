#!/opt/homebrew/bin/python3.11
# Dependencies
# brew install tesseract
# brew install poppler - Needed for pdf2image
# pip install pdfplumber python-dateutil
# pip install pdfplumber pytesseract pdf2image

import argparse
import json
import os
import re
from datetime import datetime

import pdfplumber
import pytesseract
from pdf2image import convert_from_path


def extract_text_with_pdfplumber(pdf_path: str) -> str:
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract_amount(text: str) -> str:
    """
    Find payment amount in the receipt text.
    Examples:
      PAYMENT AMOUNT $99.00
      Amount: $123.45
      TOTAL $88.88
    """
    patterns = [
        r"PAYMENT AMOUNT\s*\$?([\d,]+\.\d{2})",
        r"AMOUNT\s*\$?([\d,]+\.\d{2})",
        r"TOTAL\s*\$?([\d,]+\.\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", "")
    raise ValueError("Could not find payment amount in receipt text.")


def extract_date(text: str) -> str:
    """
    Look for MM/DD/YYYY and convert to YYYY-MM-DD.
    """
    m = re.search(r"DATE[:\s]+(\d{1,2}/\d{1,2}/\d{4})", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    if not m:
        raise ValueError("Could not find date in receipt text.")

    raw = m.group(1)
    dt = datetime.strptime(raw, "%m/%d/%Y")
    # Filename/date field format: YYYY-MM-dd
    return dt.strftime("%Y-%m-%d")


def extract_company_from_text(text: str) -> str:
    """
    Heuristic to find company from the text layer.
    First, look for known names; then a generic top-of-page scan.
    """
    # Known patterns (customize as needed)
    known = [
        (r"\bnorthwest exterminating\b", "Northwest Exterminating"),
        (r"\bnorthwest\b", "Northwest"),
    ]
    for pat, name in known:
        if re.search(pat, text, re.IGNORECASE):
            return name

    # Generic heuristic for other receipts
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skip_exact = {
        "payment", "receipt", "payment receipt", "confirmation",
        "amount", "date", "credit card", "name on card",
    }

    for ln in lines[:10]:
        norm = re.sub(r"\s+", " ", ln).strip()
        if not norm:
            continue

        low = norm.lower()
        if low in skip_exact:
            continue
        if any(label in low for label in [
            "payment receipt",
            "confirmation number",
            "payment amount",
            "credit card",
            "name on card",
            "date ",
        ]):
            continue
        # LABEL + digits (e.g. CONFIRMATION NUMBER 1921346628)
        if re.match(r"^[A-Z ]+\d+$", norm):
            continue
        # Purely numeric / code-ish
        if re.fullmatch(r"[\d\s\-#]+", norm):
            continue

        return norm

    return "Northwest"


def extract_company_from_logo_ocr(pdf_path: str) -> str:
    """
    Render the first page to an image, crop the top band
    (where the logo/company name usually is), and run OCR on it.
    Then look for 'Northwest Exterminating' / 'Northwest'.
    """
    try:
        # Only first page needed
        images = convert_from_path(pdf_path, dpi=300, first_page=1, last_page=1)
        if not images:
            return "Unknown"

        page_img = images[0]
        w, h = page_img.size

        # Crop top 25% of the page (tweak if needed)
        crop_box = (0, 0, w, int(h * 0.25))
        logo_img = page_img.crop(crop_box)

        ocr_text = pytesseract.image_to_string(logo_img)

        # Check for known company strings
        if re.search(r"northwest exterminating", ocr_text, re.IGNORECASE):
            return "Northwest Exterminating"
        if re.search(r"northwest", ocr_text, re.IGNORECASE):
            return "Northwest"

        # You can add more patterns here for other companies
    except Exception as e:
        # In a real script, you might log this somewhere
        # print(f"OCR error: {e}", file=sys.stderr)
        pass

    return "Unknown"


def extract_company(text: str, pdf_path: str) -> str:
    """
    Try text-based detection first, then fall back to OCR on the logo.
    """
    company = extract_company_from_text(text)
    if company != "Unknown":
        return company

    # Fallback to OCR on logo area
    company_ocr = extract_company_from_logo_ocr(pdf_path)
    return company_ocr if company_ocr != "Unknown" else "Unknown"


def sanitize_company(company: str) -> str:
    """
    Make the company name filesystem-safe.
    'Northwest Exterminating, Inc.' -> 'NorthwestExterminatingInc'
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", company)
    return cleaned or "Unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Parse a PDF receipt using pdfplumber + OCR for logo, "
                    "rename it, and output JSON."
    )
    parser.add_argument("pdf_path", help="Path to the PDF receipt file")
    args = parser.parse_args()

    pdf_path = os.path.abspath(args.pdf_path)
    if not os.path.isfile(pdf_path):
        raise SystemExit(f"File not found: {pdf_path}")

    text = extract_text_with_pdfplumber(pdf_path)
    amount = extract_amount(text)
    date_iso = extract_date(text)
    company = extract_company(text, pdf_path)
    company_for_file = sanitize_company(company)

    dirpath, old_name = os.path.split(pdf_path)
    _, ext = os.path.splitext(old_name)
    if not ext:
        ext = ".pdf"

    new_name = f"{date_iso}-{company_for_file}{ext}"
    new_path = os.path.join(dirpath, new_name)

    # Rename the file
    os.rename(pdf_path, new_path)

    result = {
        "fileName": new_path,
        "company": company,
        "amount": amount,
        "date": date_iso,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

