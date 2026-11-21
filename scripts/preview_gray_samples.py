"""独立灰度小样预览入口；仅绑定本机，不更改原编辑器入口。

运行：uv run --no-project python scripts/preview_gray_samples.py
默认打开区域选取；加 --study original 可恢复原三版入口。
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/":
            self.send_response(302)
            self.send_header("Location", self.server.entry)
            self.end_headers()
            return
        super().do_GET()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--study", choices=("support", "original"), default="support")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(PreviewHandler, directory=str(ROOT)))
    server.entry = "/prototype/gray_samples.html" + ("?study=support" if args.study == "support" else "")
    print(f"Gray samples: http://localhost:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
