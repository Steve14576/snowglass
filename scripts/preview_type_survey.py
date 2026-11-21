"""全类型探路的独立本机预览；只读取指定完成目录，不修改原编辑器入口。"""
import argparse
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent.parent


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path=='/':
            self.send_response(302)
            self.send_header('Location',self.server.entry)
            self.end_headers();return
        super().do_GET()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--port',type=int,default=8126)
    args=parser.parse_args()
    if not re.fullmatch(r'run-\d{8}-\d{6}-\d{6}',args.run):parser.error('无效运行目录')
    if not (ROOT/'prototype/data/type_surveys'/args.run/'manifest.json').is_file():parser.error('该批次尚未生成 manifest.json')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(ROOT)))
    server.entry=f'/prototype/type_survey.html?run={args.run}'
    print(f'Type survey: http://localhost:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
