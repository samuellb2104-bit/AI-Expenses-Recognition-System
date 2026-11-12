"""One-off fix for documents whose total was read without its thousands separator
("186.900" stored as 186.9).

Candidates are COP documents whose stored total is under 1.000 or has decimals.
Each one is re-extracted with the current prompt/schema, and ONLY `total_amount` and
`currency` are updated -- vendor, category and date are left alone so manual
corrections are never overwritten. The previous values are kept three ways: a JSON
backup file, the `processing_logs` row written for each document, and the previous
final extraction (kept, just marked is_final=False).

Usage (from expenses_organizer/backend):
    python -m app.db.reprocess_amounts --limit 5 --backup backup.json   # sample
    python -m app.db.reprocess_amounts --backup backup.json             # everything
    python -m app.db.reprocess_amounts --dry-run                        # no writes
"""

from __future__ import annotations

import argparse
import json
import random
import sys

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.processing_log import ProcessingLog
from app.services.ai_extraction_service import extract_with_claude, resolve_amount
from app.services.amount_validation_service import COP_IMPLAUSIBLY_SMALL
from app.services.storage_service import read_file_bytes


def _is_candidate(document: Document) -> bool:
    if document.total_amount is None or (document.currency or "").upper() != "COP":
        return False
    total = float(document.total_amount)
    return 0 < total < COP_IMPLAUSIBLY_SMALL or (total > 0 and total != round(total))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="process a random sample of N candidates")
    parser.add_argument("--seed", type=int, default=7, help="seed for --limit sampling")
    parser.add_argument("--dry-run", action="store_true", help="extract and show, but write nothing")
    parser.add_argument("--backup", default=None, help="path of the JSON backup of previous values")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with SessionLocal() as db:
        candidates = [d for d in db.query(Document).order_by(Document.created_at).all() if _is_candidate(d)]
        print(f"{len(candidates)} candidate documents (COP, total < 1.000 or with decimals).")
        if args.limit is not None:
            candidates = random.Random(args.seed).sample(candidates, min(args.limit, len(candidates)))
            print(f"Processing a random sample of {len(candidates)}.")

        backup: list[dict] = []
        changed = unchanged = failed = 0

        for document in candidates:
            doc_id = document.id
            old_total, old_currency = float(document.total_amount), document.currency
            try:
                data = extract_with_claude(read_file_bytes(document.storage_path), document.mime_type)
            except Exception as exc:  # noqa: BLE001 - keep going, report per document
                failed += 1
                print(f"  FAILED  {document.original_filename[:40]}: {str(exc)[:120]}")
                continue

            new_total = resolve_amount(data, "total_amount")
            new_currency = data.get("currency") or old_currency
            text = data.get("total_amount_text")
            if new_total is None:
                failed += 1
                print(f"  SKIPPED {document.original_filename[:40]}: no readable total (text={text!r})")
                continue

            flag = "same" if new_total == old_total else "FIXED"
            print(
                f"  {flag:5} {document.original_filename[:34]:34} | {old_total:>12,.2f} {old_currency or '-':3} "
                f"-> {new_total:>14,.2f} {new_currency or '-':3} | texto={text!r}"
            )
            backup.append(
                {
                    "document_id": str(doc_id),
                    "filename": document.original_filename,
                    "old_total_amount": old_total,
                    "old_currency": old_currency,
                    "new_total_amount": new_total,
                    "new_currency": new_currency,
                    "printed_text": text,
                }
            )

            if new_total == old_total and new_currency == old_currency:
                unchanged += 1
                continue
            changed += 1
            if args.dry_run:
                continue

            # The Claude call above can take long enough for the pooled connection held
            # by `db` to be dropped, so every write goes through its own short-lived
            # session and a failure only skips this document (re-running is safe: fixed
            # documents stop being candidates).
            try:
                with SessionLocal() as write_db:
                    target = write_db.get(Document, doc_id)
                    for previous in write_db.query(DocumentExtraction).filter(
                        DocumentExtraction.document_id == doc_id, DocumentExtraction.is_final.is_(True)
                    ):
                        previous.is_final = False
                    write_db.add(
                        DocumentExtraction(
                            document_id=doc_id,
                            extraction_method="ai",
                            provider_name="claude",
                            raw_text=None,
                            extracted_data=data,
                            confidence_score=None,
                            is_final=True,
                        )
                    )
                    target.total_amount = new_total
                    target.currency = new_currency
                    write_db.add(
                        ProcessingLog(
                            document_id=doc_id,
                            step_name="amount_reprocess",
                            status="success",
                            message="Total re-extracted to fix a misread thousands separator.",
                            meta={
                                "old_total_amount": old_total,
                                "old_currency": old_currency,
                                "new_total_amount": new_total,
                                "new_currency": new_currency,
                                "printed_text": text,
                            },
                        )
                    )
                    write_db.commit()
            except Exception as exc:  # noqa: BLE001 - keep going, report per document
                changed -= 1
                failed += 1
                print(f"  WRITE FAILED {document.original_filename[:40]}: {str(exc)[:120]}")

        if args.backup:
            with open(args.backup, "w", encoding="utf-8") as handle:
                json.dump(backup, handle, ensure_ascii=False, indent=2)
            print(f"Backup written to {args.backup}")

        mode = "DRY RUN - nothing written" if args.dry_run else "written"
        print(f"Done ({mode}): {changed} changed, {unchanged} unchanged, {failed} failed.")


if __name__ == "__main__":
    main()
