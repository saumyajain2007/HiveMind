/** Download helpers: CSV of numbers, and a chart's SVG as .svg or .png with theme colours inlined. */

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadCsv(header: string[], rows: (string | number)[][], filename: string): void {
  const body = [header, ...rows].map((r) => r.join(",")).join("\n");
  download(new Blob([body + "\n"], { type: "text/csv" }), filename);
}

const PROPS = [
  "fill",
  "stroke",
  "stroke-width",
  "stroke-dasharray",
  "opacity",
  "fill-opacity",
  "stroke-opacity",
  "font-family",
  "font-size",
];

/** Copy of the first <svg> under `root` with computed styles inlined (CSS variables resolved). */
function standaloneSvg(root: HTMLElement): { svg: SVGSVGElement; w: number; h: number } | null {
  const src = root.querySelector("svg");
  if (!src) return null;
  const clone = src.cloneNode(true) as SVGSVGElement;
  const a = [src, ...src.querySelectorAll("*")];
  const b = [clone, ...clone.querySelectorAll("*")];
  a.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const target = b[i] as SVGElement;
    for (const p of PROPS) target.style.setProperty(p, cs.getPropertyValue(p));
  });
  const w = src.clientWidth || Number(src.getAttribute("width"));
  const h = src.clientHeight || Number(src.getAttribute("height"));
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(w));
  clone.setAttribute("height", String(h));
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  bg.setAttribute("width", "100%");
  bg.setAttribute("height", "100%");
  bg.setAttribute("fill", getComputedStyle(document.body).backgroundColor);
  clone.insertBefore(bg, clone.firstChild);
  return { svg: clone, w, h };
}

export function exportSvg(root: HTMLElement | null, filename: string): void {
  const s = root && standaloneSvg(root);
  if (!s) return;
  download(
    new Blob([new XMLSerializer().serializeToString(s.svg)], { type: "image/svg+xml" }),
    filename,
  );
}

export function exportPng(root: HTMLElement | null, filename: string, scale = 2): void {
  const s = root && standaloneSvg(root);
  if (!s) return;
  const img = new Image();
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(s.svg)], { type: "image/svg+xml" }),
  );
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = s.w * scale;
    canvas.height = s.h * scale;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    URL.revokeObjectURL(url);
    canvas.toBlob((b) => b && download(b, filename), "image/png");
  };
  img.src = url;
}
