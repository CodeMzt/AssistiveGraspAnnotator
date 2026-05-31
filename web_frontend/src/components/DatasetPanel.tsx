import { Database, Images, Pencil, Plus, RefreshCw, Settings2, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import type { ClassInfo, DatasetMeta, ImageItem } from "../types";
import { ClassEditorDialog } from "./ClassEditorDialog";
import { DatasetManagerDialog } from "./DatasetManagerDialog";

type Props = {
  username: string;
  datasetList: DatasetMeta[];
  newDatasetName: string;
  dataset: DatasetMeta | null;
  images: ImageItem[];
  imageStatus: string;
  selectedImageId: string | null;
  uploadFiles: File[];
  uploading: boolean;
  uploadProgress: number;
  uploadMessage: string;
  uploadConcurrency: number;
  onNewDatasetNameChange: (value: string) => void;
  onCreateDataset: () => void;
  onSelectDataset: (datasetId: string) => void;
  onRenameDataset: (name: string) => void;
  onDeleteDataset: () => void;
  onRefreshDatasets: () => void;
  onDatasetClassesChange: (classes: ClassInfo[]) => void;
  onSaveDatasetClasses: () => void;
  onRefreshImages: () => void;
  onStatusChange: (status: string) => void;
  onImageSelect: (image: ImageItem) => void;
  onUploadFilesChange: (files: File[]) => void;
  onUploadConcurrencyChange: (value: number) => void;
  onUploadDataset: () => void;
  onDeleteImage: (image: ImageItem) => void;
  onDeleteImages: (images: ImageItem[]) => void;
};

export function DatasetPanel({
  username,
  datasetList,
  newDatasetName,
  dataset,
  images,
  imageStatus,
  selectedImageId,
  uploadFiles,
  uploading,
  uploadProgress,
  uploadMessage,
  uploadConcurrency,
  onNewDatasetNameChange,
  onCreateDataset,
  onSelectDataset,
  onRenameDataset,
  onDeleteDataset,
  onRefreshDatasets,
  onDatasetClassesChange,
  onSaveDatasetClasses,
  onRefreshImages,
  onStatusChange,
  onImageSelect,
  onUploadFilesChange,
  onUploadConcurrencyChange,
  onUploadDataset,
  onDeleteImage,
  onDeleteImages
}: Props) {
  const [datasetClassesOpen, setDatasetClassesOpen] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const [renameName, setRenameName] = useState(dataset?.name || "");

  useEffect(() => {
    setRenameName(dataset?.name || "");
  }, [dataset?.dataset_id, dataset?.name]);

  function appendFiles(files: FileList | File[]) {
    const current = new Map(uploadFiles.map((file) => [`${file.name}-${file.size}-${file.lastModified}`, file]));
    Array.from(files).forEach((file) => {
      if (file.type.startsWith("image/") || /\.(jpe?g|png|bmp|tiff?)$/i.test(file.name)) {
        current.set(`${file.name}-${file.size}-${file.lastModified}`, file);
      }
    });
    onUploadFilesChange(Array.from(current.values()));
  }

  return (
    <aside className="left-panel">
      <div className="brand-row">
        <div>
          <strong>Assistive Grasp</strong>
          <span>{username}</span>
        </div>
        <button title="Refresh datasets" onClick={onRefreshDatasets}>
          <RefreshCw size={16} />
        </button>
      </div>

      <section className="source-block">
        <div className="section-title">Datasets</div>
        <div className="dataset-select-row">
          <select value={dataset?.dataset_id || ""} onChange={(event) => event.target.value && onSelectDataset(event.target.value)}>
            <option value="">Select dataset</option>
            {datasetList.map((item) => (
              <option key={item.dataset_id} value={item.dataset_id}>
                {item.name}{item.missing ? " (missing)" : ""}
              </option>
            ))}
          </select>
          <button title="Refresh datasets" onClick={onRefreshDatasets}>
            <Database size={16} />
          </button>
        </div>
        <div className="create-dataset-row">
          <input
            value={newDatasetName}
            onChange={(event) => onNewDatasetNameChange(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && onCreateDataset()}
            placeholder="New dataset name"
          />
          <button title="Create dataset" onClick={onCreateDataset}>
            <Plus size={16} />
          </button>
        </div>
        {dataset && (
          <div className="dataset-admin">
            <div className="summary-row">
              <span>{dataset.image_count} images / {dataset.classes.length} classes</span>
              <button type="button" className="danger-button" onClick={onDeleteDataset}>
                <Trash2 size={15} /> Delete
              </button>
            </div>
            <div className="rename-row">
              <input value={renameName} onChange={(event) => setRenameName(event.target.value)} aria-label="Dataset name" />
              <button type="button" onClick={() => onRenameDataset(renameName)}>
                <Pencil size={15} /> Rename
              </button>
            </div>
          </div>
        )}
      </section>

      {dataset && (
        <section className="source-block">
          <div className="section-title">Classes</div>
          <div className="summary-row">
            <span>{dataset.classes.length} classes</span>
            <button type="button" onClick={() => setDatasetClassesOpen(true)}>
              <Pencil size={16} /> Edit
            </button>
          </div>
          <div className="class-summary-list">
            {dataset.classes.slice(0, 4).map((cls) => (
              <span key={cls.id}>{cls.id}: {cls.name}</span>
            ))}
            {dataset.classes.length > 4 && <span>+{dataset.classes.length - 4} more</span>}
          </div>
        </section>
      )}

      <section className="source-block">
        <div className="section-title">Upload</div>
        <div
          className="upload-dropzone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            appendFiles(event.dataTransfer.files);
          }}
        >
          <Images size={18} />
          <span>{uploadFiles.length ? `${uploadFiles.length} image(s) selected` : "Drop images here or choose files/folder"}</span>
        </div>
        <div className="native-upload-grid">
          <label className="native-upload-field">
            <span>Choose image files</span>
            <input
              className="native-file-input"
              type="file"
              multiple
              accept="image/*"
              disabled={uploading}
              onChange={(event) => {
                appendFiles(event.target.files || []);
                event.currentTarget.value = "";
              }}
            />
          </label>
          <label className="native-upload-field">
            <span>Choose folder</span>
            <input
              className="native-file-input"
              type="file"
              multiple
              accept="image/*"
              webkitdirectory=""
              directory=""
              disabled={uploading}
              onChange={(event) => {
                appendFiles(event.target.files || []);
                event.currentTarget.value = "";
              }}
            />
          </label>
        </div>
        {uploadFiles.length > 0 && (
          <div className="upload-file-list">
            {uploadFiles.slice(0, 5).map((file) => (
              <span key={`${file.name}-${file.size}-${file.lastModified}`}>{file.name}</span>
            ))}
            {uploadFiles.length > 5 && <span>+{uploadFiles.length - 5} more</span>}
          </div>
        )}
        {(uploading || uploadMessage) && (
          <div className="upload-progress-block">
            <div className="upload-progress-track">
              <span style={{ width: `${Math.max(0, Math.min(uploadProgress, 100))}%` }} />
            </div>
            <p>{uploadMessage || `Uploading ${uploadProgress}%`}</p>
          </div>
        )}
        <label className="upload-speed-row">
          <span>Speed</span>
          <select
            value={uploadConcurrency}
            disabled={uploading}
            aria-label="Upload parallel requests"
            onChange={(event) => onUploadConcurrencyChange(Number(event.target.value))}
          >
            <option value={6}>Safe x6</option>
            <option value={12}>Fast x12</option>
            <option value={18}>Turbo x18</option>
            <option value={24}>Max x24</option>
            <option value={32}>Max x32</option>
          </select>
        </label>
        <div className="upload-action-row">
          <button type="button" disabled={!uploadFiles.length || uploading} onClick={() => onUploadFilesChange([])}>
            Clear
          </button>
          <button type="button" className="primary upload-action-button" disabled={!uploadFiles.length || uploading} onClick={onUploadDataset}>
            <Upload size={16} /> {uploading ? `Uploading ${uploadProgress}%` : `Upload ${uploadFiles.length || ""}`}
          </button>
        </div>
      </section>

      <ClassEditorDialog
        title="Dataset Classes"
        classes={dataset?.classes || []}
        open={datasetClassesOpen}
        onChange={onDatasetClassesChange}
        onSave={() => {
          onSaveDatasetClasses();
          setDatasetClassesOpen(false);
        }}
        saveLabel="Save Classes"
        onClose={() => setDatasetClassesOpen(false)}
      />
      <DatasetManagerDialog
        dataset={dataset}
        images={images}
        open={managerOpen}
        onClose={() => setManagerOpen(false)}
        onRefresh={onRefreshImages}
        onDeleteImage={onDeleteImage}
        onDeleteImages={onDeleteImages}
      />

      {dataset && (
        <section className="image-list-block">
          <div className="dataset-stats">
            <strong>{dataset.name}</strong>
            <span>{dataset.annotated} annotated / {dataset.unannotated} unannotated</span>
          </div>
          <button type="button" className="wide-button" onClick={() => setManagerOpen(true)}>
            <Settings2 size={16} /> Manage Images
          </button>
          <select value={imageStatus} onChange={(event) => onStatusChange(event.target.value)}>
            <option value="all">All</option>
            <option value="unannotated">Unannotated</option>
            <option value="empty">Empty</option>
            <option value="annotated">Annotated</option>
          </select>
          <div className="image-list">
            {images.map((item) => (
              <button
                key={item.image_id}
                className={selectedImageId === item.image_id ? "image-row active" : "image-row"}
                onClick={() => onImageSelect(item)}
              >
                <span>{item.image_key}</span>
                <em className={`status ${item.status}`}>{item.status}</em>
                {item.lock && <span className="tiny-lock">locked</span>}
              </button>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}
