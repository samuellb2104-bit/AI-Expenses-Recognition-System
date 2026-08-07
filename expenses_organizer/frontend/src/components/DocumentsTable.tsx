import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  classifyDocument,
  createExpenseCategory,
  createVendor,
  deleteDocument,
  fetchDocumentFile,
  listDocuments,
  listExpenseCategories,
  listVendors,
  reprocessWithAi,
} from "../api/client";
import type { DocumentListItem, ExpenseCategoryRead, VendorRead } from "../api/types";

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Subido",
  processing: "Procesando...",
  batch_queued: "En lote (IA)...",
  ocr_failed: "OCR fallo",
  ocr_completed: "Procesado (OCR)",
  ai_extraction_completed: "Procesado (IA)",
  needs_review: "Revisar",
};

// Any status other than a completed AI extraction means the pipeline never finished
// successfully (stuck upload, transient OCR/Claude error) -- offer a retry for those.
// "processing" and "batch_queued" are excluded: something else already has the
// document claimed (backend auto-resume, or an outstanding Anthropic Message Batch),
// so a manual retry here would just race it.
const RETRYABLE_STATUSES = new Set(["uploaded", "ocr_failed", "ocr_completed", "needs_review"]);

// How often to re-poll GET /documents while any document is still 'batch_queued' --
// batch results land minutes later, out-of-band from any user action, so nothing else
// in this app would ever surface them without a timer.
const BATCH_POLL_INTERVAL_MS = 20_000;

function formatAmount(totalAmount: number | null, currency: string | null): string {
  if (totalAmount == null) return "-";
  const formatted = totalAmount.toLocaleString("es-CO", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  return currency ? `${currency} ${formatted}` : formatted;
}

function formatDocumentDate(documentDate: string | null): string {
  return documentDate ?? "-";
}

interface DocumentsTableProps {
  refreshSignal: number;
}

export function DocumentsTable({ refreshSignal }: DocumentsTableProps) {
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [vendors, setVendors] = useState<VendorRead[]>([]);
  const [categories, setCategories] = useState<ExpenseCategoryRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newVendorName, setNewVendorName] = useState("");
  const [newCategoryName, setNewCategoryName] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [documentDateFrom, setDocumentDateFrom] = useState("");
  const [documentDateTo, setDocumentDateTo] = useState("");
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; mimeType: string; filename: string } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docs, vendorList, categoryList] = await Promise.all([
        listDocuments({
          documentDateFrom: documentDateFrom || undefined,
          documentDateTo: documentDateTo || undefined,
        }),
        listVendors(),
        listExpenseCategories(),
      ]);
      setDocuments(docs);
      setVendors(vendorList);
      setCategories(categoryList);

      // A fresh load supersedes any pending poll -- clear it before possibly
      // scheduling a new one below, so overlapping loads never double-poll.
      if (pollTimeoutRef.current) {
        clearTimeout(pollTimeoutRef.current);
        pollTimeoutRef.current = null;
      }
      if (docs.some((doc) => doc.status === "batch_queued")) {
        pollTimeoutRef.current = setTimeout(() => void loadAll(), BATCH_POLL_INTERVAL_MS);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar los documentos.");
    } finally {
      setLoading(false);
    }
  }, [documentDateFrom, documentDateTo]);

  useEffect(() => {
    void loadAll();
  }, [loadAll, refreshSignal]);

  useEffect(() => {
    return () => {
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);

  async function handleClassify(documentId: string, field: "vendorId" | "expenseCategoryId", value: string) {
    const current = documents.find((d) => d.id === documentId);
    if (!current) return;

    await classifyDocument(documentId, {
      vendorId: field === "vendorId" ? value : (current.vendor_id ?? undefined),
      expenseCategoryId: field === "expenseCategoryId" ? value : (current.expense_category_id ?? undefined),
    });
    await loadAll();
  }

  async function handleAddVendor() {
    if (!newVendorName.trim()) return;
    await createVendor(newVendorName.trim());
    setNewVendorName("");
    await loadAll();
  }

  async function handleAddCategory() {
    if (!newCategoryName.trim()) return;
    await createExpenseCategory(newCategoryName.trim());
    setNewCategoryName("");
    await loadAll();
  }

  async function handleRetry(doc: DocumentListItem) {
    setRetryingId(doc.id);
    setError(null);
    try {
      await reprocessWithAi(doc.id);
      await loadAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo reprocesar el documento.");
    } finally {
      setRetryingId(null);
    }
  }

  async function handlePreview(doc: DocumentListItem) {
    setPreviewingId(doc.id);
    setPreviewError(null);
    try {
      const blob = await fetchDocumentFile(doc.id);
      const url = URL.createObjectURL(blob);
      setPreview({ url, mimeType: blob.type, filename: doc.original_filename });
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : "No se pudo cargar la vista previa.");
    } finally {
      setPreviewingId(null);
    }
  }

  function closePreview() {
    if (preview) URL.revokeObjectURL(preview.url);
    setPreview(null);
  }

  async function handleDelete(doc: DocumentListItem) {
    const confirmed = window.confirm(
      `¿Eliminar "${doc.original_filename}"? Esta accion no se puede deshacer.`,
    );
    if (!confirmed) return;

    setDeletingId(doc.id);
    try {
      await deleteDocument(doc.id);
      await loadAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo eliminar el documento.");
    } finally {
      setDeletingId(null);
    }
  }

  if (loading && documents.length === 0) {
    return <p>Cargando documentos...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  return (
    <div>
      <div className="quick-add-row">
        <div className="quick-add">
          <input
            placeholder="Nuevo proveedor..."
            value={newVendorName}
            onChange={(e) => setNewVendorName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddVendor()}
          />
          <button onClick={handleAddVendor}>+ Proveedor</button>
        </div>
        <div className="quick-add">
          <input
            placeholder="Nueva categoria..."
            value={newCategoryName}
            onChange={(e) => setNewCategoryName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddCategory()}
          />
          <button onClick={handleAddCategory}>+ Categoria</button>
        </div>
        <div className="quick-add">
          <label>
            Fecha documento desde{" "}
            <input
              type="date"
              value={documentDateFrom}
              onChange={(e) => setDocumentDateFrom(e.target.value)}
            />
          </label>
          <label>
            hasta{" "}
            <input type="date" value={documentDateTo} onChange={(e) => setDocumentDateTo(e.target.value)} />
          </label>
          {(documentDateFrom || documentDateTo) && (
            <button
              onClick={() => {
                setDocumentDateFrom("");
                setDocumentDateTo("");
              }}
            >
              Limpiar
            </button>
          )}
        </div>
      </div>

      {previewError && <p className="error-text">{previewError}</p>}

      {documents.length === 0 ? (
        <p>Aun no has subido ningun documento.</p>
      ) : (
        <table className="documents-table">
          <thead>
            <tr>
              <th>Archivo</th>
              <th>Estado</th>
              <th>Confianza OCR</th>
              <th>Valor</th>
              <th>Fecha documento</th>
              <th>Proveedor</th>
              <th>Categoria</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.id}>
                <td>
                  <button
                    className="filename-link"
                    onClick={() => handlePreview(doc)}
                    disabled={previewingId === doc.id}
                  >
                    {previewingId === doc.id ? "Cargando..." : doc.original_filename}
                  </button>
                </td>
                <td>
                  <span className={`status-badge status-${doc.status}`}>
                    {STATUS_LABELS[doc.status] ?? doc.status}
                  </span>
                </td>
                <td>{doc.confidence_score != null ? `${doc.confidence_score.toFixed(0)}%` : "-"}</td>
                <td>{formatAmount(doc.total_amount, doc.currency)}</td>
                <td>{formatDocumentDate(doc.document_date)}</td>
                <td>
                  <select
                    value={doc.vendor_id ?? ""}
                    onChange={(e) => handleClassify(doc.id, "vendorId", e.target.value)}
                  >
                    <option value="">-- Sin proveedor --</option>
                    {vendors.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    value={doc.expense_category_id ?? ""}
                    onChange={(e) => handleClassify(doc.id, "expenseCategoryId", e.target.value)}
                  >
                    <option value="">-- Sin categoria --</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="row-actions">
                  {RETRYABLE_STATUSES.has(doc.status) && (
                    <button
                      className="retry-button"
                      onClick={() => handleRetry(doc)}
                      disabled={retryingId === doc.id}
                    >
                      {retryingId === doc.id ? "Procesando..." : "Reintentar"}
                    </button>
                  )}
                  <button
                    className="delete-button"
                    onClick={() => handleDelete(doc)}
                    disabled={deletingId === doc.id}
                  >
                    {deletingId === doc.id ? "Eliminando..." : "Eliminar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {preview && (
        <div className="preview-overlay" onClick={closePreview}>
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-modal-header">
              <span>{preview.filename}</span>
              <button onClick={closePreview}>Cerrar</button>
            </div>
            {preview.mimeType.startsWith("image/") ? (
              <img src={preview.url} alt={preview.filename} className="preview-image" />
            ) : (
              <iframe src={preview.url} title={preview.filename} className="preview-pdf" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
