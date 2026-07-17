export interface DocumentUploadResponse {
  id: string;
  status: string;
  original_filename: string;
  storage_path: string;
  company_id: string;
}

export interface DocumentListItem {
  id: string;
  original_filename: string;
  status: string;
  document_type: string | null;
  vendor_id: string | null;
  expense_category_id: string | null;
  confidence_score: number | null;
  created_at: string;
}

export interface DocumentExtractionRead {
  id: string;
  document_id: string;
  extraction_method: string;
  provider_name: string | null;
  raw_text: string | null;
  extracted_data: Record<string, unknown>;
  confidence_score: number | null;
  is_final: boolean;
}

export interface VendorRead {
  id: string;
  company_id: string;
  name: string;
  tax_id: string | null;
}

export interface ExpenseCategoryRead {
  id: string;
  company_id: string;
  name: string;
}

export interface ExpenseSummaryRow {
  document_id: string;
  document_date: string | null;
  vendor_id: string | null;
  vendor_name: string | null;
  expense_category_id: string | null;
  expense_category_name: string | null;
  currency: string | null;
  total_amount: number | null;
  tax_amount: number | null;
}

export interface ExpenseCategoryTotal {
  expense_category_id: string | null;
  expense_category_name: string;
  total_amount: number;
  document_count: number;
}

export interface VendorTotal {
  vendor_id: string | null;
  vendor_name: string;
  total_amount: number;
  document_count: number;
}

export interface ExpenseSummaryResponse {
  rows: ExpenseSummaryRow[];
  totals_by_category: ExpenseCategoryTotal[];
  totals_by_vendor: VendorTotal[];
  grand_total: number;
  document_count: number;
}
