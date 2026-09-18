import {
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { Photo, photoUrl } from "../api";

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

/** Keeps the page behind an overlay from scrolling while it's open. */
function useNoScroll() {
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useNoScroll();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="card modal-body" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** Full-size viewer. Click or scroll to zoom where you point, move the
 * pointer to pan while zoomed, ←/→ to step through, Esc to close. */
export function Lightbox({
  photos,
  index,
  onIndex,
  onClose,
}: {
  photos: Photo[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [origin, setOrigin] = useState({ x: 50, y: 50 });
  const count = photos.length;
  const photo = photos[index];
  useNoScroll();

  useEffect(() => {
    setZoom(1);
    setOrigin({ x: 50, y: 50 });
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && count > 1) onIndex((index + 1) % count);
      else if (e.key === "ArrowLeft" && count > 1) onIndex((index - 1 + count) % count);
      else if (e.key === "+" || e.key === "=") setZoom((z) => clamp(z * 1.5, 1, 8));
      else if (e.key === "-") setZoom((z) => clamp(z / 1.5, 1, 8));
      else if (e.key === "0") setZoom(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, count, onIndex, onClose]);

  // The pointer's position as a percentage of the stage — the image fills the
  // stage box, so this is also the point on the image to zoom around.
  const pointAt = (e: ReactMouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return {
      x: clamp(((e.clientX - box.left) / box.width) * 100, 0, 100),
      y: clamp(((e.clientY - box.top) / box.height) * 100, 0, 100),
    };
  };

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer"
      onClick={onClose}>
      <div
        className="lightbox-stage"
        style={{ cursor: zoom > 1 ? "zoom-out" : "zoom-in" }}
        onClick={(e) => {
          e.stopPropagation();
          setOrigin(pointAt(e));
          setZoom((z) => (z > 1 ? 1 : 2.5));
        }}
        onMouseMove={(e) => {
          if (zoom > 1) setOrigin(pointAt(e));
        }}
        onWheel={(e) => {
          setOrigin(pointAt(e));
          setZoom((z) => clamp(e.deltaY < 0 ? z * 1.25 : z / 1.25, 1, 8));
        }}
      >
        <img
          src={photoUrl(photo.file_key)}
          alt={photo.angle ?? "photo"}
          draggable={false}
          style={{ transform: `scale(${zoom})`, transformOrigin: `${origin.x}% ${origin.y}%` }}
        />
      </div>
      <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
        {count > 1 && (
          <button onClick={() => onIndex((index - 1 + count) % count)} title="Previous (←)">
            ←
          </button>
        )}
        <span>
          {index + 1} / {count}
          {photo.angle ? ` · ${photo.angle}` : ""}
          {photo.width && photo.height ? ` · ${photo.width}×${photo.height}` : ""}
          {` · ${Math.round(zoom * 100)}%`}
        </span>
        {count > 1 && (
          <button onClick={() => onIndex((index + 1) % count)} title="Next (→)">
            →
          </button>
        )}
        <a className="button" href={photoUrl(photo.file_key)} target="_blank" rel="noreferrer">
          Original ↗
        </a>
        <button onClick={onClose} title="Close (Esc)">✕</button>
      </div>
    </div>
  );
}

type Crop = { x: number; y: number; w: number; h: number }; // fractions of the turned frame
type Handle = "move" | "nw" | "ne" | "sw" | "se";
type Drag = { handle: Handle; x: number; y: number; crop: Crop };

const FULL: Crop = { x: 0, y: 0, w: 1, h: 1 };
const MIN_CROP = 0.05;
const PREVIEW_MAX = { w: 640, h: 440 };

/** Scale that lets an image turned by `radians` still cover a w × h frame, so
 * straightening never leaves empty corners. */
function coverScale(w: number, h: number, radians: number) {
  const c = Math.abs(Math.cos(radians));
  const s = Math.abs(Math.sin(radians));
  return Math.max((w * c + h * s) / w, (w * s + h * c) / h);
}

/** Draw `img` turned by `quarter` × 90° and straightened by `degrees` into a
 * frame of fw × fh, shifted so (offsetX, offsetY) of the frame lands at 0,0. */
function drawFrame(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  quarter: number,
  degrees: number,
  fw: number,
  fh: number,
  offsetX = 0,
  offsetY = 0,
) {
  const straighten = (degrees * Math.PI) / 180;
  const scale = coverScale(fw, fh, straighten);
  ctx.save();
  ctx.translate(fw / 2 - offsetX, fh / 2 - offsetY);
  ctx.rotate(straighten);
  ctx.scale(scale, scale);
  ctx.rotate((quarter * Math.PI) / 2);
  ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
  ctx.restore();
}

/** Crop, turn, and straighten a photo in the browser, at full resolution. */
export function PhotoEditor({
  photo,
  onCancel,
  onSave,
}: {
  photo: Photo;
  onCancel: () => void;
  onSave: (image: Blob, filename: string, asCopy: boolean) => Promise<void>;
}) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [quarter, setQuarter] = useState(0);
  const [degrees, setDegrees] = useState(0);
  const [crop, setCrop] = useState<Crop>(FULL);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<Drag | null>(null);

  useEffect(() => {
    const image = new Image();
    image.onload = () => setImg(image);
    image.onerror = () => setError("Couldn't load the photo.");
    image.src = photoUrl(photo.file_key);
  }, [photo.file_key]);

  const fw = img ? (quarter % 2 ? img.naturalHeight : img.naturalWidth) : 1;
  const fh = img ? (quarter % 2 ? img.naturalWidth : img.naturalHeight) : 1;
  const preview = Math.min(PREVIEW_MAX.w / fw, PREVIEW_MAX.h / fh, 1);
  const previewW = Math.round(fw * preview);
  const previewH = Math.round(fh * preview);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!img || !canvas || !ctx) return;
    canvas.width = previewW;
    canvas.height = previewH;
    ctx.save();
    ctx.scale(preview, preview);
    drawFrame(ctx, img, quarter, degrees, fw, fh);
    ctx.restore();
  }, [img, quarter, degrees, fw, fh, preview, previewW, previewH]);

  const turn = (by: number) => {
    setQuarter((q) => (q + by + 4) % 4);
    setCrop(FULL);
  };

  const startDrag = (handle: Handle) => (e: ReactPointerEvent<HTMLElement>) => {
    e.stopPropagation();
    e.preventDefault();
    frameRef.current?.setPointerCapture(e.pointerId);
    dragRef.current = { handle, x: e.clientX, y: e.clientY, crop };
  };

  const onDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const box = e.currentTarget.getBoundingClientRect();
    const dx = (e.clientX - drag.x) / box.width;
    const dy = (e.clientY - drag.y) / box.height;
    const c = drag.crop;
    if (drag.handle === "move") {
      setCrop({ ...c, x: clamp(c.x + dx, 0, 1 - c.w), y: clamp(c.y + dy, 0, 1 - c.h) });
      return;
    }
    let { x, y, w, h } = c;
    if (drag.handle.includes("w")) {
      x = clamp(c.x + dx, 0, c.x + c.w - MIN_CROP);
      w = c.x + c.w - x;
    } else {
      w = clamp(c.w + dx, MIN_CROP, 1 - c.x);
    }
    if (drag.handle.includes("n")) {
      y = clamp(c.y + dy, 0, c.y + c.h - MIN_CROP);
      h = c.y + c.h - y;
    } else {
      h = clamp(c.h + dy, MIN_CROP, 1 - c.y);
    }
    setCrop({ x, y, w, h });
  };

  const endDrag = () => {
    dragRef.current = null;
  };

  const changed =
    quarter !== 0 || degrees !== 0 || crop.x !== 0 || crop.y !== 0 || crop.w !== 1 || crop.h !== 1;
  const outW = Math.max(1, Math.round(crop.w * fw));
  const outH = Math.max(1, Math.round(crop.h * fh));

  async function save(asCopy: boolean) {
    if (!img) return;
    setSaving(true);
    setError(null);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = outW;
      canvas.height = outH;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("This browser can't edit images.");
      drawFrame(ctx, img, quarter, degrees, fw, fh, crop.x * fw, crop.y * fh);
      const png = photo.file_key.toLowerCase().endsWith(".png");
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, png ? "image/png" : "image/jpeg", 0.92),
      );
      if (!blob) throw new Error("Couldn't encode the edited image.");
      await onSave(blob, `edited.${png ? "png" : "jpg"}`, asCopy);
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  return (
    <Modal title="Edit photo" onClose={() => !saving && onCancel()}>
      <div className="estimate-form" style={{ marginTop: 0 }}>
        <button type="button" onClick={() => turn(-1)} title="Turn left 90°">⟲ 90°</button>
        <button type="button" onClick={() => turn(1)} title="Turn right 90°">⟳ 90°</button>
        <label className="field">
          Straighten {degrees > 0 ? "+" : ""}{degrees.toFixed(1)}°
          <input type="range" min={-15} max={15} step={0.1} value={degrees}
            onChange={(e) => setDegrees(Number(e.target.value))} />
        </label>
        <button type="button" disabled={!changed}
          onClick={() => { setQuarter(0); setDegrees(0); setCrop(FULL); }}>
          Reset
        </button>
      </div>
      {img ? (
        <div
          ref={frameRef}
          className="editor-frame"
          style={{ width: previewW, aspectRatio: `${previewW} / ${previewH}` }}
          onPointerMove={onDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <canvas ref={canvasRef} />
          <div
            className="crop-box"
            style={{
              left: `${crop.x * 100}%`,
              top: `${crop.y * 100}%`,
              width: `${crop.w * 100}%`,
              height: `${crop.h * 100}%`,
            }}
            onPointerDown={startDrag("move")}
          >
            {(["nw", "ne", "sw", "se"] as const).map((corner) => (
              <span key={corner} className={`crop-handle ${corner}`}
                onPointerDown={startDrag(corner)} />
            ))}
          </div>
        </div>
      ) : (
        !error && <p className="muted">Loading the photo…</p>
      )}
      <p className="muted">
        Drag the box or its corners to crop. Result: {outW} × {outH} px. Replacing overwrites
        this photo; saving as a new photo keeps the original.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="primary" disabled={!img || !changed || saving} onClick={() => save(false)}>
          {saving ? "Saving…" : "Replace photo"}
        </button>
        <button disabled={!img || !changed || saving} onClick={() => save(true)}>
          Save as new photo
        </button>
        <button disabled={saving} onClick={onCancel}>Cancel</button>
      </div>
    </Modal>
  );
}

/** Take photos with a webcam (or a phone's camera) straight into the item. */
export function WebcamCapture({
  onCancel,
  onCapture,
}: {
  onCancel: () => void;
  onCapture: (image: Blob) => Promise<void>;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taken, setTaken] = useState(0);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser can't reach a camera here — camera access needs HTTPS or localhost.");
      return;
    }
    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      })
      .then((s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        stream = s;
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = s;
        video.play().finally(() => setReady(true));
      })
      .catch((e: Error) =>
        setError(
          e.name === "NotAllowedError"
            ? "Camera access was denied — allow it for this site in the browser to use the webcam."
            : `No camera available: ${e.message}`,
        ),
      );
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    setBusy(true);
    setError(null);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d")?.drawImage(video, 0, 0);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.92),
      );
      if (!blob) throw new Error("Couldn't capture a frame.");
      await onCapture(blob);
      setTaken((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Webcam" onClose={() => !busy && onCancel()}>
      {!error && <video ref={videoRef} className="webcam-video" playsInline muted />}
      {error && <p className="error">{error}</p>}
      {taken > 0 && (
        <p className="muted">
          {taken} photo{taken > 1 ? "s" : ""} added — take another, or close.
        </p>
      )}
      <div className="actions">
        <button className="primary" disabled={!ready || busy || !!error} onClick={capture}>
          {busy ? "Saving…" : "Capture"}
        </button>
        <button disabled={busy} onClick={onCancel}>Close</button>
      </div>
    </Modal>
  );
}
