#!/usr/bin/env python3
# Dependencies
# pip install pdfplumber python-dateutil

import os
import re
import pdfplumber
from datetime import datetime
from dateutil import parser as dateparser

# if you get more vendor names in the future, add them here
COMPANY_NORMALIZATION = {
    # full/contains               -> short name
    "meriwether pest & wildlife": "Meriwether",
    "meriwether pest": "Meriwether",
    "meriwether": "Meriwether",
}


def normalize_company_name(name: str) -> str:
    if not name:
        return "Unknown"
    lower = name.lower()
    for key, short in COMPANY_NORMALIZATION.items():
        if key in lower:
            return short
    # fallback: take first word
    return name.strip().split()[0]


def extract_invoice_fields(pdf_path: str):
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # 1) find company name (above INVOICE)
    company_name = None
    for i, line in enumerate(lines):
        if line.upper().startswith("INVOICE"):
            # walk up to find business name
            for j in range(i - 1, -1, -1):
                cand = lines[j].strip()
                if cand and not cand.upper().startswith(("ACCOUNT #", "PO #", "DATE")):
                    company_name = cand
                    break
            break
    if not company_name and lines:
        company_name = lines[0]

    # 2) service date
    service_date = None
    for i, line in enumerate(lines):
        if "Service Date" in line:
            # next line should have dates separated by spaces
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # e.g. "September 22, 2025 September 22, 2025 ..."
                # take the first date-y chunk
                # split on 2+ spaces to avoid capturing all 3
                parts = re.split(r"\s{2,}", next_line)
                first_part = parts[0]
                try:
                    service_date = dateparser.parse(first_part, fuzzy=True)
                except Exception:
                    pass
            break

    # fallback to "DATE 09/22/2025"
    if service_date is None:
        for line in lines:
            m = re.search(r"\bDATE\s+(\d{1,2}/\d{1,2}/\d{4})", line, re.IGNORECASE)
            if m:
                service_date = datetime.strptime(m.group(1), "%m/%d/%Y")
                break

    if service_date is None:
        raise ValueError("Could not find service date")

    # 3) invoice number
    # in your sample: "INVOICE #52359" on its own line
    invoice_number = None
    for line in lines:
        m = re.search(r"INVOICE\s*#\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
            break

    if invoice_number is None:
        # softer fallback: look for "#12345"
        for line in lines:
            m = re.search(r"#\s*([0-9]{4,})", line)
            if m:
                invoice_number = m.group(1)
                break

    # 4) amount (stay with Subtotal like before)
    amount = None
    for line in lines:
        m = re.search(r"Subtotal\s+\$?([0-9,]+\.\d{2})", line, re.IGNORECASE)
        if m:
            amount = m.group(1)
            break

    # final return
    return {
        "company_name": company_name,
        "service_date": service_date,
        "invoice_number": invoice_number,
        "amount": amount,
        "raw_text": text,
    }


def sanitize_for_filename(s: str) -> str:
    s = s.strip()
    # avoid slashes, etc.
    s = s.replace("/", "-")
    return s


def build_new_filename(original_path: str, service_date: datetime,
                       short_company: str, invoice_number: str) -> str:
    base, ext = os.path.splitext(os.path.basename(original_path))
    date_prefix = service_date.strftime("%Y-%m-%d")
    short_company = sanitize_for_filename(short_company)
    inv_part = f"Invoice #{invoice_number}" if invoice_number else base
    new_name = f"{date_prefix}-{short_company}-{inv_part}{ext}"
    return new_name


def process_invoice(pdf_path: str, rename: bool = True) -> str:
    data = extract_invoice_fields(pdf_path)

    short_company = normalize_company_name(data["company_name"])
    new_name = build_new_filename(
        pdf_path,
        data["service_date"],
        short_company,
        data.get("invoice_number") or ""
    )

    if rename:
        folder = os.path.dirname(pdf_path)
        new_path = os.path.join(folder, new_name)
        os.rename(pdf_path, new_path)
        print(f"Renamed to: {new_path}")
        return new_path
    else:
        print("Would rename to:", new_name)
        return new_name


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rename invoice PDFs based on extracted fields.")
    parser.add_argument("pdf", help="Path to the invoice PDF")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, but don't rename")
    args = parser.parse_args()

    process_invoice(args.pdf, rename=not args.dry_run)

