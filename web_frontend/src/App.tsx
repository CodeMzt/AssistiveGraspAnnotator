import { useEffect, useReducer, useRef, useState } from "react";
import { Lock } from "lucide-react";
import { api } from "./api";
import { annotationReducer, firstClass } from "./annotationReducer";
import { AnnotationCanvas } from "./Canvas";
import { DatasetPanel } from "./components/DatasetPanel";
import { SidePanel } from "./components/SidePanel";
import { Toolbar } from "./components/Toolbar";
import type {
  Annotation,
  AnnotationAction,
  AnnotationPayload,
  CanvasSelection,
  ClassInfo,
  DatasetMeta,
  GraspAnnotation,
  ImageItem,
  LockInfo,
  Mode,
  ValidationMessage
} from "./types";

const DEFAULT_CLASSES: ClassInfo[] = [{ id: 0, name: "object", graspable: true, policy: "grasp_rect" }];
const UPLOAD_CHUNK_SIZE = 960 * 1024;
const DEFAULT_UPLOAD_CONCURRENCY = 18;

function clampUploadConcurrency(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_UPLOAD_CONCURRENCY;
  return Math.max(1, Math.min(32, Math.round(value)));
}

function initialUploadConcurrency(): number {
  const stored = localStorage.getItem("aga_upload_concurrency");
  return stored ? clampUploadConcurrency(Number(stored)) : DEFAULT_UPLOAD_CONCURRENCY;
}

function autoUploadDatasetName(files: File[]): string {
  const firstPath = ((files[0] as File & { webkitRelativePath?: string })?.webkitRelativePath || files[0]?.name || "").trim();
  const folderName = firstPath.includes("/") ? firstPath.split("/")[0] : "";
  const base = folderName || `upload_${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "_")}`;
  return base.replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^[._]+|[._]+$/g, "") || "uploaded_dataset";
}

function newUploadBatchId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `upload_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function uploadFileId(file: File, index: number): string {
  const safeName = file.name.replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 80);
  return `f_${index}_${file.size}_${file.lastModified}_${safeName}`;
}

async function runLimitedConcurrency<T>(items: T[], limit: number, worker: (item: T) => Promise<void>) {
  let nextIndex = 0;
  const workerCount = Math.min(limit, items.length);
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (nextIndex < items.length) {
        const item = items[nextIndex];
        nextIndex += 1;
        await worker(item);
      }
    })
  );
}

type AnnotationState = {
  payload: AnnotationPayload | null;
};

type AnnotationStateAction =
  | { type: "setPayload"; payload: AnnotationPayload | null }
  | { type: "annotation"; action: AnnotationAction };

function annotationStateReducer(state: AnnotationState, action: AnnotationStateAction): AnnotationState {
  if (action.type === "setPayload") return { payload: action.payload };
  if (!state.payload) return state;
  return {
    payload: {
      ...state.payload,
      annotation: annotationReducer(state.payload.annotation, action.action)
    }
  };
}

export function App() {
  const [username, setUsername] = useState(localStorage.getItem("aga_user") || "");
  const [loggedIn, setLoggedIn] = useState(Boolean(localStorage.getItem("aga_user")));
  const [datasetList, setDatasetList] = useState<DatasetMeta[]>([]);
  const [newDatasetName, setNewDatasetName] = useState("new_dataset");
  const [dataset, setDataset] = useState<DatasetMeta | null>(null);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [imageStatus, setImageStatus] = useState("all");
  const [selectedImage, setSelectedImage] = useState<ImageItem | null>(null);
  const [annotationState, dispatchAnnotationState] = useReducer(annotationStateReducer, { payload: null });
  const [mode, setMode] = useState<Mode>("select");
  const [selection, setSelection] = useState<CanvasSelection>({ objectId: null, graspId: null, handle: null });
  const [lock, setLock] = useState<LockInfo | null>(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [statusLine, setStatusLine] = useState("");
  const [validationErrors, setValidationErrors] = useState<ValidationMessage[]>([]);
  const [validationWarnings, setValidationWarnings] = useState<ValidationMessage[]>([]);
  const [jobMessage, setJobMessage] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadBatchId, setUploadBatchId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadConcurrency, setUploadConcurrency] = useState(initialUploadConcurrency);
  const uploadingRef = useRef(false);

  const payload = annotationState.payload;
  const annotation = payload?.annotation || null;
  const editable = Boolean(lock?.lock_token && annotation);
  const imageUrl = dataset && selectedImage ? `/api/datasets/${dataset.dataset_id}/images/${selectedImage.image_id}/file` : "";
  const lockedBy = payload?.lock?.user || null;

  useEffect(() => {
    if (!loggedIn) return;
    void loadDatasetCatalog();
  }, [loggedIn]);

  useEffect(() => {
    if (!lock?.lock_token) return;
    const timer = window.setInterval(() => {
      api.heartbeat(lock.lock_id, lock.lock_token || "").catch(() => {
        setLock(null);
        setError("Edit lock expired. Reacquire the lock before saving.");
      });
    }, 30000);
    return () => window.clearInterval(timer);
  }, [lock?.lock_id, lock?.lock_token]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement | null)?.matches("input, textarea, select")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveCurrent();
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
      }
      if (event.key.toLowerCase() === "n" || event.key === "ArrowRight") {
        event.preventDefault();
        void selectAdjacentImage(1);
      }
      if (event.key.toLowerCase() === "p" || event.key === "ArrowLeft") {
        event.preventDefault();
        void selectAdjacentImage(-1);
      }
      if (event.key === "1") updateSelectedDifficulty("easy");
      if (event.key === "2") updateSelectedDifficulty("medium");
      if (event.key === "3") updateSelectedDifficulty("hard");
      if (event.key === "4") updateSelectedDifficulty("invalid");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [annotation, selection, editable]);

  function setPayload(next: AnnotationPayload | null) {
    dispatchAnnotationState({ type: "setPayload", payload: next });
  }

  function dispatchAnnotation(action: AnnotationAction) {
    if (!editable) return;
    dispatchAnnotationState({ type: "annotation", action });
    setDirty(true);
    setStatusLine("Unsaved");
  }

  function handleUploadFilesChange(files: File[]) {
    setUploadFiles(files);
    setUploadBatchId(files.length ? newUploadBatchId() : "");
    setUploadProgress(0);
    setUploadMessage("");
  }

  function handleUploadConcurrencyChange(value: number) {
    const next = clampUploadConcurrency(value);
    setUploadConcurrency(next);
    localStorage.setItem("aga_upload_concurrency", String(next));
  }

  async function login() {
    const user = username.trim();
    if (!user) return;
    await api.login(user);
    localStorage.setItem("aga_user", user);
    setLoggedIn(true);
  }

  async function releaseCurrentLock() {
    if (lock?.lock_token) {
      await api.releaseLock(lock.lock_id, lock.lock_token).catch(() => undefined);
    }
    setLock(null);
  }

  async function loadDatasetCatalog() {
    try {
      const data = await api.datasets();
      setDatasetList(data.datasets);
      if (dataset) {
        const latest = data.datasets.find((item) => item.dataset_id === dataset.dataset_id);
        if (latest) setDataset(latest);
      }
    } catch (exc) {
      setError(String((exc as Error).message || exc));
    }
  }

  async function saveCurrent(): Promise<boolean> {
    if (!dataset || !selectedImage || !payload || !lock) return true;
    try {
      const saved = await api.saveAnnotation(dataset.dataset_id, selectedImage.image_id, payload.annotation, payload.etag, lock);
      setPayload(saved);
      setDirty(false);
      setLock(null);
      setValidationErrors(saved.validation?.errors || []);
      setValidationWarnings(saved.validation?.warnings || []);
      setStatusLine("Saved");
      await loadImages();
      return true;
    } catch (exc) {
      setError(String((exc as Error).message || exc));
      return false;
    }
  }

  async function ensureCleanBeforeSwitch(): Promise<boolean> {
    if (!dirty) return true;
    if (!editable || !lock) {
      setError("Current image has unsaved changes. Save or release them before switching.");
      return false;
    }
    const wantsSave = window.confirm("Save current annotation before switching?");
    if (!wantsSave) return false;
    return saveCurrent();
  }

  async function loadImages(meta = dataset, status = imageStatus) {
    if (!meta) return;
    const data = await api.images(meta.dataset_id, status);
    setImages(data.items);
  }

  async function selectDataset(datasetId: string) {
    if (!(await ensureCleanBeforeSwitch())) return;
    const nextMeta = datasetList.find((item) => item.dataset_id === datasetId) || (await api.dataset(datasetId));
    if (nextMeta.missing) {
      setError("This dataset path is missing on disk. Delete it from the dataset list or restore the folder.");
      return;
    }
    setError("");
    await releaseCurrentLock();
    const meta = await api.dataset(datasetId);
    setDataset(meta);
    setSelectedImage(null);
    setPayload(null);
    setSelection({ objectId: null, graspId: null, handle: null });
    setValidationErrors([]);
    setValidationWarnings([]);
    setDirty(false);
    await loadImages(meta);
  }

  async function createDataset() {
    if (!(await ensureCleanBeforeSwitch())) return;
    const name = newDatasetName.trim();
    if (!name) return;
    setError("");
    await releaseCurrentLock();
    try {
      const meta = await api.createDataset(name, DEFAULT_CLASSES);
      setDataset(meta);
      setSelectedImage(null);
      setPayload(null);
      setSelection({ objectId: null, graspId: null, handle: null });
      setDirty(false);
      setImages([]);
      setNewDatasetName("new_dataset");
      await loadDatasetCatalog();
      setStatusLine(`Created ${meta.name}`);
    } catch (exc) {
      setError(String((exc as Error).message || exc));
    }
  }

  async function renameDataset(name: string) {
    if (!dataset) return;
    const nextName = name.trim();
    if (!nextName || nextName === dataset.name) return;
    setError("");
    try {
      const meta = await api.renameDataset(dataset.dataset_id, nextName);
      setDataset(meta);
      setDatasetList((current) => current.map((item) => (item.dataset_id === meta.dataset_id ? meta : item)));
      setStatusLine(`Renamed to ${meta.name}`);
    } catch (exc) {
      setError(String((exc as Error).message || exc));
    }
  }

  async function deleteDataset() {
    if (!dataset) return;
    if (!(await ensureCleanBeforeSwitch())) return;
    const ok = window.confirm(`Delete dataset "${dataset.name}"? The folder will be moved to .aga_trash when possible.`);
    if (!ok) return;
    setError("");
    try {
      await releaseCurrentLock();
      const deletedName = dataset.name;
      await api.deleteDataset(dataset.dataset_id);
      setDataset(null);
      setSelectedImage(null);
      setPayload(null);
      setImages([]);
      setSelection({ objectId: null, graspId: null, handle: null });
      setDirty(false);
      await loadDatasetCatalog();
      setStatusLine(`Deleted ${deletedName}`);
    } catch (exc) {
      setError(String((exc as Error).message || exc));
    }
  }

  async function uploadDataset() {
    if (!uploadFiles.length || uploadingRef.current) return;
    if (!(await ensureCleanBeforeSwitch())) return;
    setError("");
    uploadingRef.current = true;
    setUploading(true);
    setUploadProgress(0);
    setUploadMessage(`Uploading 0% (${uploadFiles.length} image(s))`);
    await releaseCurrentLock();
    const batchId = uploadBatchId || newUploadBatchId();
    const sessionId = batchId;
    const requestedConcurrency = uploadConcurrency;
    const fileRefs = uploadFiles.map((file, index) => ({
      file,
      file_id: uploadFileId(file, index),
      filename: file.name,
      size: file.size
    }));
    const totalBytes = Math.max(1, uploadFiles.reduce((sum, file) => sum + file.size, 0));
    let meta: DatasetMeta;
    let message: string;
    try {
      type ChunkTask = {
        ref: (typeof fileRefs)[number];
        chunkIndex: number;
        totalChunks: number;
        start: number;
        end: number;
        size: number;
        progressKey: string;
      };
      const chunkTasks: ChunkTask[] = [];
      for (const ref of fileRefs) {
        const totalChunks = Math.max(1, Math.ceil(ref.file.size / UPLOAD_CHUNK_SIZE));
        for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex += 1) {
          const start = chunkIndex * UPLOAD_CHUNK_SIZE;
          const end = Math.min(ref.file.size, start + UPLOAD_CHUNK_SIZE);
          chunkTasks.push({
            ref,
            chunkIndex,
            totalChunks,
            start,
            end,
            size: Math.max(1, end - start),
            progressKey: `${ref.file_id}:${chunkIndex}`
          });
        }
      }
      const chunkProgressBytes = new Map<string, number>();
      const startedAt = performance.now();
      let startedChunks = 0;
      let confirmedChunks = 0;
      const renderChunkProgress = () => {
        const uploadedBytes = Array.from(chunkProgressBytes.values()).reduce((sum, value) => sum + value, 0);
        const progress = Math.min(94, Math.round((uploadedBytes / totalBytes) * 94));
        const elapsedSeconds = Math.max(0.2, (performance.now() - startedAt) / 1000);
        const speed = uploadedBytes / 1024 / 1024 / elapsedSeconds;
        const inFlight = Math.max(0, startedChunks - confirmedChunks);
        setUploadProgress(progress);
        setUploadMessage(
          `Uploading ${progress}% · ${confirmedChunks}/${chunkTasks.length} chunks confirmed · ${inFlight} in flight · x${requestedConcurrency} · ${speed.toFixed(speed >= 10 ? 0 : 1)} MB/s`
        );
      };
      const updateChunkProgress = (task: ChunkTask, bytes: number) => {
        const previous = chunkProgressBytes.get(task.progressKey) || 0;
        chunkProgressBytes.set(task.progressKey, Math.max(previous, Math.min(task.size, bytes)));
        renderChunkProgress();
      };
      await runLimitedConcurrency(chunkTasks, requestedConcurrency, async (task) => {
        startedChunks += 1;
        renderChunkProgress();
        const chunk = task.ref.file.slice(task.start, task.end);
        const form = new FormData();
        form.set("session_id", sessionId);
        form.set("file_id", task.ref.file_id);
        form.set("filename", task.ref.filename);
        form.set("chunk_index", String(task.chunkIndex));
        form.set("total_chunks", String(task.totalChunks));
        form.append("chunk", chunk, task.ref.filename);
        await api.uploadChunk(form, (chunkProgress) => {
          updateChunkProgress(task, (task.size * chunkProgress) / 100);
        });
        confirmedChunks += 1;
        updateChunkProgress(task, task.size);
      });
      setUploadProgress(96);
      setUploadMessage("Finishing upload...");
      const files = fileRefs.map((ref) => ({ file_id: ref.file_id, filename: ref.filename, size: ref.size }));
      if (dataset) {
        const result = await api.completeChunkedImageUpload(dataset.dataset_id, {
          session_id: sessionId,
          upload_batch_id: batchId,
          files
        });
        meta = result.dataset;
        message = `Uploaded ${result.added} image(s) to ${meta.name}`;
      } else {
        meta = await api.completeChunkedDatasetUpload({
          session_id: sessionId,
          upload_batch_id: batchId,
          name: autoUploadDatasetName(uploadFiles),
          camera_name: "camera_1",
          classes: DEFAULT_CLASSES,
          files
        });
        message = `Uploaded ${meta.image_count} image(s) as ${meta.name}`;
      }
      setUploadProgress(100);
      setDataset(meta);
      setSelectedImage(null);
      setPayload(null);
      setSelection({ objectId: null, graspId: null, handle: null });
      setDirty(false);
      setUploadFiles([]);
      setUploadBatchId("");
      setUploadMessage(message);
      await loadDatasetCatalog();
      await loadImages(meta);
      setStatusLine(message);
    } catch (exc) {
      setError(String((exc as Error).message || exc));
      setUploadMessage("Upload failed");
    } finally {
      uploadingRef.current = false;
      setUploading(false);
    }
  }

  async function saveDatasetClasses() {
    if (!dataset) return;
    setError("");
    try {
      const meta = await api.updateClasses(dataset.dataset_id, dataset.classes);
      setDataset(meta);
      setDatasetList((current) => current.map((item) => (item.dataset_id === meta.dataset_id ? meta : item)));
      setStatusLine("Classes saved");
    } catch (exc) {
      setError(String((exc as Error).message || exc));
    }
  }

  async function deleteImage(item: ImageItem) {
    if (!dataset) return;
    if (dirty && selectedImage?.image_id === item.image_id) {
      setError("Save or release current changes before deleting this image.");
      return;
    }
    const ok = window.confirm(`Delete ${item.image_key}? The image and annotation will be moved to .aga_trash.`);
    if (!ok) return;
    setError("");
    try {
      const result = await api.deleteImage(dataset.dataset_id, item.image_id);
      setDataset(result.dataset);
      setDatasetList((current) => current.map((entry) => (entry.dataset_id === result.dataset.dataset_id ? result.dataset : entry)));
      if (selectedImage?.image_id === item.image_id) {
        await releaseCurrentLock();
        setSelectedImage(null);
        setPayload(null);
        setSelection({ objectId: null, graspId: null, handle: null });
      }
      const data = await api.images(dataset.dataset_id, imageStatus);
      setImages(data.items);
      setStatusLine(`Deleted ${item.image_key}`);
    } catch (exc) {
      setError(String((exc as Error).message || exc));
    }
  }

  async function deleteImages(items: ImageItem[]) {
    if (!dataset || !items.length) return;
    const selectedIds = new Set(items.map((item) => item.image_id));
    if (dirty && selectedImage && selectedIds.has(selectedImage.image_id)) {
      setError("Save or release current changes before deleting selected images.");
      return;
    }
    const ok = window.confirm(`Delete ${items.length} selected image(s)? Images and annotations will be moved to .aga_trash.`);
    if (!ok) return;
    setError("");
    let latestDataset = dataset;
    let deletedCount = 0;
    const failures: string[] = [];
    for (const item of items) {
      try {
        const result = await api.deleteImage(dataset.dataset_id, item.image_id);
        latestDataset = result.dataset;
        deletedCount += 1;
      } catch (exc) {
        failures.push(`${item.image_key}: ${String((exc as Error).message || exc)}`);
      }
    }
    setDataset(latestDataset);
    setDatasetList((current) =>
      current.map((entry) => (entry.dataset_id === latestDataset.dataset_id ? latestDataset : entry))
    );
    if (selectedImage && selectedIds.has(selectedImage.image_id)) {
      await releaseCurrentLock();
      setSelectedImage(null);
      setPayload(null);
      setSelection({ objectId: null, graspId: null, handle: null });
    }
    const data = await api.images(dataset.dataset_id, imageStatus);
    setImages(data.items);
    setStatusLine(`Deleted ${deletedCount} image(s)`);
    if (failures.length) {
      setError(`Some images were not deleted: ${failures.slice(0, 3).join("; ")}`);
    }
  }

  async function selectImage(item: ImageItem) {
    if (!(await ensureCleanBeforeSwitch())) return;
    await releaseCurrentLock();
    setSelectedImage(item);
    setPayload(null);
    setSelection({ objectId: null, graspId: null, handle: null });
    setValidationErrors([]);
    setValidationWarnings([]);
    setStatusLine("");
    if (!dataset) return;
    const next = await api.annotation(dataset.dataset_id, item.image_id);
    setPayload(next);
    setDirty(false);
    setLock(null);
  }

  async function selectAdjacentImage(delta: number) {
    if (!images.length) return;
    const currentIndex = selectedImage ? images.findIndex((item) => item.image_id === selectedImage.image_id) : -1;
    const fallback = delta > 0 ? 0 : images.length - 1;
    const nextIndex = currentIndex >= 0 ? (currentIndex + delta + images.length) % images.length : fallback;
    await selectImage(images[nextIndex]);
  }

  async function startEditing() {
    if (!dataset || !selectedImage) return;
    setError("");
    try {
      const next = await api.lock(dataset.dataset_id, selectedImage.image_id);
      setLock(next);
      setPayload(payload ? { ...payload, lock: null } : payload);
      setStatusLine("Editing");
    } catch (exc) {
      setError(String((exc as Error).message || exc));
      if (dataset && selectedImage) {
        const fresh = await api.annotation(dataset.dataset_id, selectedImage.image_id);
        setPayload(fresh);
      }
    }
  }

  function defaultClassAction(bbox: [number, number, number, number]): AnnotationAction {
    return { type: "addObject", classInfo: firstClass(dataset?.classes || []), bbox };
  }

  function deleteSelection() {
    if (!editable || !selection.objectId) return;
    if (selection.graspId) {
      dispatchAnnotation({ type: "deleteGrasp", instanceId: selection.objectId, graspId: selection.graspId });
    } else {
      dispatchAnnotation({ type: "deleteObject", instanceId: selection.objectId });
    }
    setSelection({ objectId: null, graspId: null, handle: null });
  }

  function updateSelectedDifficulty(difficulty: GraspAnnotation["difficulty"]) {
    if (!editable || !selection.objectId || !selection.graspId) return;
    dispatchAnnotation({ type: "updateGraspMetadata", instanceId: selection.objectId, graspId: selection.graspId, difficulty });
  }

  async function validateCurrent() {
    if (!dataset) return;
    const result = await api.validate(dataset.dataset_id, selectedImage?.image_id);
    setValidationErrors(result.errors);
    setValidationWarnings(result.warnings);
    setStatusLine(result.valid ? "Validation passed" : "Validation issues");
  }

  async function exportDataset(exportType: "yolo" | "grasp_roi" | "target_maps") {
    if (!dataset) return;
    if (dirty && !(await saveCurrent())) return;
    setJobMessage("Export queued");
    const job = await api.exportDataset(dataset.dataset_id, exportType);
    const timer = window.setInterval(async () => {
      const latest = await api.job(job.id);
      setJobMessage(`${latest.status}: ${latest.message || exportType}`);
      if (!["queued", "running"].includes(latest.status)) window.clearInterval(timer);
    }, 1000);
  }

  if (!loggedIn) {
    return (
      <main className="login-view">
        <section className="login-panel">
          <h1>Assistive Grasp Annotator</h1>
          <div className="form-row">
            <label htmlFor="login-username">Username</label>
            <input id="login-username" value={username} onChange={(event) => setUsername(event.target.value)} onKeyDown={(event) => event.key === "Enter" && login()} />
          </div>
          <button className="primary" onClick={() => void login()}>
            <Lock size={16} /> Enter
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <DatasetPanel
        username={username}
        datasetList={datasetList}
        newDatasetName={newDatasetName}
        dataset={dataset}
        images={images}
        imageStatus={imageStatus}
        selectedImageId={selectedImage?.image_id || null}
        uploadFiles={uploadFiles}
        uploading={uploading}
        uploadProgress={uploadProgress}
        uploadMessage={uploadMessage}
        uploadConcurrency={uploadConcurrency}
        onNewDatasetNameChange={setNewDatasetName}
        onCreateDataset={() => void createDataset()}
        onSelectDataset={(datasetId) => void selectDataset(datasetId)}
        onRenameDataset={(name) => void renameDataset(name)}
        onDeleteDataset={() => void deleteDataset()}
        onRefreshDatasets={() => void loadDatasetCatalog()}
        onDatasetClassesChange={(classes) => setDataset((current) => (current ? { ...current, classes } : current))}
        onSaveDatasetClasses={() => void saveDatasetClasses()}
        onRefreshImages={() => void loadImages()}
        onStatusChange={(status) => {
          setImageStatus(status);
          void loadImages(dataset, status);
        }}
        onImageSelect={(image) => void selectImage(image)}
        onUploadFilesChange={handleUploadFilesChange}
        onUploadConcurrencyChange={handleUploadConcurrencyChange}
        onUploadDataset={() => void uploadDataset()}
        onDeleteImage={(image) => void deleteImage(image)}
        onDeleteImages={(selectedImages) => void deleteImages(selectedImages)}
      />

      <section className="workspace">
        <Toolbar
          mode={mode}
          canEdit={editable}
          canAcquireLock={Boolean(selectedImage && !lock && (!payload?.lock || payload.lock.user === username))}
          dirty={dirty}
          lock={lock}
          lockedBy={lockedBy && lockedBy !== username ? lockedBy : null}
          onModeChange={setMode}
          onAcquireLock={() => void startEditing()}
          onReleaseLock={() => void releaseCurrentLock()}
          onSave={() => void saveCurrent()}
          onDelete={deleteSelection}
          onValidate={() => void validateCurrent()}
        />
        {(error || statusLine) && <div className={error ? "error-line" : "status-line"}>{error || statusLine}</div>}
        <AnnotationCanvas
          imageUrl={imageUrl}
          annotation={annotation}
          mode={mode}
          editable={editable}
          selection={selection}
          onSelectionChange={setSelection}
          onModeChange={setMode}
          onAction={dispatchAnnotation}
          onNoObjectForGrasp={() => setStatusLine("Draw a bbox first, then select it before drawing grasps")}
          defaultClassAction={defaultClassAction}
        />
      </section>

      <SidePanel
        dataset={dataset}
        annotation={annotation}
        imageKey={payload?.image_key || ""}
        selection={selection}
        editable={editable}
        validationErrors={validationErrors}
        validationWarnings={validationWarnings}
        jobMessage={jobMessage}
        onSelectionChange={setSelection}
        onClassChange={(instanceId: number, classInfo: ClassInfo) =>
          dispatchAnnotation({ type: "updateObjectClass", instanceId, classInfo })
        }
        onDifficultyChange={(instanceId, graspId, difficulty) =>
          dispatchAnnotation({ type: "updateGraspMetadata", instanceId, graspId, difficulty })
        }
        onQualityChange={(instanceId, graspId, quality) =>
          dispatchAnnotation({ type: "updateGraspMetadata", instanceId, graspId, quality })
        }
        onNoteChange={(instanceId, graspId, note) =>
          dispatchAnnotation({ type: "updateGraspMetadata", instanceId, graspId, note })
        }
        onExport={(exportType) => void exportDataset(exportType)}
      />
    </main>
  );
}
