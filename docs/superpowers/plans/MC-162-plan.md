# MC-162 plan: preview attachments in the browser

## Goal
Clicking an attachment, anywhere the app shows one, opens it in a full-screen viewer (image, SVG, PDF, text, audio, video, or a "No preview" card) with a Download button always at hand.

## Architecture
A pure module, `frontend/src/lib/preview.ts`, decides each file's preview kind and turns the three sources (task `Attachment`, message `ImageRef`, unsent `DraftImage`) into one `ViewerFile` shape. One component, `AttachmentViewer` (with `FilePreview` for the body), renders a list of `ViewerFile`s inside a new full-screen `screen` variant of `Dialog`; `Attachments`, `ImageGallery` and `ImageAttach` each keep an `openKey` state and render it. On the backend, `upload_attachment` labels files by their `%PDF-` bytes and `download_attachment` serves checked PDFs inline; nothing else changes.

## Facts checked in the code
- `frontend/src/components/ui/Dialog.tsx`: props `open, onClose, title, children, wide, dismissible, role, bare, describedBy, phoneFull`. It calls `showModal()` in a layout effect, focuses `[data-autofocus]` or itself, handles Escape in its React `onKeyDown` (preventDefault, then `onClose()`), wraps children in `PortalContainerContext.Provider`. It does **not** stop propagation, so today Escape also reaches `TaskDrawer`'s `window` keydown listener (`frontend/src/components/task/TaskDrawer.tsx:21-26`).
- `frontend/src/components/task/Attachments.tsx`: props `items, names?, disabled, onUpload, onDelete`. Holds `SENT_WITH`, `LINKED` and the `SentWith` component. Each file name is `<a href="/api/attachments/{id}">`, so a click downloads it. Used by `TaskView.tsx:253` and `chats/RoundSections.tsx:111`; neither changes.
- `frontend/src/components/images/ImageGallery.tsx`: thumbnail grid of `Open {filename}` buttons, plus its own `Dialog` and a `document` keydown listener for ← →. Used by `ActivityThread.tsx:503,638`, `QuestionCard.tsx:189`, `RoundSections.tsx:76`; none change. `ActivityThread.test.tsx` and `ChatView.test.tsx` only look for the `Open x.png` buttons, which stay.
- `frontend/src/components/images/ImageAttach.tsx`: `draft.items` are `DraftImage = { key, file, preview, id? }` (`frontend/src/lib/images.ts`). `preview` is an object URL, or `""` in jsdom (no `URL.createObjectURL`).
- `frontend/src/lib/images.ts`: `imageUrl(id, inline = true)` gives `/api/attachments/{id}?inline=1` or `/api/attachments/{id}`; `formatSize(bytes)` gives `"388.0 KB"`, `"3.2 MB"`; `ImageRef = { id, filename, size }`.
- `Attachment` = `S["AttachmentOut"]` (`frontend/src/lib/types.ts:30`): `id, task_id, filename, content_type, size, uploaded_by, created_at, image, message_kind, message_id`.
- Themes are CSS variables on `:root[data-theme=…]` (`frontend/src/app/globals.css`), so "always dark" means literal Tailwind colours (`bg-neutral-950`, `text-neutral-100`, `border-white/10`), not theme tokens.
- Backend `backend/app/tasks/activity.py:415-459`: `upload_attachment` calls `save_upload(...)`, which returns `(size, head)` with `HEAD = 16` first bytes (`backend/app/images/files.py:18`), then `sniff(head)` for images. `download_attachment` sends `content_disposition_type="inline" if inline and att.image else "attachment"` and `X-Content-Type-Options: nosniff`. Starlette is 1.9.0 (`backend/uv.lock`); `FileResponse` answers `Range`.
- Backend tests: `backend/tests/tasks/test_attachments.py`, helper `_task(client, db)` makes project PAY and task PAY-1; DB edits in tests end with `await db.commit()`.
- Commands (AGENTS.md), frontend from `frontend/`: `npx vitest run <file>`, `npm test`, `npx tsc --noEmit`, `npx eslint <files>`. Backend from `backend/`: `megoocolab-runner services run test -- uv run pytest tests/tasks/test_attachments.py -q`. Playwright from `frontend/`: `megoocolab-runner services run e2e -- npx playwright test e2e/images.spec.ts --reporter=line`.
- Commit subjects: `type(area): plain sentence`, a body saying why, and the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never change the version files. Don't reformat files you don't otherwise change.

## File map
| File | Change | Responsibility |
|---|---|---|
| `backend/app/tasks/activity.py` | modify | label PDFs by bytes on upload; serve checked PDFs inline |
| `backend/tests/tasks/test_attachments.py` | modify | PDF, fake PDF, never-inline types, Range |
| `frontend/src/lib/preview.ts` | new | `PreviewKind`, `ViewerFile`, `previewKind`, `typeChip`, `SENT_WITH`/`LINKED`/`sentWith`, builders, `loadText` |
| `frontend/src/lib/__tests__/preview.test.ts` | new | tests for the above |
| `frontend/src/components/ui/Dialog.tsx` | modify | `screen` variant |
| `frontend/src/components/ui/__tests__/Dialog.test.tsx` | modify | `screen` tests |
| `frontend/src/components/attachments/AttachmentViewer.tsx` | new | top bar, arrows, keyboard, strip, zoom state, follow/close |
| `frontend/src/components/attachments/FilePreview.tsx` | new | one branch per kind, loading and error states |
| `frontend/src/components/attachments/__tests__/AttachmentViewer.test.tsx` | new | viewer tests |
| `frontend/src/components/task/Attachments.tsx` (+ test) | modify | buttons open the viewer; download icon link; type chips |
| `frontend/src/components/images/ImageGallery.tsx` (+ test) | modify | its own dialog replaced by the viewer |
| `frontend/src/components/images/ImageAttach.tsx` (+ test) | modify | unsent thumbnails open the viewer |
| `frontend/e2e/images.spec.ts` | modify | updated assertions; new PDF + text check |

## Shared contracts (used by steps 2-9)

### `frontend/src/lib/preview.ts`
```ts
import { ApiError } from "@/lib/api";
import { type DraftImage, type ImageRef, imageUrl } from "@/lib/images";
import type { Attachment } from "@/lib/types";

export type PreviewKind = "image" | "pdf" | "text" | "audio" | "video" | "none";

/** One file as the viewer shows it. `src` is what the preview loads; `note` is the grey line under the name. */
export type ViewerFile = {
  key: string; name: string; size: number; kind: PreviewKind; src: string;
  downloadUrl?: string; tabUrl?: string; note?: string;
};

const TEXT_EXT = new Set(["txt","log","md","json","csv","tsv","yaml","yml","xml","html","css","js","ts","tsx","jsx",
  "py","go","rs","sh","sql","toml","ini","diff","patch"]);
const TEXT_TYPES = new Set(["application/json","application/xml","application/javascript","application/x-sh",
  "application/sql","application/toml","application/yaml","application/x-yaml"]);
const ext = (name: string) => /\.([^./]+)$/.exec(name)?.[1].toLowerCase() ?? "";

export function previewKind(contentType: string, filename: string, checkedImage: boolean): PreviewKind {
  const type = contentType.split(";")[0].trim().toLowerCase();
  if (checkedImage || type === "image/svg+xml") return "image";
  if (type === "application/pdf") return "pdf";
  // before the type: browsers report .ts as video (MPEG transport stream)
  if (TEXT_EXT.has(ext(filename))) return "text";
  if (type.startsWith("text/") || TEXT_TYPES.has(type)) return "text";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("video/")) return "video";
  return "none";
}

/** The short type label shown instead of a picture: "PDF", "TXT", "MP4"; "FILE" without an extension. */
export const typeChip = (name: string) => ext(name).slice(0, 4).toUpperCase() || "FILE";

// moved here from Attachments.tsx, unchanged
export const SENT_WITH: Record<string, string> = { comment: "comment", agent_message: "message", answer: "answer",
  change_request: "change request", first_message: "first message", nudge: "message" };
export const LINKED = new Set(["comment", "agent_message", "answer"]);

/** "Sara Kim's comment": what the attachment was sent with, or null for a file attached directly. */
export function sentWith(a: Attachment, names?: Map<string, string>): string | null {
  if (!a.message_kind) return null;
  return `${(a.uploaded_by && names?.get(a.uploaded_by)) || "someone"}'s ${SENT_WITH[a.message_kind] ?? "message"}`;
}

export function fromAttachment(a: Attachment, names?: Map<string, string>): ViewerFile {
  const kind = previewKind(a.content_type, a.filename, a.image);
  const inline = a.image || kind === "pdf"; // the two types the server serves inline
  const what = sentWith(a, names);
  return { key: a.id, name: a.filename, size: a.size, kind, src: imageUrl(a.id, inline),
    downloadUrl: imageUrl(a.id, false), tabUrl: inline ? imageUrl(a.id) : undefined,
    note: what ? `from ${what}` : undefined };
}

export const fromImageRef = (img: ImageRef): ViewerFile => ({ key: img.id, name: img.filename, size: img.size,
  kind: "image", src: imageUrl(img.id), downloadUrl: imageUrl(img.id, false), tabUrl: imageUrl(img.id) });

export const fromDraft = (d: DraftImage): ViewerFile => ({ key: d.key, name: d.file.name, size: d.file.size,
  kind: "image", src: d.preview, note: "Not sent yet" });

export const TEXT_LIMIT = 1024 * 1024;
export type LoadedText = { text: string; cut: boolean; binary: boolean };

/** Reads at most the first 1 MB of a file and stops. A NUL byte means it isn't text. Throws ApiError on a non-2xx. */
export async function loadText(url: string, signal?: AbortSignal): Promise<LoadedText> {
  const res = await fetch(url, { credentials: "include", signal });
  if (!res.ok) throw new ApiError(res.status, "load_failed");
  const chunks: Uint8Array[] = [];
  let got = 0;
  let cut = false;
  if (res.body) {
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.length;
      if (got > TEXT_LIMIT) { cut = true; void reader.cancel(); break; }
    }
  } else {
    const all = new Uint8Array(await res.arrayBuffer());
    chunks.push(all);
    got = all.length;
    cut = got > TEXT_LIMIT;
  }
  const bytes = new Uint8Array(Math.min(got, TEXT_LIMIT));
  let at = 0;
  for (const c of chunks) { const part = c.subarray(0, bytes.length - at); bytes.set(part, at); at += part.length; if (at >= bytes.length) break; }
  if (bytes.includes(0)) return { text: "", cut: false, binary: true };
  return { text: new TextDecoder().decode(bytes), cut, binary: false };
}
```

### `AttachmentViewer` (`frontend/src/components/attachments/AttachmentViewer.tsx`)
```ts
export function AttachmentViewer(props: {
  files: ViewerFile[];
  openKey: string | null;        // null: closed
  onOpen: (key: string) => void; // arrows, keys and the strip call it
  onClose: () => void;
}): JSX.Element | null
```
- Returns null when `openKey` is null or not in `files`. An effect calls `onClose()` when `openKey` is set and no file has that key (the open file left the list).
- `<Dialog open screen title={file.name} onClose={onClose}>`.
- Accessible names (the tests rely on them): dialog = file name; `Previous file`, `Next file`, `Zoom out`, `Zoom in`, the zoom label text `100%`; link `Open in new tab` (`target="_blank" rel="noopener noreferrer"`, only when `tabUrl`); link `Download` (only when `downloadUrl` and the file is not gone); button `Close`; counter text `2 of 5`; strip `<ul aria-label="Files">` of buttons `Show {name}` with `aria-current="true"` on the open one.
- Zoom state: `const [zoom, setZoom] = useState({ key: "", pct: 100 })`; `pct = zoom.key === file.key ? zoom.pct : 100` (resets on the next file without an effect); `zoomTo(p) = setZoom({ key: file.key, pct: Math.min(300, Math.max(50, p)) })`; − / + step 25; `Zoom out` disabled at 50, `Zoom in` disabled at 300. Zoom controls only for `kind === "image"`, class `max-md:hidden`; `Open in new tab` also `max-md:hidden`.
- Gone state: `const [gone, setGone] = useState<string | null>(null)`; FilePreview calls `onGone()` → `setGone(file.key)`; the top-bar Download is hidden while `gone === file.key`.
- Keyboard: while open, a `document` keydown listener: ArrowLeft / ArrowRight call `onOpen` with the previous / next key, wrapping; ignored when `e.target` is an `audio`, `video`, `input` or `textarea` element, and when there is one file.
- One file: no arrows, no counter, no strip.

### `FilePreview` (`frontend/src/components/attachments/FilePreview.tsx`)
```ts
export function FilePreview(props: { file: ViewerFile; zoom: number; onZoom: (pct: number) => void; onGone: () => void }): JSX.Element
```
Rendered as `<FilePreview key={file.key} … />` so its state resets per file. State `status: "loading" | "ready" | "failed" | "gone"` (starts `"loading"`, except `none` which starts `"ready"`). Texts (exact):
- loading: `<p role="status">Loading…</p>` overlaid until the element's `onLoad` / `onLoadedMetadata` or the text arrives;
- failed: `This file can't be shown here.` plus the body Download link;
- gone: `This file is no longer available.`, no Download;
- none (and text that turned out binary): `No preview for this type of file` plus the body Download link;
- pdf when `navigator.pdfViewerEnabled === false`: `This browser can't show PDFs in the page`, an `Open in new tab` link (tabUrl) and the body Download link;
- text cut: `Showing the first 1 MB of {formatSize(file.size)}. Download the file to see all of it.`
- The body Download link: visible text `Download`, `aria-label={`Download ${file.name}`}`, `href={file.downloadUrl}`; only when `downloadUrl`.

On a load error (`onError` of img/audio/video, or a text fetch that throws a non-404, non-abort error): when `file.downloadUrl` is set, `fetch(file.downloadUrl, { headers: { Range: "bytes=0-0" }, credentials: "include" })`; 404 → `gone` + `onGone()`, anything else (or a network error) → `failed`. Without `downloadUrl` (an unsent image) → `failed` at once. A text fetch that throws `ApiError` with status 404 → `gone` + `onGone()` directly.

Elements per kind:
- image: `<img src alt={name} data-zoom={zoom} onClick={() => onZoom(zoom === 100 ? 200 : 100)}>`; at 100 `max-h-full max-w-full object-contain cursor-zoom-in`; otherwise `max-h-none max-w-none cursor-zoom-out` with `style={{ height: `${zoom}%` }}`, inside an `overflow-auto` body.
- pdf: `<iframe title={name} src={file.src} className="size-full border-0 bg-white">`.
- text: an effect with an `AbortController` calls `loadText(file.src, signal)`; cleanup aborts it. `<pre className="whitespace-pre-wrap break-words font-mono text-xs">`.
- audio: `<audio controls src>`; video: `<video controls preload="metadata" src className="max-h-full max-w-full">`.

## Steps

### 1. Backend: label PDFs by their bytes and serve checked PDFs inline
Files: `backend/app/tasks/activity.py`, `backend/tests/tasks/test_attachments.py`.

Tests first (add to `test_attachments.py`, reuse `_task`):
```python
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

async def test_real_pdf_is_stored_as_pdf_and_served_inline(client, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("r.pdf", PDF, "application/octet-stream")})).json()
    assert att["content_type"] == "application/pdf" and att["image"] is False
    shown = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["content-type"] == "application/pdf"
    assert shown.headers["x-content-type-options"] == "nosniff"
    plain = await client.get(f"/api/attachments/{att['id']}")
    assert plain.headers["content-disposition"].startswith("attachment")

async def test_fake_pdf_is_stored_as_octet_stream_and_stays_a_download(client, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("x.pdf", b"<html>hi</html>", "application/pdf")})).json()
    assert att["content_type"] == "application/octet-stream"
    r = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert r.headers["content-disposition"].startswith("attachment")

async def test_pdf_label_without_pdf_bytes_stays_a_download(client, db):
    # a file uploaded before this change, labelled by the browser only
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("old.pdf", b"not a pdf", "text/plain")})).json()
    row = (await db.execute(select(Attachment))).scalar_one()
    row.content_type = "application/pdf"
    await db.commit()
    r = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert r.headers["content-disposition"].startswith("attachment")

@pytest.mark.parametrize("name,body,ctype", [
    ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
    ("a.html", b"<script>alert(1)</script>", "text/html"),
    ("a.txt", b"hello", "text/plain"),
])
async def test_svg_html_and_text_are_never_inline(client, db, name, body, ctype):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": (name, body, ctype)})).json()
    r = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"

async def test_range_request_answers_206(client, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("v.mp4", b"0123456789", "video/mp4")})).json()
    r = await client.get(f"/api/attachments/{att['id']}", headers={"Range": "bytes=2-5"})
    assert r.status_code == 206 and r.content == b"2345"
```
(add `import pytest` at the top). Run `megoocolab-runner services run test -- uv run pytest tests/tasks/test_attachments.py -q` from `backend/`: the first two fail (content type is `application/octet-stream` / `application/pdf`); the others pass already (they pin behaviour).

Implementation in `activity.py`:
```python
PDF_MAGIC = b"%PDF-"

def _upload_type(head: bytes, image_type: str | None, claimed: str | None) -> str:
    """The type a file is stored with: an image or a PDF by its bytes; a file that only claims to be a PDF is not one."""
    if image_type:
        return image_type
    if head.startswith(PDF_MAGIC):
        return "application/pdf"
    claimed = (claimed or "application/octet-stream")[:200]
    return "application/octet-stream" if claimed.split(";")[0].strip().lower() == "application/pdf" else claimed

def _is_pdf(att: Attachment, path: Path) -> bool:
    """A file labelled PDF whose bytes start like one, read now: uploads from before the label was checked work too."""
    if att.content_type != "application/pdf":
        return False
    with path.open("rb") as f:
        return f.read(len(PDF_MAGIC)) == PDF_MAGIC
```
`upload_attachment`: `content_type=_upload_type(head, image_type, file.content_type)`. `download_attachment`: `shown = inline and (att.image or _is_pdf(att, path))`, then `content_disposition_type="inline" if shown else "attachment"`; update its docstring to say "an image or a PDF checked by its bytes". `download_by_link` unchanged. Re-run: all pass. Then the whole file and `uv run ruff check app/tasks/activity.py tests/tasks/test_attachments.py`.

Commit: `feat(attachments): PDFs are recognised by their bytes and can be shown in the page`.

### 2. Frontend: preview kinds, builders and text loading (`lib/preview.ts`)
Files: new `frontend/src/lib/preview.ts` (exactly the contract above), new `frontend/src/lib/__tests__/preview.test.ts`.

Tests first:
- `previewKind` table (`it.each`): `("image/png","a.png",true)→image`, `("image/svg+xml","a.svg",false)→image`, `("image/png","fake.png",false)→none`, `("application/pdf","r.pdf",false)→pdf`, `("video/mp2t","main.ts",false)→text`, `("text/plain","notes",false)→text`, `("application/json","data",false)→text`, `("text/html; charset=utf-8","page.html",false)→text`, `("application/octet-stream","build.log",false)→text`, `("audio/mpeg","a.mp3",false)→audio`, `("video/mp4","a.mp4",false)→video`, `("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","estimate.xlsx",false)→none`, `("application/octet-stream","blob",false)→none`.
- `typeChip`: `report.pdf→PDF`, `clip.MP4→MP4`, `archive.tar.gz→GZ`, `Makefile→FILE`.
- `fromAttachment`: a checked PNG gets `src "/api/attachments/i1?inline=1"`, `tabUrl` same, `downloadUrl "/api/attachments/i1"`; a PDF gets `?inline=1` src and a tabUrl; a text file gets `src "/api/attachments/a1"` and no tabUrl; a comment image with `names` gets `note "from Sara Kim's comment"`; without `message_kind`, no note. Use the `att()` factory from `Attachments.test.tsx`.
- `fromImageRef` and `fromDraft` (`new File(["x"], "shot.png", { type: "image/png" })`, preview `"blob:1"`): draft has `note "Not sent yet"`, no `downloadUrl`, no `tabUrl`, `src "blob:1"`.
- `loadText` with `vi.stubGlobal("fetch", …)` returning `new Response(...)`: a short text → `{ text, cut: false, binary: false }`; `"a".repeat(TEXT_LIMIT + 10)` → `cut: true`, `text.length === TEXT_LIMIT`; bytes with a 0 → `binary: true`; a 404 response → rejects with an `ApiError` whose `status` is 404. `afterEach(() => vi.unstubAllGlobals())`.

Run `npx vitest run src/lib/__tests__/preview.test.ts` from `frontend/`: fails (module missing). Write the module; re-run: passes. Then `npx tsc --noEmit`, `npx eslint src/lib/preview.ts src/lib/__tests__/preview.test.ts`. Don't touch `Attachments.tsx` yet (step 6 moves `SENT_WITH` out of it).

Commit: `feat(attachments): decide how each kind of file is previewed`.

### 3. Dialog: a full-screen `screen` variant
Files: `frontend/src/components/ui/Dialog.tsx`, `frontend/src/components/ui/__tests__/Dialog.test.tsx`.

Tests first (append to `Dialog.test.tsx`):
- `"screen fills the window with no title bar"`: render `<Dialog open screen title="photo.png" onClose={vi.fn()}><p>body</p></Dialog>`; the dialog named `photo.png` exists, `queryByRole("button", { name: "Close" })` is null, `queryByRole("heading")` is null, and `dialog.className` does not contain `card`.
- `"screen keeps Escape from reaching listeners outside"`: add `const outer = vi.fn()` with `window.addEventListener("keydown", outer)` (remove it at the end); `fireEvent.keyDown(dialog, { key: "Escape" })`; `onClose` called once, `outer` not called.
- `"a normal dialog still lets Escape through"`: same with no `screen`: `outer` called (pins that other dialogs are unchanged).

Run `npx vitest run src/components/ui/__tests__/Dialog.test.tsx`: the screen tests fail. Implementation:
- New prop `screen = false`, doc comment: `/** Fill the window with no card, title bar or padding: the content brings everything (the attachment viewer). Escape stops here, so a drawer's window listener behind it doesn't close too. */`.
- In `onKeyDown` Escape branch: `if (screen) e.stopPropagation();` before `onClose()`.
- className: when `screen`, use `fixed inset-0 m-0 h-dvh max-h-none w-full max-w-none overflow-hidden border-0 bg-neutral-950 p-0 text-neutral-100 focus:outline-none backdrop:bg-black/80` instead of the card classes.
- Title bar rendered only when `!bare && !screen`; children wrapper: `screen ? children : <div className={bare ? "p-5" : "p-4"}>{children}</div>`, still inside `PortalContainerContext.Provider`.

Re-run: passes. `npx tsc --noEmit`, `npx eslint` on both files.

Commit: `feat(ui): a full-screen dialog variant for the attachment viewer`.

### 4. AttachmentViewer: top bar, navigation, keyboard, strip, images and zoom
Files: new `frontend/src/components/attachments/AttachmentViewer.tsx`, new `frontend/src/components/attachments/FilePreview.tsx` (image branch, loading and `none` card only in this step; other kinds render the `none` card for now), new `frontend/src/components/attachments/__tests__/AttachmentViewer.test.tsx`. Contracts: see "AttachmentViewer" and "FilePreview" above.

Test harness:
```tsx
function Harness({ files, start }: { files: ViewerFile[]; start: string | null }) {
  const [open, setOpen] = useState<string | null>(start);
  return <AttachmentViewer files={files} openKey={open} onOpen={setOpen} onClose={() => setOpen(null)} />;
}
```
Files built with `fromAttachment` from an `att()` factory: `a.png` (image), `b.png` (image), `notes.txt` (text), `estimate.xlsx` (none).

Tests first:
- opens on the given file: dialog named `b.png`, text `2 of 4`, the size, links `Download` (`/api/attachments/b`) and `Open in new tab` (`/api/attachments/b?inline=1`, `target="_blank"`).
- `Next file` / `Previous file` and ArrowRight / ArrowLeft (fired on the dialog) move and wrap (`4 of 4` → ArrowRight → `1 of 4`).
- the strip: `Show estimate.xlsx` opens it; the open one has `aria-current="true"`; image buttons hold an `<img>`, others the chip text (`XLSX`, `TXT`).
- Escape closes and does not reach a `window` keydown listener.
- zoom: `100%` shown; `Zoom in` twice → `150%` and `data-zoom="150"` on the img; clicking the img → `100%`… (`zoom === 100 ? 200 : 100`: from 150 goes to 100, from 100 to 200); `Zoom out` is disabled at 50%, `Zoom in` at 300%; moving to the next file resets to `100%`.
- `none` file: text `No preview for this type of file`, a `Download estimate.xlsx` link, no `Open in new tab`, no zoom buttons.
- one file: no `Next file`, no counter, no `Files` list.
- the open file leaves the list: `rerender` with the file removed → dialog gone.
- "Loading…" shows until `fireEvent.load(img)`.

Run `npx vitest run src/components/attachments/__tests__/AttachmentViewer.test.tsx`: fails (missing module). Build the components. Layout: top bar `flex items-center gap-2 border-b border-white/10 px-3 py-2` with name `h2 truncate text-sm font-bold` and note `p text-xs text-neutral-400`; body `relative flex min-h-0 flex-1 items-center justify-center overflow-auto`; arrows absolutely placed at the middle sides, `max-md:top-auto max-md:bottom-3` on phones; strip `flex gap-1.5 overflow-x-auto border-t border-white/10 p-2`, items `size-12`. Root inside the dialog: `flex h-full flex-col`. Re-run: passes. `npx tsc --noEmit`, `npx eslint src/components/attachments`.

Commit: `feat(attachments): a full-screen viewer for images, with zoom and the other files a step away`.

### 5. FilePreview: PDF, text, audio, video and the error states
Files: `frontend/src/components/attachments/FilePreview.tsx`, `frontend/src/components/attachments/__tests__/AttachmentViewer.test.tsx`.

Tests first (same harness; `afterEach` unstubs globals and resets `navigator.pdfViewerEnabled`):
- pdf: an `iframe` with `title="r.pdf"` and `src="/api/attachments/p?inline=1"`; `Open in new tab` shown.
- pdf with `Object.defineProperty(navigator, "pdfViewerEnabled", { value: false, configurable: true })`: text `This browser can't show PDFs in the page`, no iframe, an `Open in new tab` and a `Download r.pdf` link.
- text: stub `fetch` → `new Response("hello")`; `findByText("hello")` inside a `pre`; fetch called with `/api/attachments/a1`.
- text over 1 MB (size 3.2 MB): text `Showing the first 1 MB of 3.2 MB. Download the file to see all of it.`
- text with a NUL byte: `No preview for this type of file`.
- moving on while text loads aborts it: the stubbed fetch records `init.signal`; after ArrowRight, `signal.aborted` is true.
- audio: an `audio` element with `controls`; video: a `video` with `controls` and `preload="metadata"`.
- image error, server 404: fire `error` on the img; the Range fetch (`headers.Range === "bytes=0-0"`) answers 404 → `This file is no longer available.`, and no link named `Download` (top bar) nor `Download x`.
- image error, server 200: → `This file can't be shown here.` and a Download link.
- text fetch 404 → `This file is no longer available.`

Run the viewer test file: the new tests fail. Implement the branches per the FilePreview contract; a text effect: `const ctl = new AbortController(); loadText(file.src, ctl.signal).then(r => …, err => { if (ctl.signal.aborted) return; if (err instanceof ApiError && err.status === 404) { setStatus("gone"); onGone(); } else fail(); }); return () => ctl.abort();` (setState only in the async callbacks). Re-run: passes; then `npx tsc --noEmit`, `npx eslint src/components/attachments`.

Commit: `feat(attachments): the viewer shows PDFs, text, audio and video, and says when a file is gone`.

### 6. Attachments list: open the viewer, download icon, type chips
Files: `frontend/src/components/task/Attachments.tsx`, `frontend/src/components/task/__tests__/Attachments.test.tsx`.

Tests first:
- update the first test: the thumbnail is `container.querySelector("img")` with `src "/api/attachments/i1?inline=1"` and `alt ""`; `container.querySelectorAll("img")` has length 1; the `Sara Kim's comment` link stays.
- `"the file name opens the viewer on the whole list"`: click button `notes.txt` → dialog named `notes.txt` with `2 of 2` (stub `fetch` → `new Response("hi")`).
- `"each file has a download link"`: link `Download notes.txt` with `href "/api/attachments/a1"`, shown also when `disabled`.
- `"files that aren't images show their type"`: `report.pdf` row shows `PDF`.
Run `npx vitest run src/components/task/__tests__/Attachments.test.tsx`: fails.

Implementation:
- Import `SENT_WITH`-free: delete the local `SENT_WITH` / `LINKED`, import `LINKED`, `sentWith`, `fromAttachment`, `typeChip` from `@/lib/preview`; `SentWith` builds `what` with `sentWith(a, names)` and returns null when it is null.
- `const [open, setOpen] = useState<string | null>(null)`; `const files = useMemo(() => items.map((a) => fromAttachment(a, names)), [items, names])`.
- Thumbnail: `<button type="button" tabIndex={-1} aria-hidden onClick={() => setOpen(a.id)} className="size-8 shrink-0 overflow-hidden rounded border border-line">` holding `<img alt="" …>` for `a.image`, else `<span className="flex size-full items-center justify-center bg-surface-2 text-[9px] font-bold text-muted-foreground">{typeChip(a.filename)}</span>` (replaces the Paperclip icon; drop that import).
- Name: `<button type="button" className="block max-w-full truncate text-left hover:text-cyan-ink" onClick={() => setOpen(a.id)}>{a.filename}</button>`.
- Before the delete button, always: `<Hint label={`Download ${a.filename}`}><a href={imageUrl(a.id, false)} className="icon-btn h-6 w-6" aria-label={`Download ${a.filename}`}><Download size={12} aria-hidden /></a></Hint>` (`Download` from lucide-react).
- After the list: `<AttachmentViewer files={files} openKey={open} onOpen={setOpen} onClose={() => setOpen(null)} />`.
Re-run: passes. `npm test` (whole suite: TaskView / RoundSections tests must stay green), `npx tsc --noEmit`, `npx eslint` on both files.

Commit: `feat(attachments): the Attachments list opens files in the viewer, with a download button on each`.

### 7. ImageGallery: use the viewer
Files: `frontend/src/components/images/ImageGallery.tsx`, `frontend/src/components/images/__tests__/ImageGallery.test.tsx`.

Tests first: change the second test to the new names: `Previous image` → `Previous file`; keep `2 of 3`, `388.0 KB`, the `Download` link `/api/attachments/i2`, ArrowRight to `design.png`, Escape closing. Add: `Open in new tab` has `href "/api/attachments/i2?inline=1"`; the `Files` strip lists three `Show …` buttons. Run `npx vitest run src/components/images/__tests__/ImageGallery.test.tsx`: fails on `Previous file`.

Implementation: remove its `Dialog`, `ChevronLeft/Right`, the keydown effect and `step`; `const [open, setOpen] = useState<string | null>(null)`; `const files = useMemo(() => images.map(fromImageRef), [images])`; thumbnails call `setOpen(img.id)`; render `<AttachmentViewer files={files} openKey={open} onOpen={setOpen} onClose={() => setOpen(null)} />` after the grid. Keep the early `return null` for no images after the hooks. Re-run; `npm test` (ActivityThread, ChatView, QuestionCard tests stay green); tsc; eslint.

Commit: `feat(images): a message's images open in the full-screen viewer`.

### 8. ImageAttach: preview unsent images
Files: `frontend/src/components/images/ImageAttach.tsx`, `frontend/src/components/images/__tests__/ImageAttach.test.tsx`.

Tests first: `"opens an image not sent yet, with no download"`: add `png("shot.png")` through the file input; click button `Open shot.png`; dialog named `shot.png` shows `Not sent yet`, has no link named `Download`, no `Open in new tab`; Escape closes it and the `Remove shot.png` button is still there. Add a second image and check `2 of 2` after opening the second. Run `npx vitest run src/components/images/__tests__/ImageAttach.test.tsx`: fails.

Implementation: `const [open, setOpen] = useState<string | null>(null)`; `const files = useMemo(() => draft.items.map(fromDraft), [draft.items])`; inside each `li`, wrap the preview in `<button type="button" aria-label={`Open ${i.file.name}`} onClick={() => setOpen(i.key)} className="block size-full cursor-zoom-in">` (the img and the upload bar move inside it); the ✕ Remove button stays after it (absolute, on top). Render `<AttachmentViewer …>` at the end of the component's root `div`. A removed image that was open closes the viewer (the viewer's follow rule). Re-run; `npm test`; tsc; eslint.

Commit: `feat(images): images added to a message can be checked full screen before sending`.

### 9. Browser tests: updated image checks and a PDF + text check
File: `frontend/e2e/images.spec.ts`.

- In the existing test: the Attachments assertion becomes `await expect(attachments.getByRole("button", { name: "screenshot.png", exact: true })).toBeVisible();`. The chat viewer block keeps `Open screenshot.png`, the dialog name and `getByRole("link", { name: "Download", exact: true })`.
- New test (no runner needed), see "New e2e test" below. Update the file's top comment to mention it, and that it creates project PRV.
Run from `frontend/`: `megoocolab-runner services run e2e -- npx playwright test e2e/images.spec.ts --reporter=line`; both tests pass. Then `npx tsc --noEmit` and `npx eslint e2e/images.spec.ts`.

Commit: `test(e2e): PDFs and text files open in the viewer from a task's Attachments`.

### New e2e test (step 9)
```ts
const MIN_PDF = "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" +
  "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n";

test("a PDF and a text file open in the viewer from a task's Attachments", async ({ page }) => {
  await setupOrSignIn(page);
  const request = page.request;
  const team = await post<{ id: string }>(request, "/api/teams", { name: "Preview Team", description: "" });
  await post(request, "/api/projects", { key: "PRV", name: "Preview", description: "", team_ids: [team.id] });
  const task = await post<{ key: string; number: number }>(request, "/api/projects/PRV/tasks", { title: "Files", type: "task" });
  const upload = async (name: string, mimeType: string, body: string) => {
    const r = await request.post(`/api/tasks/${task.key}/attachments`, {
      multipart: { file: { name, mimeType, buffer: Buffer.from(body) } }, headers: WEB });
    expect(r.ok(), await r.text()).toBeTruthy();
    return (await r.json()) as { id: string };
  };
  const pdf = await upload("report.pdf", "application/pdf", MIN_PDF);
  await upload("notes.txt", "text/plain", "hello from the notes");

  await page.goto(`/projects/PRV/tasks/${task.number}`);
  const attachments = page.locator("section", { has: page.getByRole("heading", { name: "Attachments" }) });
  await attachments.getByRole("button", { name: "report.pdf", exact: true }).click();
  const viewer = page.getByRole("dialog", { name: "report.pdf" });
  const canShow = await page.evaluate(() => navigator.pdfViewerEnabled);
  if (canShow) await expect(viewer.locator(`iframe[src="/api/attachments/${pdf.id}?inline=1"]`)).toBeVisible();
  else await expect(viewer.getByText("This browser can't show PDFs in the page")).toBeVisible();
  await expect(viewer.getByRole("link", { name: "Download", exact: true })).toHaveAttribute("href", `/api/attachments/${pdf.id}`);
  await page.keyboard.press("ArrowRight");
  const text = page.getByRole("dialog", { name: "notes.txt" });
  await expect(text.getByText("hello from the notes")).toBeVisible();
  await expect(text.getByRole("link", { name: "Download", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(text).toBeHidden();
});
```

## Final verification
From `backend/`:
- `megoocolab-runner services run test -- uv run pytest -q -n auto`
- `uv run ruff check app tests`

From `frontend/`:
- `npx tsc --noEmit`
- `npx eslint src/lib/preview.ts src/components/attachments src/components/ui/Dialog.tsx src/components/task/Attachments.tsx src/components/images e2e/images.spec.ts`
- `npm test`
- `megoocolab-runner services run e2e -- npx playwright test --reporter=line`

No `npm run gen:api` is needed: `AttachmentOut` and the endpoints are unchanged.

## Requirement coverage
- Full-screen viewer, always dark, phone layout: steps 3, 4.
- Images (zoom), SVG, PDF (+ no-viewer card), text (1 MB, binary), audio, video, none: steps 2, 4, 5.
- Download everywhere, Open in new tab for checked images and PDFs only, none for unsent images: steps 2, 4, 6, 8.
- Attachments list (task page, drawer, chat rounds), message images, unsent images: steps 6, 7, 8.
- Keyboard and Escape not closing the drawer: steps 3, 4.
- Gone / unreadable / loading / list changes / one file: steps 4, 5.
- Server: PDF by bytes, inline only for checked images and PDFs, nosniff, Range pinned: step 1.
- Playwright: step 9.
