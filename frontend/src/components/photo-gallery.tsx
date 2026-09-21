import { useCallback, useEffect, useState } from "react";

import { Angle, api, ItemDetail, Photo, photoUrl } from "../api";
import { FileButton } from "./controls";
import { CameraIcon, UploadIcon, WebcamIcon } from "./icons";
import { Lightbox, PhotoEditor, WebcamCapture } from "./photos";

const ANGLES: Angle[] = ["obverse", "reverse", "edge", "other"];

/** The item page's Photos card: the grid with reorder, angle, primary, edit
 * and delete, plus every way in: picker, camera, webcam, URL, drop, paste. */
export function PhotoGallery({ item, onChanged }: { item: ItemDetail; onChanged: () => void }) {
  const [uploading, setUploading] = useState(false);
  const [uploadAngle, setUploadAngle] = useState<Angle | "">("");
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [photoNote, setPhotoNote] = useState<string | null>(null);
  const [photoSource, setPhotoSource] = useState("");
  const [dragging, setDragging] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [editing, setEditing] = useState<Photo | null>(null);
  const [webcam, setWebcam] = useState(false);

  const itemId = item.id;

  // One path for picked, dropped, and pasted files.
  const uploadFiles = useCallback(
    async (files: File[], how: string) => {
      const images = files.filter((f) => f.type.startsWith("image/"));
      if (images.length === 0) {
        setPhotoError("Only image files can be added as photos.");
        return;
      }
      setUploading(true);
      setPhotoError(null);
      setPhotoNote(null);
      let added = 0;
      try {
        for (const file of images) {
          await api.uploadPhoto(itemId, file, uploadAngle);
          added++;
        }
        setPhotoNote(`${how} ${added} photo${added > 1 ? "s" : ""}.`);
      } catch (err) {
        setPhotoError((err as Error).message);
      } finally {
        setUploading(false);
        onChanged(); // earlier files in the batch may have landed
      }
    },
    [itemId, uploadAngle, onChanged],
  );

  // Paste an image anywhere on the item page to add it.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (!files.some((f) => f.type.startsWith("image/"))) return;
      e.preventDefault();
      uploadFiles(files, "Pasted");
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [uploadFiles]);

  const act = (fn: () => Promise<unknown>) => () =>
    fn().then(onChanged).catch((e: Error) => setPhotoError(e.message));

  const movePhoto = (index: number, delta: number) => {
    const order = item.photos.map((p) => p.id);
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    act(() => api.reorderPhotos(item.id, order))();
  };

  async function importFromUrl() {
    const url = photoSource.trim();
    if (!url) return;
    setUploading(true);
    setPhotoError(null);
    setPhotoNote(null);
    try {
      await api.importPhoto(itemId, url, uploadAngle);
      setPhotoSource("");
      setPhotoNote("Imported the photo from the URL.");
      onChanged();
    } catch (err) {
      setPhotoError((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  // Errors propagate to the editor, which shows them and stays open.
  async function saveEdit(image: Blob, filename: string, asCopy: boolean) {
    if (!editing) return;
    if (asCopy) {
      await api.uploadPhoto(itemId, new File([image], filename, { type: image.type }), editing.angle ?? "");
    } else {
      await api.replacePhotoImage(editing.id, image, filename);
    }
    setEditing(null);
    setPhotoNote(asCopy ? "Saved the edit as a new photo." : "Replaced the photo with the edit.");
    onChanged();
  }

  async function captureWebcam(image: Blob) {
    const file = new File([image], `webcam-${Date.now()}.jpg`, { type: "image/jpeg" });
    await api.uploadPhoto(itemId, file, uploadAngle);
    onChanged();
  }

  return (
    <div
      className={`card photo-drop${dragging ? " dragging" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        uploadFiles(Array.from(e.dataTransfer.files), "Dropped");
      }}
    >
      <h2>Photos</h2>
      {photoError && <p className="error">{photoError}</p>}
      {photoNote && <p className="muted">{photoNote}</p>}
      {item.photos.length === 0 && (
        <p className="muted">No photos yet.</p>
      )}
      <div className="photo-grid">
        {item.photos.map((photo, index) => (
          <div key={photo.id} className={`photo-card${photo.is_primary ? " primary" : ""}`}>
            <button type="button" className="photo-open" title="View larger"
              onClick={() => setLightbox(index)}>
              {/* A photo whose file has gone still gets a tile, so it can be deleted. */}
              <img src={photoUrl(photo.thumb_key ?? photo.file_key)}
                alt={photo.angle ?? "photo"}
                onError={(e) => e.currentTarget.classList.add("missing")} />
            </button>
            <div className="row">
              <button title="Move left" disabled={index === 0}
                onClick={() => movePhoto(index, -1)}>←</button>
              <select
                value={photo.angle ?? ""}
                onChange={(e) =>
                  act(() => api.updatePhoto(photo.id, { angle: e.target.value as Angle }))()
                }
              >
                <option value="" disabled>angle…</option>
                {ANGLES.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
              <button title="Move right" disabled={index === item.photos.length - 1}
                onClick={() => movePhoto(index, 1)}>→</button>
              <button
                title="Delete photo"
                onClick={() => {
                  if (window.confirm("Delete this photo?")) {
                    act(() => api.deletePhoto(photo.id))();
                  }
                }}
              >
                ✕
              </button>
            </div>
            <div className="row">
              {photo.is_primary ? (
                <span className="muted">★ primary</span>
              ) : (
                <button onClick={act(() => api.updatePhoto(photo.id, { is_primary: true }))}>
                  Make primary
                </button>
              )}
              <button title="Crop, turn, or straighten" onClick={() => setEditing(photo)}>
                ✎ Edit
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="dropzone">
        <FileButton primary multiple accept="image/jpeg,image/png,image/webp"
          disabled={uploading} onFiles={(files) => uploadFiles(files, "Added")}>
          <UploadIcon /> {uploading ? "Uploading…" : "Add photos"}
        </FileButton>
        {/* capture opens the camera directly on phones; a normal picker elsewhere */}
        <FileButton accept="image/jpeg,image/png,image/webp" capture="environment"
          disabled={uploading} onFiles={(files) => uploadFiles(files, "Added")}
          title="Opens the camera on a phone">
          <CameraIcon /> Camera
        </FileButton>
        <button type="button" disabled={uploading} onClick={() => setWebcam(true)}
          title="Take photos with a webcam">
          <WebcamIcon /> Webcam
        </button>
        <span className="muted">or drop images here, or paste one</span>
      </div>
      <div className="estimate-form">
        <label className="field">
          Angle for new photos
          <select value={uploadAngle}
            onChange={(e) => setUploadAngle(e.target.value as Angle | "")}>
            <option value="">unspecified</option>
            {ANGLES.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Import from URL
          <input type="url" value={photoSource} placeholder="https://…"
            onChange={(e) => setPhotoSource(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") importFromUrl();
            }} />
        </label>
        <button type="button" disabled={uploading || !photoSource.trim()} onClick={importFromUrl}>
          Import
        </button>
      </div>
      {lightbox !== null && item.photos[lightbox] && (
        <Lightbox photos={item.photos} index={lightbox} onIndex={setLightbox}
          onClose={() => setLightbox(null)} />
      )}
      {editing && (
        <PhotoEditor photo={editing} onCancel={() => setEditing(null)} onSave={saveEdit} />
      )}
      {webcam && <WebcamCapture onCancel={() => setWebcam(false)} onCapture={captureWebcam} />}
    </div>
  );
}
