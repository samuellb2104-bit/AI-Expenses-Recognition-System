import { useRef, useState } from "react";
import { ApiError, reprocessWithAi, submitBatchExtraction, uploadDocument } from "../api/client";

type FileStage = "queued" | "uploading" | "processing" | "batched" | "done" | "error";

interface UploadItem {
  key: string;
  file: File;
  stage: FileStage;
  message: string | null;
  documentId?: string;
}

const STAGE_LABELS: Record<FileStage, string> = {
  queued: "En cola...",
  uploading: "Subiendo...",
  processing: "Procesando (IA)...",
  batched: "Enviado en lote -- revisa la tabla",
  done: "Listo",
  error: "Error",
};

const MAX_CONCURRENT = 3;

// Below this many files, each one is processed synchronously (fast, seconds-scale
// feedback). At/above it, all files are uploaded and then submitted as a single
// Anthropic Message Batch (results land minutes later, but avoids running that many
// concurrent Claude calls against this single-worker backend). Tunable.
const BATCH_EXTRACTION_THRESHOLD = 10;

interface UploadDocumentProps {
  onProcessed: () => void;
}

function isAcceptedFile(file: File): boolean {
  return file.type === "application/pdf" || file.type.startsWith("image/");
}

export function UploadDocument({ onProcessed }: UploadDocumentProps) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [skippedNote, setSkippedNote] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  function updateItem(key: string, patch: Partial<UploadItem>) {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  }

  async function processOne(item: UploadItem) {
    updateItem(item.key, { stage: "uploading", message: null });
    try {
      const uploaded = await uploadDocument(item.file);
      updateItem(item.key, { stage: "processing" });

      // OCR no longer runs as part of the default flow -- Claude alone produces every
      // field the app depends on, and skipping local Tesseract keeps this fast and
      // light on the backend. OCR is still reachable manually if ever needed.
      const extraction = await reprocessWithAi(uploaded.id);
      const vendor = (extraction.extracted_data.vendor_name as string | undefined) ?? "sin proveedor detectado";
      const total = extraction.extracted_data.total_amount;
      updateItem(item.key, {
        stage: "done",
        message: `${vendor}${total ? ` - $${total}` : ""}`,
      });
    } catch (error) {
      updateItem(item.key, {
        stage: "error",
        message: error instanceof ApiError ? error.message : "Error inesperado al subir el documento.",
      });
    } finally {
      // Refresh the documents table after every file (success or failure) rather than
      // only at batch-end -- a single file can take a couple seconds, and for
      // folder-sized batches waiting for the whole batch to settle before anything
      // shows up would feel broken.
      onProcessed();
    }
  }

  async function runQueue(newItems: UploadItem[]) {
    let cursor = 0;
    async function worker() {
      while (cursor < newItems.length) {
        const item = newItems[cursor++];
        await processOne(item);
      }
    }
    await Promise.allSettled(Array.from({ length: MAX_CONCURRENT }, () => worker()));
  }

  async function uploadOnly(item: UploadItem): Promise<string | null> {
    updateItem(item.key, { stage: "uploading", message: null });
    try {
      const uploaded = await uploadDocument(item.file);
      updateItem(item.key, { stage: "batched", documentId: uploaded.id });
      onProcessed();
      return uploaded.id;
    } catch (error) {
      updateItem(item.key, {
        stage: "error",
        message: error instanceof ApiError ? error.message : "Error inesperado al subir el documento.",
      });
      return null;
    }
  }

  async function runBatchQueue(newItems: UploadItem[]) {
    let cursor = 0;
    const uploadedIds: string[] = [];
    async function worker() {
      while (cursor < newItems.length) {
        const item = newItems[cursor++];
        const documentId = await uploadOnly(item);
        if (documentId) uploadedIds.push(documentId);
      }
    }
    await Promise.allSettled(Array.from({ length: MAX_CONCURRENT }, () => worker()));

    if (uploadedIds.length === 0) return;

    try {
      await submitBatchExtraction(uploadedIds);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Error inesperado al enviar el lote a procesar.";
      setItems((prev) =>
        prev.map((item) =>
          uploadedIds.includes(item.documentId ?? "") ? { ...item, stage: "error", message } : item,
        ),
      );
    } finally {
      onProcessed();
    }
  }

  function enqueueFiles(files: File[]) {
    const accepted = files.filter(isAcceptedFile);
    const skipped = files.length - accepted.length;
    setSkippedNote(skipped > 0 ? `${skipped} archivo(s) omitido(s) (tipo no soportado)` : null);

    if (accepted.length === 0) return;

    const newItems: UploadItem[] = accepted.map((file) => ({
      key: crypto.randomUUID(),
      file,
      stage: "queued",
      message: null,
    }));
    setItems((prev) => [...prev, ...newItems]);

    if (newItems.length >= BATCH_EXTRACTION_THRESHOLD) {
      void runBatchQueue(newItems);
    } else {
      void runQueue(newItems);
    }
  }

  async function collectEntries(entry: FileSystemEntry): Promise<File[]> {
    if (entry.isFile) {
      return new Promise((resolve) => {
        (entry as FileSystemFileEntry).file(
          (file) => resolve([file]),
          () => resolve([]),
        );
      });
    }
    if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      const allEntries: FileSystemEntry[] = [];
      // A single readEntries() call can silently truncate large directories (browsers
      // cap entries per call) -- must keep calling until it returns an empty batch.
      for (;;) {
        const batch: FileSystemEntry[] = await new Promise((resolve) => {
          reader.readEntries(resolve, () => resolve([]));
        });
        if (batch.length === 0) break;
        allEntries.push(...batch);
      }
      const nested = await Promise.all(allEntries.map(collectEntries));
      return nested.flat();
    }
    return [];
  }

  async function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);

    const dtItems = event.dataTransfer.items;
    let files: File[];

    if (dtItems && dtItems.length > 0 && typeof dtItems[0].webkitGetAsEntry === "function") {
      const entries = Array.from(dtItems)
        .map((item) => item.webkitGetAsEntry())
        .filter((entry): entry is FileSystemEntry => entry !== null);
      files = (await Promise.all(entries.map(collectEntries))).flat();
    } else {
      files = Array.from(event.dataTransfer.files ?? []);
    }

    enqueueFiles(files);
  }

  function onFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    enqueueFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  function onFolderSelected(event: React.ChangeEvent<HTMLInputElement>) {
    enqueueFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  const busy = items.some((item) => item.stage === "uploading" || item.stage === "processing");

  return (
    <div className="upload-card">
      <div
        className={`dropzone ${isDragging ? "dropzone-active" : ""} ${busy ? "dropzone-busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,image/*"
          multiple
          hidden
          onChange={onFileSelected}
        />
        <p>
          Arrastra una o varias facturas/recibos (PDF o imagen), o una carpeta completa, aqui — o haz clic
          para elegir archivos
        </p>
      </div>

      <div className="upload-actions">
        <input
          ref={folderInputRef}
          type="file"
          hidden
          multiple
          onChange={onFolderSelected}
          {...({ webkitdirectory: "true" } as unknown as React.InputHTMLAttributes<HTMLInputElement>)}
        />
        <button type="button" onClick={() => folderInputRef.current?.click()}>
          Subir carpeta
        </button>
      </div>

      {skippedNote && <p className="upload-message">{skippedNote}</p>}

      {items.length > 0 && (
        <ul className="upload-queue">
          {items.map((item) => (
            <li key={item.key} className={`upload-item upload-item-${item.stage}`}>
              <span className="upload-item-name">{item.file.name}</span>
              <span className="upload-item-message">{item.message ?? STAGE_LABELS[item.stage]}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
