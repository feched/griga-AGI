"""Локальный HTTP-сервер визуализатора (ADR-015 §5).

Только стандартная библиотека: ``http.server`` + статические файлы.
Сервер по умолчанию слушает ``127.0.0.1`` — наружу ничего не отдаётся.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from griga.config import Config, load_config
from griga.graph.graph import KnowledgeGraph
from griga.thinking.spreader import Spreader, WorkingMemory
from griga.visualization.snapshot import (
    GraphSnapshot,
    build_snapshot,
    snapshot_for_node,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


class VisualizerServer:
    """Состояние визуализатора: граф, рабочая память и последний запрос."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | None = None,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.graph = graph
        self.config = config or load_config()
        self.spreader = Spreader(graph, self.config)
        self.host = host
        self.port = port
        self.memory: WorkingMemory | None = None
        self.last_query: str | None = None

    def snapshot(self) -> GraphSnapshot:
        meta: dict[str, Any] = {}
        if self.last_query is not None:
            meta["last_query"] = self.last_query
        return build_snapshot(self.graph, self.memory, meta=meta)

    def activate(self, name: str) -> GraphSnapshot | None:
        node = snapshot_for_node(self.graph, name)
        if node is None:
            return None
        self.memory = self.spreader.activate(
            [node], top_k=self.config.memory.top_k
        )
        self.last_query = node.name
        return self.snapshot()

    def reset(self) -> GraphSnapshot:
        self.memory = None
        self.last_query = None
        return self.snapshot()

    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def serve_forever(self, *, open_browser: bool = True) -> None:
        httpd = self.make_httpd()
        self.port = httpd.server_address[1]
        url = self.url()
        print(f"Визуализатор: {url}")
        print("Остановка: Ctrl+C")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
        finally:
            httpd.server_close()

    def start_background(self) -> tuple[ThreadingHTTPServer, threading.Thread]:
        """Запускает сервер в фоне (для тестов и скриптов)."""
        httpd = self.make_httpd()
        self.port = httpd.server_address[1]
        thread = threading.Thread(
            target=httpd.serve_forever, name="griga-visualizer", daemon=True
        )
        thread.start()
        return httpd, thread

    def make_httpd(self) -> "_VisualizerHTTPServer":
        return _VisualizerHTTPServer((self.host, self.port), _Handler, self)


class _VisualizerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        visualizer: VisualizerServer,
    ) -> None:
        super().__init__(address, handler)
        self.visualizer = visualizer


class _Handler(BaseHTTPRequestHandler):
    server: _VisualizerHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Тихий лог: не засоряем консоль диалога.
        return

    # --- routing -------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/api/graph":
            self._send_json(self.server.visualizer.snapshot().to_dict())
            return

        if parsed.path == "/api/activate":
            query = parse_qs(parsed.query).get("node", [""])[0].strip()
            if not query:
                self._send_json(
                    {"error": "query parameter 'node' is required"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            snapshot = self.server.visualizer.activate(query)
            if snapshot is None:
                self._send_json(
                    {"error": f"node {query!r} not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_json(snapshot.to_dict())
            return

        if parsed.path == "/api/health":
            self._send_json({"status": "ok"})
            return

        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/reset":
            self._send_json(self.server.visualizer.reset().to_dict())
            return
        self._send_json(
            {"error": "not found"}, status=HTTPStatus.NOT_FOUND
        )

    # --- responses -----------------------------------------------------

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = _CONTENT_TYPES.get(
            target.suffix.lower(),
            mimetypes.guess_type(str(target))[0] or "application/octet-stream",
        )
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
