/** Client-side image compression for chat + label-photo uploads.
 *
 * Takes a File from <input type="file">, decodes it via an off-DOM <img>,
 * rescales so the longest edge is <= maxEdge, and re-encodes as JPEG at
 * the given quality. Returns both a display data URL and the raw base64
 * (without the data: prefix) ready for a Bedrock image block.
 *
 * We don't handle arbitrary EXIF rotation — drawImage honors orientation on
 * modern Safari/Chrome. Very old devices may produce sideways output; this
 * is acceptable for v1 (the model still sees the content).
 */

export interface CompressedImage {
  /** Full data URL for <img src> thumbnails. */
  dataUrl: string;
  /** Raw base64 body (no data: prefix) — what Bedrock wants. */
  base64: string;
  /** MIME type of the encoded output. Always image/jpeg. */
  mediaType: "image/jpeg";
  /** Size of the encoded bytes (not the base64 string). */
  bytes: number;
}

const DEFAULT_MAX_EDGE = 1024;
const DEFAULT_QUALITY = 0.7;

export async function compressImage(
  file: File,
  maxEdge: number = DEFAULT_MAX_EDGE,
  quality: number = DEFAULT_QUALITY,
): Promise<CompressedImage> {
  const bitmap = await loadImage(file);
  const { canvas, width, height } = scaleToCanvas(bitmap, maxEdge);

  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2d context unavailable");
  ctx.drawImage(bitmap, 0, 0, width, height);

  const blob = await canvasToBlob(canvas, "image/jpeg", quality);
  const base64 = await blobToBase64(blob);
  const dataUrl = `data:image/jpeg;base64,${base64}`;

  return {
    dataUrl,
    base64,
    mediaType: "image/jpeg",
    bytes: blob.size,
  };
}

async function loadImage(file: File): Promise<HTMLImageElement> {
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("couldn't decode image"));
      img.src = url;
    });
  } finally {
    // Release the blob URL once decode finished — drawImage has the pixels already.
    queueMicrotask(() => URL.revokeObjectURL(url));
  }
}

function scaleToCanvas(img: HTMLImageElement, maxEdge: number) {
  const w0 = img.naturalWidth || img.width;
  const h0 = img.naturalHeight || img.height;
  const scale = Math.min(1, maxEdge / Math.max(w0, h0));
  const width = Math.max(1, Math.round(w0 * scale));
  const height = Math.max(1, Math.round(h0 * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return { canvas, width, height };
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("canvas encoding failed"))),
      type,
      quality,
    );
  });
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("unexpected FileReader result"));
        return;
      }
      // result is "data:image/jpeg;base64,...." — strip the prefix.
      const idx = result.indexOf(",");
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = () => reject(reader.error || new Error("FileReader failed"));
    reader.readAsDataURL(blob);
  });
}
