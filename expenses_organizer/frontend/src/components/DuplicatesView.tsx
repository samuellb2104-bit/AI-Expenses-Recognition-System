import { useEffect, useState } from "react";
import { Loader } from "./Brand";
import {
  ApiError,
  deleteDocument,
  dismissDuplicateGroup,
  fetchDocumentFile,
  getProbableDuplicates,
} from "../api/client";
import type { DuplicateDocument, DuplicateGroup, DuplicateReviewResponse } from "../api/types";

interface DuplicatesViewProps {
  onChanged: () => void;
}

function formatAmount(amount: number, currency: string | null): string {
  const formatted = amount.toLocaleString("es-CO", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  return currency ? `${currency} ${formatted}` : formatted;
}

function groupKey(group: DuplicateGroup): string {
  return group.documents.map((d) => d.id).join("-");
}

export function DuplicatesView({ onChanged }: DuplicatesViewProps) {
  const [result, setResult] = useState<DuplicateReviewResponse | null>(null);
  const [dateWindowDays, setDateWindowDays] = useState(5);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [dismissingKey, setDismissingKey] = useState<string | null>(null);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; mimeType: string; filename: string } | null>(null);

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);

  async function scan() {
    setScanning(true);
    setError(null);
    try {
      setResult(await getProbableDuplicates(dateWindowDays));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo revisar los duplicados.");
    } finally {
      setScanning(false);
    }
  }

  async function handlePreview(doc: DuplicateDocument) {
    setPreviewingId(doc.id);
    setError(null);
    try {
      const blob = await fetchDocumentFile(doc.id);
      setPreview({ url: URL.createObjectURL(blob), mimeType: blob.type, filename: doc.original_filename });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cargar la vista previa.");
    } finally {
      setPreviewingId(null);
    }
  }

  function closePreview() {
    if (preview) URL.revokeObjectURL(preview.url);
    setPreview(null);
  }

  async function handleDelete(doc: DuplicateDocument) {
    const confirmed = window.confirm(
      `¿Eliminar "${doc.original_filename}"? Esta accion no se puede deshacer.`,
    );
    if (!confirmed) return;

    setDeletingId(doc.id);
    setError(null);
    try {
      await deleteDocument(doc.id);
      onChanged();
      await scan();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo eliminar el documento.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDismiss(group: DuplicateGroup) {
    const key = groupKey(group);
    setDismissingKey(key);
    setError(null);
    try {
      await dismissDuplicateGroup(group.documents.map((d) => d.id));
      // Drop the group locally instead of rescanning: the rest of the list (and the
      // user's scroll position) stays exactly as it was.
      setResult((current) =>
        current ? { ...current, groups: current.groups.filter((g) => groupKey(g) !== key) } : current,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo marcar el grupo como no duplicado.");
    } finally {
      setDismissingKey(null);
    }
  }

  const totalOvercount = result?.groups.reduce((sum, g) => sum + g.possible_overcount, 0) ?? 0;

  return (
    <div>
      <div className="duplicates-toolbar">
        <button onClick={scan} disabled={scanning}>
          {scanning ? "Revisando..." : "Revisar duplicados"}
        </button>
        <label>
          Diferencia maxima de fechas{" "}
          <input
            type="number"
            min={0}
            max={30}
            value={dateWindowDays}
            onChange={(e) => setDateWindowDays(Math.min(30, Math.max(0, Number(e.target.value) || 0)))}
            style={{ width: "4em" }}
          />{" "}
          dias
        </label>
      </div>

      <p className="duplicate-reasons">
        Busca documentos con el mismo valor y moneda, proveedor igual o similar y fechas cercanas
        (por ejemplo, una factura y su comprobante de pago).
      </p>

      {error && <p className="error-text">{error}</p>}

      {scanning && <Loader label="Buscando egresos duplicados..." />}

      {result && result.groups.length === 0 && (
        <p>
          No se encontraron posibles duplicados entre {result.scanned_document_count} documentos con valor.
        </p>
      )}

      {result && result.groups.length > 0 && (
        <>
          <div className="summary-cards">
            <div className="summary-card">
              <span className="summary-card-label">Grupos sospechosos</span>
              <span className="summary-card-value">{result.groups.length}</span>
            </div>
            <div className="summary-card">
              <span className="summary-card-label">Posible monto contado de mas</span>
              <span className="summary-card-value">${totalOvercount.toLocaleString("es-CO")}</span>
            </div>
          </div>

          {result.groups.map((group) => (
            <div className="duplicate-group" key={groupKey(group)}>
              <div className="duplicate-group-header">
                <strong>{formatAmount(group.total_amount, group.currency)}</strong>
                <span className={`confidence-badge confidence-${group.confidence}`}>
                  Coincidencia {group.confidence}
                </span>
                <button onClick={() => handleDismiss(group)} disabled={dismissingKey === groupKey(group)}>
                  {dismissingKey === groupKey(group) ? "Guardando..." : "No es duplicado"}
                </button>
              </div>
              <p className="duplicate-reasons">{group.reasons.join(" · ")}</p>

              <div className="table-scroll">
<table className="documents-table">
                <thead>
                  <tr>
                    <th>Archivo</th>
                    <th>Proveedor</th>
                    <th>Fecha documento</th>
                    <th>Subido</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {group.documents.map((doc) => (
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
                      <td>{doc.vendor_name ?? "-"}</td>
                      <td>{doc.document_date ?? "-"}</td>
                      <td>{new Date(doc.created_at).toLocaleDateString("es-CO")}</td>
                      <td className="row-actions">
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
</div>
            </div>
          ))}
        </>
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
