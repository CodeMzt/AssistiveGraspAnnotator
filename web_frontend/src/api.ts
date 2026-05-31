import type { Annotation, AnnotationPayload, ClassInfo, DatasetMeta, ImageItem, LockInfo, ValidationResult } from "./types";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function uploadRequest<T>(path: string, form: FormData, onProgress?: (progress: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return;
      onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let data: unknown = {};
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : {};
      } catch {
        data = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve(data as T);
        return;
      }
      const detail =
        typeof data === "object" && data && "detail" in data
          ? typeof (data as { detail: unknown }).detail === "string"
            ? (data as { detail: string }).detail
            : JSON.stringify((data as { detail: unknown }).detail)
          : String(data || xhr.statusText || `HTTP ${xhr.status}`);
      reject(new Error(detail));
    };
    xhr.onerror = () => reject(new Error("Upload failed due to a network error."));
    xhr.send(form);
  });
}

export const api = {
  login(username: string) {
    return request<{ username: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ username })
    });
  },
  roots() {
    return request<{ roots: { path: string; name: string }[]; datasets: DatasetMeta[] }>("/api/roots");
  },
  datasets() {
    return request<{ datasets: DatasetMeta[] }>("/api/datasets");
  },
  createDataset(name: string, classes: ClassInfo[] = []) {
    return request<DatasetMeta>("/api/datasets", {
      method: "POST",
      body: JSON.stringify({ name, classes })
    });
  },
  openDataset(path: string) {
    return request<DatasetMeta>("/api/datasets/open", {
      method: "POST",
      body: JSON.stringify({ path })
    });
  },
  renameDataset(datasetId: string, name: string) {
    return request<DatasetMeta>(`/api/datasets/${datasetId}`, {
      method: "PATCH",
      body: JSON.stringify({ name })
    });
  },
  deleteDataset(datasetId: string) {
    return request<{ deleted: { dataset_id: string; name: string; root: string; trash_path: string | null } }>(
      `/api/datasets/${datasetId}`,
      { method: "DELETE" }
    );
  },
  uploadDataset(form: FormData, onProgress?: (progress: number) => void) {
    return uploadRequest<DatasetMeta>("/api/datasets/upload", form, onProgress);
  },
  uploadImages(datasetId: string, form: FormData, onProgress?: (progress: number) => void) {
    return uploadRequest<{ added: number; dataset: DatasetMeta }>(
      `/api/datasets/${datasetId}/images/upload`,
      form,
      onProgress
    );
  },
  uploadChunk(form: FormData, onProgress?: (progress: number) => void) {
    return uploadRequest<{ received: boolean; chunk_index: number; total_chunks: number }>("/api/uploads/chunk", form, onProgress);
  },
  completeChunkedDatasetUpload(payload: {
    session_id: string;
    upload_batch_id: string;
    name: string;
    camera_name: string;
    classes: ClassInfo[];
    files: { file_id: string; filename: string; size: number }[];
  }) {
    return request<DatasetMeta>("/api/datasets/upload-chunked/complete", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  completeChunkedImageUpload(
    datasetId: string,
    payload: {
      session_id: string;
      upload_batch_id: string;
      files: { file_id: string; filename: string; size: number }[];
    }
  ) {
    return request<{ added: number; dataset: DatasetMeta }>(
      `/api/datasets/${datasetId}/images/upload-chunked/complete`,
      {
        method: "POST",
        body: JSON.stringify(payload)
      }
    );
  },
  dataset(datasetId: string) {
    return request<DatasetMeta>(`/api/datasets/${datasetId}`);
  },
  updateClasses(datasetId: string, classes: ClassInfo[]) {
    return request<DatasetMeta>(`/api/datasets/${datasetId}/classes`, {
      method: "PUT",
      body: JSON.stringify({ classes })
    });
  },
  images(datasetId: string, status = "all") {
    return request<{ items: ImageItem[]; total: number }>(
      `/api/datasets/${datasetId}/images?limit=500&status=${encodeURIComponent(status)}`
    );
  },
  annotation(datasetId: string, imageId: string) {
    return request<AnnotationPayload>(`/api/datasets/${datasetId}/images/${imageId}/annotation`);
  },
  deleteImage(datasetId: string, imageId: string) {
    return request<{ deleted: { image_id: string; image_key: string; trash_image_path: string; trash_annotation_path: string | null }; dataset: DatasetMeta }>(
      `/api/datasets/${datasetId}/images/${imageId}`,
      { method: "DELETE" }
    );
  },
  lock(datasetId: string, imageId: string) {
    return request<LockInfo & { lock_token: string }>(`/api/datasets/${datasetId}/images/${imageId}/lock`, {
      method: "POST"
    });
  },
  heartbeat(lockId: string, lockToken: string) {
    return request<LockInfo & { lock_token: string }>(`/api/locks/${lockId}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({ lock_token: lockToken })
    });
  },
  releaseLock(lockId: string, lockToken: string) {
    return request<{ released: boolean }>(`/api/locks/${lockId}`, {
      method: "DELETE",
      body: JSON.stringify({ lock_token: lockToken })
    });
  },
  saveAnnotation(datasetId: string, imageId: string, annotation: Annotation, etag: string, lock: LockInfo) {
    return request<AnnotationPayload>(`/api/datasets/${datasetId}/images/${imageId}/annotation`, {
      method: "PUT",
      body: JSON.stringify({
        lock_id: lock.lock_id,
        lock_token: lock.lock_token,
        etag,
        annotation
      })
    });
  },
  validate(datasetId: string, imageId?: string) {
    return request<ValidationResult>(
      `/api/datasets/${datasetId}/validate`,
      {
        method: "POST",
        body: JSON.stringify({ image_id: imageId || null })
      }
    );
  },
  exportDataset(datasetId: string, exportType: "yolo" | "grasp_roi" | "target_maps") {
    return request<{ id: string; status: string }>(`/api/datasets/${datasetId}/exports`, {
      method: "POST",
      body: JSON.stringify({ export_type: exportType })
    });
  },
  job(jobId: string) {
    return request<{ id: string; status: string; message: string; result: Record<string, unknown> }>(
      `/api/jobs/${jobId}`
    );
  }
};
