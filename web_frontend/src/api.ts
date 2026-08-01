import type {
  Annotation,
  AnnotationPayload,
  ClassInfo,
  DatasetMeta,
  DatasetStats,
  ImageItem,
  LockInfo,
  MaskCandidate,
  MaskReview,
  MaskReviewPayload,
  ValidationResult
} from "./types";

export class ApiError extends Error {
  detail: unknown;
  status: number;

  constructor(message: string, detail: unknown, status = 0) {
    super(message);
    this.name = "ApiError";
    this.detail = detail;
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...authHeaders(),
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    let detail = response.statusText;
    let rawDetail: unknown = detail;
    try {
      const text = await response.text();
      try {
        const data = JSON.parse(text);
        rawDetail = data.detail ?? data;
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      } catch {
        rawDetail = text || response.statusText;
        detail = text || response.statusText;
      }
    } catch {
      detail = response.statusText;
      rawDetail = detail;
    }
    throw new ApiError(detail || `HTTP ${response.status}`, rawDetail, response.status);
  }
  return response.json() as Promise<T>;
}

function storedAuthUser(): string {
  if (typeof localStorage === "undefined") return "";
  try {
    return (localStorage.getItem("aga_user") || "").trim();
  } catch {
    return "";
  }
}

function authHeaderValue(): string {
  const user = storedAuthUser();
  if (!user) return "";
  try {
    return encodeURIComponent(user);
  } catch {
    return "";
  }
}

function authHeaders(): Record<string, string> {
  const user = authHeaderValue();
  return user ? { "X-AGA-User": user } : {};
}

function uploadRequest<T>(path: string, form: FormData, onProgress?: (progress: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.withCredentials = true;
    const user = authHeaderValue();
    if (user) {
      xhr.setRequestHeader("X-AGA-User", user);
    }
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
  stats(datasetId: string) {
    return request<DatasetStats>(`/api/datasets/${datasetId}/stats`);
  },
  updateClasses(datasetId: string, classes: ClassInfo[]) {
    return request<DatasetMeta>(`/api/datasets/${datasetId}/classes`, {
      method: "PUT",
      body: JSON.stringify({ classes })
    });
  },
  images(datasetId: string, status = "all", offset = 0, limit = 320) {
    return request<{ items: ImageItem[]; total: number; offset: number; limit: number }>(
      `/api/datasets/${datasetId}/images?offset=${offset}&limit=${limit}&status=${encodeURIComponent(status)}`
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
  maskReview(datasetId: string, imageId: string) {
    return request<MaskReviewPayload>(`/api/datasets/${datasetId}/images/${imageId}/mask-review`);
  },
  generateMaskCandidate(datasetId: string, imageId: string, instanceId: number) {
    return request<MaskCandidate>(
      `/api/datasets/${datasetId}/images/${imageId}/objects/${instanceId}/mask-candidate`,
      { method: "POST" }
    );
  },
  saveMaskReview(
    datasetId: string,
    imageId: string,
    instanceId: number,
    payload: { candidate_id?: string | null; score: number; review_status?: string | null; failure_tags?: string[]; notes?: string }
  ) {
    return request<MaskReview>(
      `/api/datasets/${datasetId}/images/${imageId}/objects/${instanceId}/mask-review`,
      {
        method: "PUT",
        body: JSON.stringify(payload)
      }
    );
  },
  clearMaskReview(datasetId: string, imageId: string, instanceId: number) {
    return request<{ cleared: boolean; instance_id: number }>(
      `/api/datasets/${datasetId}/images/${imageId}/objects/${instanceId}/mask-review`,
      { method: "DELETE" }
    );
  },
  maskPreviewUrl(datasetId: string, imageId: string, instanceId: number) {
    return `/api/datasets/${datasetId}/images/${imageId}/objects/${instanceId}/mask-candidate/preview`;
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
  exportDataset(datasetId: string, exportType: "yolo" | "yolo_angle" | "obb_teacher") {
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
