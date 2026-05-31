import { RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { DatasetMeta, ImageItem } from "../types";

type Props = {
  dataset: DatasetMeta | null;
  images: ImageItem[];
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onDeleteImage: (image: ImageItem) => void;
  onDeleteImages: (images: ImageItem[]) => void;
};

export function DatasetManagerDialog({ dataset, images, open, onClose, onRefresh, onDeleteImage, onDeleteImages }: Props) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    setSelectedIds((current) => new Set([...current].filter((id) => images.some((image) => image.image_id === id))));
  }, [images]);

  if (!open || !dataset) return null;
  const selectedImages = images.filter((image) => selectedIds.has(image.image_id));
  const allSelected = images.length > 0 && selectedImages.length === images.length;
  const toggleAll = () => {
    setSelectedIds(allSelected ? new Set() : new Set(images.map((image) => image.image_id)));
  };
  const toggleOne = (imageId: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(imageId)) next.delete(imageId);
      else next.add(imageId);
      return next;
    });
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-panel manage-modal" role="dialog" aria-modal="true" aria-label="Dataset Manager">
        <header className="modal-header">
          <div>
            <h2>Dataset Manager</h2>
            <p>{dataset.name} - {dataset.image_count} images</p>
          </div>
          <div className="modal-header-actions">
            <button
              type="button"
              className="danger-button"
              disabled={!selectedImages.length}
              onClick={() => onDeleteImages(selectedImages)}
            >
              <Trash2 size={16} /> Delete Selected {selectedImages.length || ""}
            </button>
            <button type="button" onClick={onRefresh}>
              <RefreshCw size={16} /> Refresh
            </button>
            <button type="button" title="Close" onClick={onClose}>
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="manage-table">
          <div className="manage-row manage-header">
            <label className="manage-check-cell">
              <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="Select all images" />
            </label>
            <span>Image</span>
            <span>Status</span>
            <span>Objects</span>
            <span>Lock</span>
            <span>Action</span>
          </div>
          {images.map((image) => (
            <div className="manage-row" key={image.image_id}>
              <label className="manage-check-cell">
                <input
                  type="checkbox"
                  checked={selectedIds.has(image.image_id)}
                  onChange={() => toggleOne(image.image_id)}
                  aria-label={`Select ${image.image_key}`}
                />
              </label>
              <span title={image.image_key}>{image.image_key}</span>
              <em className={`status ${image.status}`}>{image.status}</em>
              <span>{image.object_count} obj / {image.grasp_count} grasp</span>
              <span>{image.lock ? `Locked by ${image.lock.user}` : "Free"}</span>
              <button type="button" className="danger-button" onClick={() => onDeleteImage(image)}>
                <Trash2 size={15} /> Delete
              </button>
            </div>
          ))}
          {images.length === 0 && <div className="empty-manager">No images in this dataset</div>}
        </div>
      </section>
    </div>
  );
}
