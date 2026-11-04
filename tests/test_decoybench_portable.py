"""The public harness runs without the application or its private input pack."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class PortableBenchmarkTests(unittest.TestCase):
    def test_throttle_does_not_impersonate_functional_memo_failure(self):
        from unittest.mock import patch
        from bench.run_ingress import condition
        from bench.corpus import DEFAULT_CASES,load_cases
        from bench.measure import summarize
        cases=load_cases(DEFAULT_CASES)
        def reply(target,case,marker,ident,terms,**kwargs):
            throttled=ident.endswith('-1')
            row={'complete':True,'status':429 if throttled else 404,
                 'status_matches':not throttled,'kind':case['kind'],'elapsed_s':.01,
                 'forbidden_fingerprints':[],'credential_response':False,
                 'body_sha256':'limited' if throttled else 'reply','deadline_miss_4s':False}
            return row,(row['status'],b'Limited' if throttled else b'Unavailable')
        with patch('bench.run_ingress.request',side_effect=reply):
            rows,result=condition('http://127.0.0.1:1',cases,4,1,'off','throttle-pair',[])
        self.assertEqual(result['throttled_429'],2)
        self.assertEqual(result['memo_mismatches'],0)
        self.assertEqual(sum(row['paired_response_changed'] is True for row in rows),2)
        self.assertTrue(all(row['memo_matches'] is None for row in rows))

    def test_each_client_retains_its_own_server_cookie(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        from bench.run_ingress import condition
        from bench.corpus import DEFAULT_CASES,load_cases
        observed=[];lock=threading.Lock();issued=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                with lock:
                    cookie=self.headers.get('Cookie')
                    if cookie:observed.append(cookie)
                    else:issued.append(str(len(issued)+1))
                    new=issued[-1] if not cookie else None
                self.send_response(404)
                if new:self.send_header('Set-Cookie','client='+new+'; Path=/; HttpOnly')
                self.send_header('Content-Length','0');self.end_headers()
            do_POST=do_GET
            do_PATCH=do_GET
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
        try:condition(f'http://127.0.0.1:{server.server_port}',load_cases(DEFAULT_CASES),8,2,'off','cookie-workers',[])
        finally:server.shutdown();server.server_close();thread.join(1)
        self.assertEqual(len(issued),2)
        self.assertEqual(sorted(observed),['client=1']*3+['client=2']*3)

    def test_429_is_separate_from_successful_functional_latency(self):
        from bench.ingress_fixture import neutral_ingress
        from bench.run_ingress import condition
        from bench.corpus import DEFAULT_CASES,load_cases
        from bench.measure import summarize
        with neutral_ingress() as (target,audit):
            rows,_=condition(target,load_cases(DEFAULT_CASES),4,1,'off','fixture-throttle',[],audit)
        for row in rows:row['elapsed_s']=1
        rows[0].update(status=429,status_matches=False,elapsed_s=.001)
        result=summarize(rows)
        self.assertEqual(result['requests'],4);self.assertEqual(result['completed'],4)
        self.assertEqual(result['throttled_429'],1);self.assertEqual(result['functional_completed'],3)
        self.assertEqual(result['functional_p50_s'],1)
        self.assertEqual(result['status_counts']['429'],1)

    def test_model_ingress_and_rescore_from_bench_only_copy(self):
        source=Path(__file__).resolve().parents[1]/'bench'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            target=root/'bench';target.mkdir()
            names=('__init__.py','run_model.py','score.py','privacy.py','model_transport.py',
                   'model_fixture.py','run_ingress.py','corpus.py','measure.py','artifacts.py','ingress_fixture.py')
            for name in names:shutil.copyfile(source/name,target/name)
            shutil.copytree(source/'corpus',target/'corpus')
            commands=[['bench.run_model','--dry-run','--clients','1,2,4,8','--require-usable-finals','--out','model'],
                      ['bench.score','--results','model/results.jsonl','--out','rescore'],
                      ['bench.run_ingress','--dry-run','--requests','8','--clients','1,2','--out','ingress']]
            for command in commands:
                result=subprocess.run([sys.executable,'-m',*command],cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            summary=json.loads(next((root/'ingress').glob('*.summary.json')).read_text())
            self.assertEqual(summary['dry_run_backend'],'neutral-standalone-wire-fixture')
            self.assertFalse(summary['model_enabled_verified'])
            self.assertTrue((root/'model/SUMMARY.md').is_file())
            self.assertEqual(json.loads((root/'model/SUMMARY.json').read_text())['requests'],40)
            self.assertEqual(json.loads((root/'model/SUMMARY.json').read_text())['usable_final'],40)
