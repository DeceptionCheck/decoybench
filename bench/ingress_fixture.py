"""Neutral standalone ingress fixture, no application/model/identity dependency."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def handle_case(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=4096:raise ValueError('body')
            self.rfile.read(size)
            if self.command=='POST' and self.path in {'/login','/setup','/acknowledge'}:
                kind,status='rejected_form',401 if self.path=='/login' else 403
            elif self.command not in {'GET','HEAD','POST'} and self.path=='/overview':kind,status='unsupported_method',405
            elif self.path=='/configuration':kind,status='operational_unavailable',403
            else:kind,status='unknown_path',404
            raw={401:b'401 Unauthorized.',403:b'403 Forbidden.',404:b'404 Not Found.',405:b'405 Method Not Allowed.'}[status]
            self.send_response(status);self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            row={'surface':'hmi','http':{'method':self.command,'path':self.path,
                'headers_subset':{'User-Agent':self.headers.get('User-Agent','')}},
                'disposition':kind,'response':{'source':'deterministic'}}
            with self.server.audit_lock,self.server.audit.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        except (OSError,ValueError):pass

    do_GET=do_POST=do_PATCH=do_PUT=do_DELETE=handle_case


@contextmanager
def neutral_ingress():
    with tempfile.TemporaryDirectory(prefix='decoybench-fixture-') as folder:
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;server.block_on_close=False
        server.audit=Path(folder)/'audit.jsonl';server.audit.touch();server.audit_lock=threading.Lock()
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
        try:yield f'http://127.0.0.1:{server.server_port}',server.audit
        finally:server.shutdown();server.server_close();worker.join(1)
