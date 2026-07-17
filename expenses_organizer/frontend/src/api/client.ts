import type {
  DocumentExtractionRead,
  DocumentListItem,
  DocumentUploadResponse,
  ExpenseCategoryRead,
  ExpenseSummaryResponse,
  VendorRead,
} from "./types";
import { supabase } from "../lib/supabaseClient";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function authHeaders(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = { ...(await authHeaders()), ...(init?.headers ?? {}) };
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body; keep statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function buildQuery(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export async function uploadDocument(
  file: File,
  documentType?: string,
): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (documentType) formData.append("document_type", documentType);

  return request<DocumentUploadResponse>("/documents/upload", {
    method: "POST",
    body: formData,
  });
}

export async function processDocument(documentId: string): Promise<DocumentExtractionRead> {
  return request<DocumentExtractionRead>(`/documents/${documentId}/ocr`, { method: "POST" });
}

export async function reprocessWithAi(documentId: string): Promise<DocumentExtractionRead> {
  return request<DocumentExtractionRead>(`/documents/${documentId}/ai-extract`, { method: "POST" });
}

export async function listDocuments(filters: {
  vendorId?: string;
  expenseCategoryId?: string;
} = {}): Promise<DocumentListItem[]> {
  const query = buildQuery({
    vendor_id: filters.vendorId,
    expense_category_id: filters.expenseCategoryId,
  });
  return request<DocumentListItem[]>(`/documents${query}`);
}

export async function deleteDocument(documentId: string): Promise<void> {
  return request<void>(`/documents/${documentId}`, { method: "DELETE" });
}

export async function classifyDocument(
  documentId: string,
  fields: { vendorId?: string; expenseCategoryId?: string },
): Promise<DocumentListItem> {
  return request<DocumentListItem>(`/documents/${documentId}/classify`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vendor_id: fields.vendorId ?? null,
      expense_category_id: fields.expenseCategoryId ?? null,
    }),
  });
}

export async function listVendors(): Promise<VendorRead[]> {
  return request<VendorRead[]>("/vendors");
}

export async function createVendor(name: string, taxId?: string): Promise<VendorRead> {
  return request<VendorRead>("/vendors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, tax_id: taxId ?? null }),
  });
}

export async function listExpenseCategories(): Promise<ExpenseCategoryRead[]> {
  return request<ExpenseCategoryRead[]>("/expense-categories");
}

export async function createExpenseCategory(name: string): Promise<ExpenseCategoryRead> {
  return request<ExpenseCategoryRead>("/expense-categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function getExpenseSummary(filters: {
  vendorId?: string;
  expenseCategoryId?: string;
} = {}): Promise<ExpenseSummaryResponse> {
  const query = buildQuery({
    vendor_id: filters.vendorId,
    expense_category_id: filters.expenseCategoryId,
  });
  return request<ExpenseSummaryResponse>(`/reports/expense-summary${query}`);
}
