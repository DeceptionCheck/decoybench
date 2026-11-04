"""Disposable HTTP wire fixtures. No model inference or private app import."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


class FixtureServer(ThreadingHTTPServer):
    """Accept an eight-client burst before exposing the fixture endpoint.

    The queue is fixture capacity, not a transport timeout or admission policy.
    Readiness means the accept loop has completed a cycle, without probe calls.
    """
    request_queue_size = 64
    daemon_threads = True
    block_on_close = False

    def service_actions(self):
        self.ready.set()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=1024*1024:raise ValueError('size')
            request=json.loads(self.rfile.read(size));mode=self.server.mode
            if mode=='throttle':
                self.send_response(429);self.send_header('Content-Length','0');self.end_headers();return
            if mode=='partial':
                raw=b'data: {"choices"'
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(raw)+100));self.end_headers();self.wfile.write(raw);self.wfile.flush();return
            if mode=='stall':
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.flush()
                self.server.stopping.wait(2);return
            prompt=str(request.get('messages',[{}])[-1].get('content','')) if request.get('messages') else str(request.get('prompt',''))
            text='```text\nexample\n```' if 'code' in prompt.casefold() else '404 Not Found.'
            if mode=='malformed':
                raw=b'{"choices":';media='application/json'
            elif mode in {'nonstream','malformed_usage','legacy_tool'}:
                value={'model':'fixture','choices':[{'message':{'role':'assistant','content':text},'finish_reason':'stop'}],
                       'usage':{'prompt_tokens':12,'completion_tokens':4}}
                if mode=='malformed_usage':value['usage']['completion_tokens_details']=['malformed']
                if mode=='legacy_tool':value['choices'][0]['message']['function_call']={'name':'example','arguments':'{}'}
                raw=json.dumps(value).encode();media='application/json'
            elif mode=='native':
                value={'content':text,'stop':True,'stopped_eos':True,'tokens_evaluated':12,'tokens_predicted':4,'tokens_cached':0,
                       'timings':{'prompt_ms':1.0,'predicted_ms':2.0}}
                raw=('data: '+json.dumps(value)+'\n\n').encode();media='text/event-stream'
            else:
                values=[{'choices':[{'delta':{'role':'assistant'},'finish_reason':None}]},
                        {'choices':[{'delta':{'content':text},'finish_reason':None}]},
                        {'choices':[{'delta':{},'finish_reason':'length' if mode=='length' else 'stop'}],
                         'usage':{'prompt_tokens':12,'completion_tokens':4,'completion_tokens_details':{'reasoning_tokens':0},'prompt_tokens_details':{'cached_tokens':0}}}]
                raw=(''.join('data: '+json.dumps(value)+'\n\n' for value in values)+'data: [DONE]\n\n').encode();media='text/event-stream'
            self.send_response(200);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        except (ValueError,OSError,IndexError):pass


@contextmanager
def fixture(mode='chat'):
    server=FixtureServer(('127.0.0.1',0),Handler)
    server.mode=mode;server.stopping=threading.Event();server.ready=threading.Event()
    worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
    try:
        if not server.ready.wait(1):raise RuntimeError('fixture accept loop did not become ready')
        yield f'http://127.0.0.1:{server.server_port}/'+('completion' if mode=='native' else 'v1/chat/completions')
    finally:server.stopping.set();server.shutdown();server.server_close();worker.join(1)
