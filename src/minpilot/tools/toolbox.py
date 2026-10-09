"""The worker tool set, bound to one workspace directory.

Tools (names and descriptions are min_pilot's own):
  web_search(query)                 Google results via Serper (DuckDuckGo fallback); cached
  read_url(url, page=1, date=None)  page text (Crawl4AI -> direct -> Playwright), paged; `date` reads the
                                    Wayback snapshot closest to that date
  read_file(path, page=1)           a file in the workspace (attachments, files written by code); paged; zips
                                    are extracted
  view_image(path_or_url)           puts the image into the worker's context (the worker model sees it)
  run_python(code)                  sandboxed Python in the workspace (no network, no processes)

A `Toolbox` is bound to one workspace. The execution worker uses the run's main workspace; probes and
verifications get a toolbox on a scratch copy, so whatever they write never reaches the execution (the
`WebTools` cache is shared: it only makes identical requests return identical results).

`call(name, arguments)` checks the run budget first (BudgetExceeded propagates), never raises for tool errors
(they come back to the model as text), and writes one record per call through the trace.
"""

from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from minpilot.runtime.trace import Trace
from minpilot.tools import blocklist, documents
from minpilot.tools.sandbox import normalize_paths, run_python
from minpilot.tools.web import BLOCKED_MESSAGE, WebTools, paged

MAX_IMAGE_SIDE = 4096  # larger images are downscaled before they are sent (keeps the request within limits)

TOOL_SCHEMAS: dict[str, dict] = {
    "web_search": {
        "description": "Search the web (Google results). Returns the top results with title, URL and snippet.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The search query."}}, "required": ["query"]},
    },
    "read_url": {
        "description": ("Read a web page or an online document (HTML, PDF, DOCX, XLSX, ...) as text. Long content is "
                        "split into pages; request later pages with `page`. Give `date` (YYYYMMDD) to read the "
                        "archived snapshot (Wayback Machine) closest to that date instead of the live page."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "http(s) URL."},
            "page": {"type": "integer", "description": "Page of the extracted text, starting at 1."},
            "date": {"type": "string", "description": "Optional YYYYMMDD date for an archived snapshot."}},
            "required": ["url"]},
    },
    "read_file": {
        "description": ("Read a file in the working directory (e.g. an attachment, or a file written by code) as "
                        "text: PDF, DOCX, PPTX, XLSX/XLS/CSV (all sheets, with cell fill colours), TXT, JSON, XML, "
                        "code, ... ZIP archives are extracted and their file list is returned. Long content is "
                        "split into pages; request later pages with `page`."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path relative to the working directory."},
            "page": {"type": "integer", "description": "Page of the extracted text, starting at 1."}},
            "required": ["path"]},
    },
    "view_image": {
        "description": "Look at an image (a file in the working directory or an http(s) URL). The image is added "
                       "to your context so you can inspect it directly.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace path or http(s) URL of the image."}},
            "required": ["path"]},
    },
    "run_python": {
        "description": ("Run Python code in the working directory and return stdout, stderr and the exit code. Only "
                        "Python (no shell or other processes); no network access (use web_search/read_url); only "
                        "the working directory is readable and writable. Print what you need to see. Common "
                        "packages are installed: numpy, pandas, scipy, sympy, matplotlib, openpyxl, pymupdf, "
                        "python-docx, python-pptx, pillow."),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "The Python code to run."}}, "required": ["code"]},
    },
}
TOOL_NAMES = tuple(TOOL_SCHEMAS)


def tool_schemas(names: tuple[str, ...] | list[str]) -> list[dict]:
    return [{"type": "function", "function": {"name": n, **TOOL_SCHEMAS[n]}} for n in names]


@dataclass
class ToolOutput:
    text: str
    images: list[str] = field(default_factory=list)  # data URLs to show the model after the tool results


class Toolbox:
    def __init__(self, work_dir: Path | str, web: WebTools, trace: Trace, *, question: str | None = None):
        self.work_dir = Path(work_dir).resolve()
        self.web = web
        self.trace = trace
        self.question = question  # for the content blocklist only
        self.n_code_runs = 0

    # -- state (workspace-local counters) ----------------------------------------------------
    def state_dict(self) -> dict:
        return {"n_code_runs": self.n_code_runs}

    def load_state_dict(self, state: dict) -> None:
        self.n_code_runs = state.get("n_code_runs", 0)

    def attachment_names(self) -> tuple[str, ...]:
        att = self.work_dir / "attachments"
        return tuple(sorted(p.name for p in att.iterdir())) if att.is_dir() else ()

    # -- dispatch ----------------------------------------------------------------------------
    def call(self, name: str, arguments: str | dict, allowed_tools: tuple[str, ...]) -> ToolOutput:
        rec = {"tool": name, "call_no": self.trace.next_id()}
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as e:
            self.trace.tool({**rec, "args_raw": str(arguments)[:2000], "status": "error",
                             "error": f"invalid_arguments: {e}"})
            return ToolOutput(f"Error: the arguments are not a valid JSON object ({e}).")
        rec["args"] = args
        if name not in allowed_tools:
            self.trace.tool({**rec, "status": "error", "error": "tool_not_available"})
            return ToolOutput(f"Error: tool {name!r} is not available to you.")
        self.trace.before_tool()
        self.trace.tool({**rec, "status": "started"})
        t0 = time.monotonic()
        try:
            out, extra = getattr(self, f"_t_{name}")(**args)
        except TypeError as e:  # wrong or missing arguments
            out, extra = f"Error: invalid arguments for {name} ({e}).", {"error": f"invalid_arguments: {e}"}
        except Exception as e:  # tool bugs never crash the run; the record keeps the error
            out, extra = f"Error: {name} failed ({type(e).__name__}).", {"error": repr(e)[:500]}
        if isinstance(out, ToolOutput):
            result = out
        else:
            result = ToolOutput(out)
        if not extra.get("error") and result.text.startswith("Error:"):
            extra = {**extra, "error": "tool_error_message"}  # e.g. a wrong file type: the agent saw an error
        status = "error" if extra.get("error") else "ok"
        self.trace.tool({**rec, **extra, "status": status, "latency_s": round(time.monotonic() - t0, 3),
                         "output_chars": len(result.text), "n_images": len(result.images),
                         "output_head": result.text[:300]})
        return result

    # -- tools -------------------------------------------------------------------------------
    def _t_web_search(self, query: str):
        return self.web.web_search(str(query), allowed=self.attachment_names())

    def _t_read_url(self, url: str, page: int = 1, date: str | None = None):
        return self.web.read_url(str(url), page=page, date=date, allowed=self.attachment_names())

    def _confine(self, path: str) -> Path | None:
        p = Path(str(path)).expanduser()
        p = (self.work_dir / p).resolve() if not p.is_absolute() else p.resolve()
        return p if p.is_relative_to(self.work_dir) else None

    def _show(self, p: Path) -> str:
        return str(p.relative_to(self.work_dir)) if p.is_relative_to(self.work_dir) else str(p)

    def _t_read_file(self, path: str, page: int = 1):
        rec: dict = {"backend": "local"}
        p = self._confine(path)
        if p is None:
            rec["blocked"] = "outside_work_dir"
            return f"Error: {path} is outside the working directory.", rec
        if not p.is_file():
            return f"Error: file not found: {path}", rec
        ext = p.suffix.lower().lstrip(".")
        data = p.read_bytes()
        if ext == "zip":
            dest = p.with_suffix("")
            try:
                files = documents.extract_zip(data, dest, root=self.work_dir)
            except PermissionError as e:
                rec["blocked"] = "outside_work_dir"
                return f"Error: {e}", rec
            return (f"Extracted {len(files)} files from {self._show(p)} into {self._show(dest)}:\n"
                    + "\n".join(self._show(f) for f in files)), rec
        if ext in documents.IMAGE_EXTS:
            return f"Error: {path} is an image; use view_image to look at it.", rec
        try:
            text = documents.bytes_to_text(data, ext)
        except documents.UnsupportedDocument as e:
            return f"Error: {e}", rec
        # Files other than the task's own attachments came from the web or from code: content rules apply.
        if not self._show(p).startswith("attachments/"):
            if reason := blocklist.content_block_reason(text, self.question, allowed=self.attachment_names()):
                rec["blocked"] = reason
                return BLOCKED_MESSAGE, rec
        return paged({"text": text, "url": self._show(p), "title": p.name}, page, self.web.cfg.page_chars,
                     "read_file", self._show(p)), rec

    def _t_view_image(self, path: str):
        rec: dict = {}
        path = str(path).strip()
        if path.startswith(("http://", "https://")):
            if reason := self.web._block_reason(path, blocklist.url_block_reason(path)):
                rec["blocked"] = reason
                return BLOCKED_MESSAGE, rec
            # Online images are cached like pages: frozen on first success (review 2026-10-09, F9)
            cached = self.web.cache.get("image", path)
            if cached is not None:
                data = base64.b64decode(cached["b64"])
                rec.update(cache_hit=True, backend="direct")
            else:
                from minpilot.tools.backends import BackendError, DirectFetchBackend

                try:
                    data, _, _ = DirectFetchBackend(self.web.cfg).download(path)
                except BackendError as e:
                    rec["error"] = str(e)[:300]
                    return "Error: could not download the image.", rec
                data = base64.b64decode(self.web.cache.put("image", path, {
                    "b64": base64.b64encode(data).decode(), "fetched_at": time.time()}, "direct")["b64"])
                rec.update(cache_hit=False, backend="direct")
            label = path
        else:
            p = self._confine(path)
            if p is None:
                rec["blocked"] = "outside_work_dir"
                return f"Error: {path} is outside the working directory.", rec
            if not p.is_file():
                return f"Error: file not found: {path}", rec
            data, label = p.read_bytes(), self._show(p)
            rec["backend"] = "local"
        try:
            url, size, resized = image_data_url(data)
        except Exception as e:
            rec["error"] = f"not_an_image: {e!r}"[:300]
            return f"Error: {path} could not be opened as an image.", rec
        rec.update(image_size=size, resized=resized)
        note = f" (downscaled to fit {MAX_IMAGE_SIDE} px)" if resized else ""
        return ToolOutput(f"The image {label} ({size[0]}x{size[1]} px{note}) is shown below.", [url]), rec

    def _t_run_python(self, code: str):
        self.n_code_runs += 1
        res = run_python(str(code), self.work_dir, self.n_code_runs, timeout_s=self.web.cfg.code_timeout_s,
                         max_output_chars=self.web.cfg.max_code_output_chars, question=self.question,
                         allowed=self.attachment_names())
        return res.output, {"backend": "sandbox", **res.record}

    def show_path(self, text: str) -> str:
        return normalize_paths(text, self.work_dir)


def image_data_url(data: bytes) -> tuple[str, tuple[int, int], bool]:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    size = img.size
    resized = max(size) > MAX_IMAGE_SIDE
    fmt = (img.format or "PNG").upper()
    if resized or fmt not in ("PNG", "JPEG", "GIF", "WEBP"):
        if resized:
            img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data, fmt = buf.getvalue(), "PNG"
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}[fmt]
    return f"data:{mime};base64,{base64.b64encode(data).decode()}", img.size if resized else size, resized
