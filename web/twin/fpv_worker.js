// JPEG encoder for the FPV feed, off the main thread. JPEG encode takes
// 15-140 ms on this laptop depending on load; on the main thread that alone
// capped the feed at ~5 fps and stole time from the render loop.
//
// In:  {id, px: ArrayBuffer (transferred), w, h, quality}
//      px = raw RGBA read back from a WebGL render target: bottom row first,
//      linear colour (three.js writes working-space colour into render targets).
// Out: {id, jpeg: ArrayBuffer | null, px (returned for reuse), bmp: ImageBitmap for the preview}

// Linear -> sRGB, the same transfer three.js applies when drawing to the screen.
const SRGB = new Uint8ClampedArray(256);
for (let i = 0; i < 256; i++) {
  const c = i / 255;
  SRGB[i] = Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055));
}

let canvas = null, ctx = null, img = null;

onmessage = async (e) => {
  const { id, px, w, h, quality } = e.data;
  try {
    if (!canvas || canvas.width !== w || canvas.height !== h) {
      canvas = new OffscreenCanvas(w, h);
      // willReadFrequently keeps this canvas in CPU memory. A GPU-backed one
      // would upload the pixels and read them back again for the encode,
      // queueing behind the 3D view on the GPU (measured 140-200 ms/frame).
      ctx = canvas.getContext("2d", { willReadFrequently: true });
      img = ctx.createImageData(w, h);
    }
    // Flip rows (GL is bottom-up) and encode colour in one pass.
    const src = new Uint8Array(px), dst = img.data, row = w * 4;
    for (let y = 0; y < h; y++) {
      let s = (h - 1 - y) * row, d = y * row;
      for (const end = d + row; d < end; d += 4, s += 4) {
        dst[d] = SRGB[src[s]]; dst[d + 1] = SRGB[src[s + 1]]; dst[d + 2] = SRGB[src[s + 2]]; dst[d + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    // convertToBlob snapshots the canvas at the call, so the next message
    // may overwrite it while this encode is still running.
    const blobP = canvas.convertToBlob({ type: "image/jpeg", quality });
    const bmp = await createImageBitmap(canvas);
    const jpeg = await (await blobP).arrayBuffer();
    postMessage({ id, jpeg, px, bmp }, [jpeg, px, bmp]);
  } catch (err) {
    postMessage({ id, jpeg: null, px, error: String(err) }, [px]);
  }
};
