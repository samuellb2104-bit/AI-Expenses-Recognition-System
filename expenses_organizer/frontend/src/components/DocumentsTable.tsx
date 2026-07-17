import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  classifyDocument,
  createExpenseCategory,
  createVendor,
  deleteDocument,
  listDocuments,
  listExpenseCategories,
  listVendors,
} from "../api/client";
import type { DocumentListItem, ExpenseCategoryRead, VendorRead } from "../api/types";

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Subido",
  ocr_failed: "OCR fallo",
  ocr_completed: "Procesado (OCR)",
  ai_extraction_completed: "Procesado (IA)",
  needs_review: "Revisar",
};

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

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docs, vendorList, categoryList] = await Promise.all([
        listDocuments(),
        listVendors(),
        listExpenseCategories(),
      ]);
      setDocuments(docs);
      setVendors(vendorList);
      setCategories(categoryList);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar los documentos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll, refreshSignal]);

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
      </div>

      {documents.length === 0 ? (
        <p>Aun no has subido ningun documento.</p>
      ) : (
        <table className="documents-table">
          <thead>
            <tr>
              <th>Archivo</th>
              <th>Estado</th>
              <th>Confianza OCR</th>
              <th>Proveedor</th>
              <th>Categoria</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.original_filename}</td>
                <td>
                  <span className={`status-badge status-${doc.status}`}>
                    {STATUS_LABELS[doc.status] ?? doc.status}
                  </span>
                </td>
                <td>{doc.confidence_score != null ? `${doc.confidence_score.toFixed(0)}%` : "-"}</td>
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
                <td>
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
    </div>
  );
}
