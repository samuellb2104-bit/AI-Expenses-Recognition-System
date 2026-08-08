import { useCallback, useEffect, useState } from "react";
import { ApiError, listVendors } from "../api/client";
import type { VendorRead } from "../api/types";

interface VendorsViewProps {
  refreshSignal: number;
  onSelectVendor: (vendorId: string) => void;
}

export function VendorsView({ refreshSignal, onSelectVendor }: VendorsViewProps) {
  const [vendors, setVendors] = useState<VendorRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadVendors = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setVendors(await listVendors());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar los proveedores.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadVendors();
  }, [loadVendors, refreshSignal]);

  if (loading && vendors.length === 0) {
    return <p>Cargando proveedores...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  if (vendors.length === 0) {
    return <p>Aun no hay proveedores registrados.</p>;
  }

  return (
    <table className="vendors-table">
      <thead>
        <tr>
          <th>Proveedor</th>
          <th>Documentos</th>
        </tr>
      </thead>
      <tbody>
        {vendors.map((vendor) => (
          <tr key={vendor.id} className="vendor-row" onClick={() => onSelectVendor(vendor.id)}>
            <td>{vendor.name}</td>
            <td>{vendor.document_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
