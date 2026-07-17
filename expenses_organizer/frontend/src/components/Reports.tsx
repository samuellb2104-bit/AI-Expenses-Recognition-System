import { useCallback, useEffect, useState } from "react";
import { ApiError, getExpenseSummary } from "../api/client";
import type { ExpenseSummaryResponse } from "../api/types";

interface ReportsProps {
  refreshSignal: number;
}

export function Reports({ refreshSignal }: ReportsProps) {
  const [summary, setSummary] = useState<ExpenseSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getExpenseSummary();
      setSummary(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar los reportes.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll, refreshSignal]);

  if (loading && !summary) {
    return <p>Cargando reportes...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  if (!summary) {
    return null;
  }

  const maxCategoryTotal = Math.max(1, ...summary.totals_by_category.map((c) => c.total_amount));
  const maxVendorTotal = Math.max(1, ...summary.totals_by_vendor.map((v) => v.total_amount));

  return (
    <div>
      <div className="summary-cards">
        <div className="summary-card">
          <span className="summary-card-label">Total gastado</span>
          <span className="summary-card-value">${summary.grand_total.toLocaleString()}</span>
        </div>
        <div className="summary-card">
          <span className="summary-card-label">Documentos</span>
          <span className="summary-card-value">{summary.document_count}</span>
        </div>
      </div>

      <h3>Por categoria</h3>
      {summary.totals_by_category.length === 0 ? (
        <p>Aun no hay gastos categorizados.</p>
      ) : (
        <div className="bar-chart">
          {summary.totals_by_category.map((c) => (
            <div className="bar-row" key={c.expense_category_id ?? "none"}>
              <span className="bar-label">{c.expense_category_name}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(c.total_amount / maxCategoryTotal) * 100}%` }} />
              </div>
              <span className="bar-value">
                ${c.total_amount.toLocaleString()} ({c.document_count})
              </span>
            </div>
          ))}
        </div>
      )}

      <h3>Por proveedor</h3>
      {summary.totals_by_vendor.length === 0 ? (
        <p>Aun no hay gastos con proveedor asignado.</p>
      ) : (
        <div className="bar-chart">
          {summary.totals_by_vendor.map((v) => (
            <div className="bar-row" key={v.vendor_id ?? "none"}>
              <span className="bar-label">{v.vendor_name}</span>
              <div className="bar-track">
                <div className="bar-fill bar-fill-vendor" style={{ width: `${(v.total_amount / maxVendorTotal) * 100}%` }} />
              </div>
              <span className="bar-value">
                ${v.total_amount.toLocaleString()} ({v.document_count})
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
