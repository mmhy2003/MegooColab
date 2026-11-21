# MC-162 design: preview attachments in the browser

## Goal
Clicking an attachment opens it in a full-screen viewer instead of downloading it: images, SVG, PDF, text files, audio and video are shown in the page, and every file keeps a Download button. The same viewer opens everywhere the app shows attachments.

## Decisions
- **Viewer style: full-screen overlay** (chosen from mockup v1). Rejected: a larger version of today's dialog card (too little room for PDFs, cramped on a phone) and opening the file in place inside the list (small, pushes the page down).
- **File types: everything the browser can show itself** (chosen). Rejected: images only; Office files (they need a conversion step on the server).
- **Where it opens** (mockup v2, approved "as shown"):
  1. the Attachments list, on the task page, in the task drawer and in chat rounds;
  2. the images under a message (comments, answers, change requests, a chat's first message);
  3. the images added to a message box before sending.
- **No new libraries and no database change.** Each type uses what the browser has: `<img>`, the built-in PDF viewer in an `<iframe>`, `<audio>`, `<video>`, and plain text in a `<pre>`.
- **The server stays strict about what it serves inline.** Today only PNG, JPEG, GIF and WebP checked by their bytes are served inline. This design adds PDF, also checked by its bytes, and nothing else. SVG, text, audio and video are still served as downloads; the viewer shows them through `<img>`, `fetch` and media elements, which ignore the download header and never run a file's scripts. HTML and Markdown files are shown as source text, never rendered.

## Architecture

### Frontend
- **`frontend/src/lib/preview.ts` (new)**
  - `ViewerFile`: `{ key, name, size, kind, src, downloadUrl?, tabUrl?, note? }`. `note` is the grey line under the name ("from Sara Kim's comment", "Not sent yet").
  - `previewKind(contentType, filename, checkedImage)`, a pure function returning `image | pdf | text | audio | video | none`:
    - `image`: the server's `image` flag, or `image/svg+xml`;
    - `pdf`: `application/pdf`;
    - `text`: a known text extension (`txt log md json csv tsv yaml yml xml html css js ts tsx jsx py go rs sh sql toml ini diff patch`), else `text/*` or a known text type such as `application/json`. The extension is checked first because browsers report `.ts` as video;
    - `audio` / `video`: `audio/*` / `video/*`;
    - `none`: everything else.
  - Builders from the three sources: a task `Attachment`, a message `ImageRef`, a `DraftImage` (its local object URL, no download or new-tab link).
  - `loadText(url)`: reads at most the first 1 MB of the file and stops; reports whether it was cut; a file with NUL bytes counts as not text.
- **`frontend/src/components/attachments/AttachmentViewer.tsx` (new)**: props `files`, `openKey`, `onOpen(key)`, `onClose()`. Layout as in mockup v2:
  - top bar: name, note line, "2 of 5", zoom (images), Open in new tab (checked images and PDFs only, the two types the server serves inline), Download, Close;
  - body: the preview, with previous / next arrows;
  - thumbnail strip when there is more than one file: the picture for checked images, a type chip (PDF, TXT, MP4…) for the rest.
  - Always dark, in both themes. On a phone it fills the screen, the arrows sit at the bottom corners, and the zoom buttons and Open in new tab are hidden.
  - Only the current file is loaded.
- **`FilePreview` (same folder)**: one branch per kind.
  - image: `<img>`; − / + step 25% between 50% and 300%; a click or tap switches 100% ↔ 200%; zoom resets on the next file.
  - pdf: `<iframe src="/api/attachments/{id}?inline=1">`. When `navigator.pdfViewerEnabled` is false (most phone browsers): a card "This browser can't show PDFs in the page" with Open in new tab and Download.
  - text: `<pre>` with wrapping; when cut, a line "Showing the first 1 MB of 3.2 MB. Download the file to see all of it."
  - audio / video: `<audio controls>` / `<video controls preload="metadata">`.
  - none: "No preview for this type of file" and a Download button.
- **`frontend/src/components/ui/Dialog.tsx`**: a new `screen` variant (fills the window, no card or title bar), so the viewer reuses its `showModal`, focus and popup handling.
- **Keyboard**: ← → move through the files and wrap around; Escape closes the viewer only. The task drawer listens for Escape on the window (`TaskDrawer.tsx:23`), so the viewer stops the key there.
- **Callers**
  - `components/task/Attachments.tsx`: the thumbnail (or type chip) and the file name become buttons that open the viewer on the whole list; a new download icon link sits before the delete button. `TaskView` and `RoundSections` do not change.
  - `components/images/ImageGallery.tsx`: keeps its thumbnail grid; its own dialog is replaced by the viewer, over that message's images. `ActivityThread`, `QuestionCard` and `RoundSections` do not change.
  - `components/images/ImageAttach.tsx`: each unsent thumbnail becomes an "Open …" button, over the images in that box. No Download or new-tab button; the ✕ that removes it stays.

### Backend (`backend/app/tasks/activity.py`)
- `upload_attachment`: a file whose bytes start with `%PDF-` is stored as `application/pdf`; a file that only claims to be a PDF is stored as `application/octet-stream`. Images are handled as today.
- `download_attachment`: `inline=1` is honoured for checked images (as today) and for a file stored as `application/pdf` whose first bytes are `%PDF-`, read when it is served, so files uploaded before this change work too. Everything else stays a download. `X-Content-Type-Options: nosniff` stays on every answer.
- The signed agent link (`download_by_link`), the runner's image endpoint and the MCP tools do not change.
- Seeking in audio and video relies on `Range` requests, which `FileResponse` already answers (Starlette 1.9); a test pins it.

## Data and interfaces
- No new table, column, endpoint or setting. `AttachmentOut` is unchanged, so the generated API types stay as they are.
- The only API change: `GET /api/attachments/{id}?inline=1` now answers `Content-Disposition: inline` for PDFs too.

## Error handling and edge cases
- **File gone or unreadable**: when a preview fails to load, the viewer asks the server for the file's first byte. 404: "This file is no longer available.", with no Download button. Anything else: "This file can't be shown here." with Download.
- **Loading**: "Loading…" until the preview is ready; a text fetch still running is cancelled when the person moves on.
- **The list changes while the viewer is open** (a file is deleted, a live update arrives): the viewer follows the file by its key; if that file is gone, it closes.
- **A PDF uploaded before this change with a wrong label** (named `.pdf` but not a PDF): the frame would download it instead of showing it. Rare, and accepted; new uploads are labelled by their bytes.
- **PDF scripts**: a PDF is shown by the browser's own viewer, which keeps a PDF's scripts away from the page. It is served with its exact type and `nosniff`.
- **One file**: no arrows, counter or strip.
- **Long names** are cut with an ellipsis in the top bar; the full name is the dialog's label.

## Testing
- **Vitest**
  - `preview.test.ts`: the `previewKind` table, including `.ts`, SVG, unknown types, and the three builders.
  - `AttachmentViewer.test.tsx`: the right element per kind; arrows and ← → wrap; Escape closes and does not reach a window listener; zoom steps and reset; which kinds get Download and Open in new tab; the cut-text notice (stubbed `fetch`); the no-PDF-viewer card; both error messages; closing when the open file leaves the list.
  - `Attachments.test.tsx`: the name opens the viewer, the download link's address, chips for files that are not images.
  - `ImageGallery.test.tsx` and `ImageAttach.test.tsx`: updated for the new viewer; an unsent image has no Download.
- **pytest** (`backend/tests/tasks/test_attachments.py`): a real PDF is stored as `application/pdf` and served inline with `inline=1`; a fake one is stored as `application/octet-stream` and stays a download; SVG, HTML and text never inline; a `Range` request answers 206.
- **Playwright**: `e2e/images.spec.ts` updated for the new viewer; a new check uploads a PDF and a text file to a task, opens each from the Attachments list and finds the frame, the text and the Download link.

## Out of scope
- Word, Excel and PowerPoint previews.
- Rendering Markdown or HTML files, and syntax colouring.
- Thumbnails in the list for files that are not checked images (a PDF's first page, a video frame).
- A link that opens a given file's preview directly.
- Deleting or renaming from the viewer.
- Sending files other than images with a message.
- Pinch-zoom and drag gestures for images.
- The mockup's "Jump to" row, "Phone" and "Light" buttons: they are mockup tools, not part of the app.
