"""Local browser interface for running course scenarios with the MAS runtime."""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sysconfig
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

from mas.config import Settings
from mas.team import ROLE_FILE
from mas.web_runner import RunManager


ASSETS = Path(__file__).with_name("web_static")
STATIC_FILES = {
    "": ("index.html", "text/html"),
    "app.js": ("app.js", "text/javascript"),
    "style.css": ("style.css", "text/css"),
}
SCENARIOS = Path(__file__).resolve().parents[1] / "testset"
EXAMPLE_NAMES = {
    "scenario_1_software_engineering 2": "软件开发团队",
    "scenario_2_newsroom 2": "新闻编辑部",
    "scenario_3_securities_fund 2": "证券投资基金团队",
}


def examples() -> list[dict]:
    directory = SCENARIOS
    if not directory.is_dir():
        directory = Path(sysconfig.get_path("data")) / "share" / "mas" / "midtest"
    items = []
    for name, label in EXAMPLE_NAMES.items():
        folder = directory / name
        roles = folder / ROLE_FILE
        if roles.is_file():
            tasks = [p.read_text(encoding="utf-8") for p in sorted(folder.glob("*_task_*.md"))]
            items.append({"id": name, "name": label, "roles": roles.read_text(encoding="utf-8"), "tasks": tasks})
    return items


def browser_snapshot(manager: RunManager, run_id: str) -> dict:
    snapshot = manager.snapshot(run_id)
    results = []
    files = []
    for result in snapshot["results"]:
        attachments = [
            {"name": file["name"], "url": f"/api/runs/{run_id}/files/{quote(file['id'], safe='')}"}
            for file in result["files"]
        ]
        results.append({**result, "files": attachments})
        files.extend(attachments)
    questions = snapshot["questions"]
    status = "waiting" if questions and snapshot["status"] == "running" else snapshot["status"]
    return {**snapshot, "status": status, "question": next(iter(questions), None), "results": results, "files": files}


def create_server(settings: Settings, port: int = 8765) -> ThreadingHTTPServer:
    manager = RunManager(settings)

    class WorkspaceServer(ThreadingHTTPServer):
        def server_close(self) -> None:
            try:
                super().server_close()
            finally:
                manager.close()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def json(self, status: int, data: dict) -> None:
            self.reply(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def dispatch(self, post: bool) -> None:
            host = self.headers.get("Host")
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if port == 80:
                hosts.update({"127.0.0.1", "localhost"})
            if host not in hosts:
                self.json(403, {"error": "仅允许从本机访问。"})
                return
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{host}":
                self.json(403, {"error": "请从工作台页面发起请求。"})
                return
            parts = urlsplit(self.path).path.split("/")[1:]
            if post:
                self.post(parts)
            else:
                self.get(parts)

        def get(self, parts: list[str]) -> None:
            if len(parts) == 1 and parts[0] in STATIC_FILES:
                name, mime = STATIC_FILES[parts[0]]
                self.reply(200, (ASSETS / name).read_bytes(), mime + "; charset=utf-8")
            elif parts == ["api", "examples"]:
                self.json(200, {"examples": examples()})
            elif parts == ["api", "active"]:
                self.json(200, {"id": manager.active_id()})
            elif parts[:2] == ["api", "runs"] and len(parts) == 3:
                self.json(200, browser_snapshot(manager, parts[2]))
            elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "inputs":
                self.json(200, manager.inputs(parts[2]))
            elif len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3] == "files":
                path = manager.artifact(parts[2], parts[4])
                with path.open("rb") as stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name, safe=""))
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    shutil.copyfileobj(stream, self.wfile)
            else:
                self.json(404, {"error": "找不到这个页面。"})

        def post(self, parts: list[str]) -> None:
            if self.headers.get_content_type() != "application/json":
                self.json(415, {"error": "请求需要使用 JSON 格式。"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 * 1024:
                self.json(413, {"error": "请输入角色和任务，总大小限 1 MiB。"})
                return
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("需要一个包含角色和任务的 JSON 对象。")
            if parts == ["api", "runs"]:
                roles, tasks = data.get("roles"), data.get("tasks")
                if not isinstance(roles, str) or not isinstance(tasks, list) or not all(isinstance(t, str) for t in tasks):
                    raise ValueError("请输入角色 Markdown 和任务列表。")
                self.json(201, {"id": manager.start(roles, tasks)})
            elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "answer":
                question, answer = data.get("id"), data.get("answer")
                if not isinstance(question, str) or not isinstance(answer, str) or not answer.strip():
                    raise ValueError("请选择问题并填写答复。")
                manager.reply(parts[2], question, answer)
                self.json(200, {"ok": True})
            else:
                self.json(404, {"error": "找不到这个接口。"})

        def handle_request(self, post: bool) -> None:
            try:
                self.dispatch(post)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (KeyError, FileNotFoundError):
                self.json(404, {"error": "找不到这次运行、问题或文件。"})
            except ValueError as exc:
                self.json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self.json(409, {"error": str(exc)})
            except Exception:
                logging.exception("Browser interface request failed")
                self.json(500, {"error": "服务发生错误，详情请查看终端。"})

        def do_GET(self) -> None:
            self.handle_request(False)

        def do_POST(self) -> None:
            self.handle_request(True)

    return WorkspaceServer(("127.0.0.1", port), Handler)


def main() -> None:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="model settings (default: .env)")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    with create_server(Settings.from_env(data_dir=args.data_dir), args.port) as server:
        print(f"MAS workspace: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
