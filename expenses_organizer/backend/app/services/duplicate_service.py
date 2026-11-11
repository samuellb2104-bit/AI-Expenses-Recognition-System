from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from itertools import combinations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.duplicate_dismissal import DuplicateDismissal
from app.models.vendor import Vendor
from app.schemas.duplicate import DuplicateDocument, DuplicateGroup, DuplicateReviewResponse

DEFAULT_DATE_WINDOW_DAYS = 5
VENDOR_NAME_SIMILARITY_THRESHOLD = 0.85

# Legal-form / filler tokens that say nothing about *who* the vendor is, so
# "Claro Colombia S.A.S." and "CLARO COLOMBIA" compare as the same name.
_NAME_NOISE_TOKENS = {"sas", "sa", "s", "a", "ltda", "cia", "eu", "srl", "inc", "llc", "de", "la", "el", "y", "e"}

# A comprobante de pago and its factura rarely disagree on the amount, so amounts
# must match to the cent; everything else (date, vendor) is what varies between them.
_AMOUNT_DECIMALS = 2


def normalize_vendor_name(name: str | None) -> str:
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", ascii_name) if t and t not in _NAME_NOISE_TOKENS]
    return " ".join(tokens)


def vendor_names_similar(name_a: str | None, name_b: str | None) -> bool:
    norm_a, norm_b = normalize_vendor_name(name_a), normalize_vendor_name(name_b)
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True

    tokens_a, tokens_b = set(norm_a.split()), set(norm_b.split())
    smaller, larger = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    # "claro" vs "claro colombia": one name is the other plus extra words.
    if smaller <= larger and any(len(token) >= 4 for token in smaller):
        return True

    return SequenceMatcher(None, norm_a, norm_b).ratio() >= VENDOR_NAME_SIMILARITY_THRESHOLD


def _vendor_relation(
    doc_a: Document, doc_b: Document, vendors_by_id: dict[uuid.UUID, Vendor]
) -> str | None:
    """'same' | 'similar' | 'unknown' (a vendor is missing) | None (clearly different vendors)."""
    if doc_a.vendor_id is None or doc_b.vendor_id is None:
        return "unknown"
    if doc_a.vendor_id == doc_b.vendor_id:
        return "same"

    vendor_a, vendor_b = vendors_by_id.get(doc_a.vendor_id), vendors_by_id.get(doc_b.vendor_id)
    if vendor_a is None or vendor_b is None:
        return "unknown"
    if vendor_a.tax_id and vendor_b.tax_id and vendor_a.tax_id == vendor_b.tax_id:
        return "same"
    if vendor_names_similar(vendor_a.name, vendor_b.name):
        return "similar"
    return None


def _date_relation(date_a: date | None, date_b: date | None, window_days: int) -> str | None:
    """'same' | 'close' | 'unknown' (a date is missing) | None (too far apart)."""
    if date_a is None or date_b is None:
        return "unknown"
    gap = abs((date_a - date_b).days)
    if gap == 0:
        return "same"
    if gap <= window_days:
        return "close"
    return None


def _score_pair(vendor_rel: str, date_rel: str) -> tuple[int, list[str]]:
    reasons = ["Mismo valor"]
    score = 0

    if vendor_rel == "same":
        reasons.append("Mismo proveedor")
        score += 2
    elif vendor_rel == "similar":
        reasons.append("Proveedor similar")
        score += 1
    else:
        reasons.append("Proveedor sin asignar en alguno de los documentos")

    if date_rel == "same":
        reasons.append("Misma fecha")
        score += 2
    elif date_rel == "close":
        reasons.append("Fechas cercanas")
        score += 1
    else:
        reasons.append("Fecha faltante en alguno de los documentos")

    return score, reasons


def _confidence_label(score: int) -> str:
    # Max score is 4 (same vendor + same date). Anything with a missing vendor/date
    # tops out lower and is worth a look but shouldn't read as a sure thing.
    if score >= 3:
        return "alta"
    if score >= 2:
        return "media"
    return "baja"


def find_probable_duplicates(
    db: Session,
    company_id: uuid.UUID,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
) -> DuplicateReviewResponse:
    documents = (
        db.query(Document)
        .filter(
            Document.company_id == company_id,
            Document.total_amount.is_not(None),
            Document.total_amount > 0,
        )
        .all()
    )

    vendor_ids = {d.vendor_id for d in documents if d.vendor_id is not None}
    vendors_by_id = (
        {v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()} if vendor_ids else {}
    )

    dismissed_pairs = {
        frozenset((row.document_a_id, row.document_b_id))
        for row in db.query(DuplicateDismissal).filter(DuplicateDismissal.company_id == company_id).all()
    }

    # Bucketing by (amount, currency) keeps the pairwise comparison cheap: only
    # documents that already share an exact total are ever compared to each other.
    buckets: dict[tuple[float, str], list[Document]] = defaultdict(list)
    for document in documents:
        key = (round(float(document.total_amount), _AMOUNT_DECIMALS), (document.currency or "").upper())
        buckets[key].append(document)

    # Union-find so three documents for the same expense (factura + comprobante +
    # a re-upload) end up in one group instead of three overlapping pairs.
    parent: dict[uuid.UUID, uuid.UUID] = {}

    def find(node: uuid.UUID) -> uuid.UUID:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: uuid.UUID, b: uuid.UUID) -> None:
        parent[find(a)] = find(b)

    pair_scores: dict[frozenset[uuid.UUID], tuple[int, list[str]]] = {}
    for bucket_documents in buckets.values():
        if len(bucket_documents) < 2:
            continue
        for doc_a, doc_b in combinations(bucket_documents, 2):
            if frozenset((doc_a.id, doc_b.id)) in dismissed_pairs:
                continue
            vendor_rel = _vendor_relation(doc_a, doc_b, vendors_by_id)
            if vendor_rel is None:
                continue
            date_rel = _date_relation(doc_a.document_date, doc_b.document_date, date_window_days)
            if date_rel is None:
                continue
            # Both vendor and date unknown would flag any two documents with the same
            # total -- too weak a signal to put in front of the user.
            if vendor_rel == "unknown" and date_rel == "unknown":
                continue

            pair_scores[frozenset((doc_a.id, doc_b.id))] = _score_pair(vendor_rel, date_rel)
            union(doc_a.id, doc_b.id)

    documents_by_id = {d.id: d for d in documents}
    members_by_root: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for document_id in parent:
        members_by_root[find(document_id)].append(document_id)

    groups: list[DuplicateGroup] = []
    for member_ids in members_by_root.values():
        if len(member_ids) < 2:
            continue

        member_pairs = [pair_scores[p] for p in pair_scores if p <= set(member_ids)]
        # A group is as trustworthy as its best-matching pair; collect every reason
        # that applied so the UI can explain *why* these were flagged.
        best_score = max(score for score, _ in member_pairs)
        reasons = list(dict.fromkeys(reason for _, pair_reasons in member_pairs for reason in pair_reasons))

        member_documents = sorted(
            (documents_by_id[i] for i in member_ids),
            key=lambda d: (d.document_date or date.max, d.created_at),
        )
        first = member_documents[0]
        groups.append(
            DuplicateGroup(
                confidence=_confidence_label(best_score),
                reasons=reasons,
                total_amount=float(first.total_amount),
                currency=first.currency,
                possible_overcount=round(float(first.total_amount) * (len(member_documents) - 1), 2),
                documents=[
                    DuplicateDocument(
                        id=d.id,
                        original_filename=d.original_filename,
                        document_type=d.document_type,
                        status=d.status,
                        vendor_id=d.vendor_id,
                        vendor_name=vendors_by_id[d.vendor_id].name if d.vendor_id in vendors_by_id else None,
                        total_amount=float(d.total_amount),
                        currency=d.currency,
                        document_date=d.document_date,
                        created_at=d.created_at,
                    )
                    for d in member_documents
                ],
            )
        )

    confidence_order = {"alta": 0, "media": 1, "baja": 2}
    groups.sort(key=lambda g: (confidence_order[g.confidence], -g.possible_overcount))

    return DuplicateReviewResponse(
        groups=groups,
        scanned_document_count=len(documents),
        date_window_days=date_window_days,
    )


def dismiss_duplicate_group(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID | None,
    document_ids: list[uuid.UUID],
) -> int:
    """Marks every pair among `document_ids` as 'not a duplicate' so the review
    stops flagging them. Returns how many new pairs were recorded (idempotent)."""
    unique_ids = list(dict.fromkeys(document_ids))
    if len(unique_ids) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Se necesitan al menos 2 documentos.")

    owned_count = (
        db.query(Document.id)
        .filter(Document.company_id == company_id, Document.id.in_(unique_ids))
        .count()
    )
    # Anti-IDOR: every id must belong to the caller's company.
    if owned_count != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    existing = {
        (row.document_a_id, row.document_b_id)
        for row in db.query(DuplicateDismissal).filter(
            DuplicateDismissal.company_id == company_id,
            DuplicateDismissal.document_a_id.in_(unique_ids),
        )
    }

    created = 0
    for doc_a, doc_b in combinations(sorted(unique_ids), 2):
        if (doc_a, doc_b) in existing:
            continue
        db.add(
            DuplicateDismissal(
                company_id=company_id,
                document_a_id=doc_a,
                document_b_id=doc_b,
                dismissed_by=user_id,
            )
        )
        created += 1

    db.commit()
    return created
