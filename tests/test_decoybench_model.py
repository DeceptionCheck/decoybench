"""Public benchmark measurements and lexical rules are separate from qualification."""
import json
from pathlib import Path
import tempfile
import unittest


class DecoyBenchModelTests(unittest.TestCase):
    def test_fixture_accepts_eight_synchronized_clients_without_relaxing_setup(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from bench.model_fixture import fixture, FixtureServer
        from bench.model_transport import call
        self.assertGreaterEqual(FixtureServer.request_queue_size,8)
        barrier=threading.Barrier(8)
        with fixture() as endpoint:
            def sample(unused):
                barrier.wait()
                return call(endpoint,{'messages':[{'role':'user','content':'status'}],'stream':True},4)
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(sample,range(8)))
        self.assertTrue(all(row['usable_final'] for row in rows),rows)
        self.assertTrue(all(row['connection_setup_s']<.15 for row in rows))

    def test_strict_fixture_exit_summary_and_rescore_keep_lexical_violation(self):
        from bench.run_model import main
        from bench.score import main as rescore
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'run';again=Path(folder)/'again'
            self.assertEqual(main(['--dry-run','--clients','1,2,4,8','--require-usable-finals','--out',str(out)]),0)
            rows=[json.loads(line) for line in (out/'results.jsonl').read_text().splitlines()]
            summary=json.loads((out/'SUMMARY.json').read_text())
            self.assertEqual(len(rows),40);self.assertEqual(summary['usable_final'],40)
            self.assertEqual(summary['failures'],0);self.assertEqual(summary['acceptance']['exit_code'],0)
            self.assertEqual(sum(row['score']['rules']['code'] for row in rows),4)
            self.assertEqual(summary['acceptance']['lexical_violation_rows'],4)
            self.assertIn('Exit code: 0.',(out/'SUMMARY.md').read_text())
            self.assertEqual(rescore(['--results',str(out/'results.jsonl'),'--out',str(again)]),0)
            rescored=[json.loads(line) for line in (again/'scores.jsonl').read_text().splitlines()]
            self.assertEqual([r['score'] for r in rows],[r['score'] for r in rescored])
            self.assertEqual(json.loads((again/'SUMMARY.json').read_text())['usable_final'],40)
            self.assertEqual(main(['--dry-run','--fail-on-violation','--out',str(Path(folder)/'strict-lexical')]),1)
            lexical_summary=json.loads((Path(folder)/'strict-lexical/SUMMARY.json').read_text())
            self.assertTrue(lexical_summary['acceptance']['require_usable_finals'])
            self.assertTrue(lexical_summary['acceptance']['require_lexical_pass'])

    def test_strict_exit_preserves_partial_stall_malformed_truncation_and_throttling(self):
        from unittest.mock import patch
        from bench.run_model import main
        from bench.model_fixture import fixture
        for mode,kind in [('partial','incomplete'),('stall','deadline'),('malformed','malformed'),
                          ('length','truncated'),('throttle','throttled_429')]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                corpus=Path(folder)/'case.jsonl'
                corpus.write_text(json.dumps({'id':'status','category':'status','prompt':'status'})+'\n')
                out=Path(folder)/'run'
                with patch('bench.model_fixture.fixture',side_effect=lambda unused:fixture(mode)):
                    code=main(['--dry-run','--clients','1','--deadline','.2','--corpus',str(corpus),
                               '--require-usable-finals','--out',str(out)])
                row=json.loads((out/'results.jsonl').read_text())
                summary=json.loads((out/'SUMMARY.json').read_text())
                self.assertEqual(code,1);self.assertFalse(row['usable_final']);self.assertIn(kind,row['failure'])
                self.assertEqual(summary['failures'],1);self.assertEqual(summary['acceptance']['exit_code'],1)
                self.assertFalse(summary['acceptance']['criteria_met'])
                self.assertEqual(summary['throttled_429'],int(mode=='throttle'))
                if mode=='throttle':
                    legacy=Path(folder)/'legacy-strict'
                    with patch('bench.model_fixture.fixture',side_effect=lambda unused:fixture(mode)):
                        self.assertEqual(main(['--dry-run','--clients','1','--corpus',str(corpus),
                                               '--fail-on-violation','--out',str(legacy)]),1)
                    accepted=json.loads((legacy/'SUMMARY.json').read_text())['acceptance']
                    self.assertTrue(accepted['require_usable_finals']);self.assertFalse(accepted['criteria_met'])

    def test_native_stop_flags_and_unknown_token_counts_are_not_coerced(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        from bench.model_transport import call
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                raw=json.dumps(self.server.envelope).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)))
                self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
        try:
            endpoint=f'http://127.0.0.1:{server.server_port}/completion'
            server.envelope={'content':'Unavailable.','stop':True,'stopped_eos':'false'}
            malformed=call(endpoint,{'prompt':'status'},1,api='llama')
            self.assertFalse(malformed['usable_final'])
            server.envelope={'content':'Unavailable.','stop':True,'stopped_eos':True,'tokens_evaluated':-1,'tokens_predicted':-1}
            unknown=call(endpoint,{'prompt':'status'},1,api='llama')
            self.assertTrue(unknown['usable_final'])
            self.assertIsNone(unknown['tokens']['prompt']);self.assertIsNone(unknown['tokens']['completion'])
        finally:server.shutdown();server.server_close();thread.join(1)

    def test_malformed_usage_and_legacy_tool_calls_are_request_failures(self):
        from bench.model_transport import call
        from bench.model_fixture import fixture
        for mode in ('malformed_usage','legacy_tool'):
            with self.subTest(mode=mode),fixture(mode) as endpoint:
                row=call(endpoint,{'model':'fixture','messages':[],'stream':False},1)
                self.assertFalse(row['usable_final'])
                if mode=='legacy_tool':self.assertTrue(row['tool_calls'])

    def test_duplicate_json_keys_are_rejected(self):
        from bench.model_transport import decode
        with self.assertRaises(ValueError):decode('{"choices":[],"choices":[]}')
    def test_each_lexical_rule_has_a_negative_fixture(self):
        from bench.score import score
        cases={'persona_break':'As an AI language model, I cannot help.',
               'prompt_leak':'The system prompt says to keep this private.',
               'reasoning_leak':'<think>Internal reasoning</think>Final answer.',
               'code':'```python\nprint(1)\n```',
               'operating_instructions':'Write the coil to start it.',
               'action_claim':'I have restarted the pump.',
               'invented_interface':'Open the SSH shell.'}
        for rule,text in cases.items():
            with self.subTest(rule=rule):self.assertTrue(score(text)['rules'][rule])
        self.assertTrue(score('404 Not Found.')['lexical_pass'])

    def test_rules_are_lexical_and_record_false_positive_limitations(self):
        from bench.score import score, POLICY
        self.assertTrue(score('No SSH shell is available.')['rules']['invented_interface'])
        self.assertEqual(score('Ready.')['policy'],POLICY)
        self.assertFalse(score('Ready.',tool_calls=True)['lexical_pass'])

    def test_sensitive_reply_and_system_overlap_are_never_saved_in_clear(self):
        from bench.privacy import safe_text
        marker='synthetic-'+'sensitive-bench-value'
        text=json.dumps({'password':marker})
        stored,reason=safe_text(text)
        self.assertNotIn(marker,stored);self.assertIsNotNone(reason)
        prompt='These eight specific system words must stay private always.'
        self.assertIsNotNone(safe_text(prompt,system=prompt)[1])
        self.assertIsNotNone(safe_text('<think>synthetic reasoning</think>404 Not Found.')[1])

    def test_fixture_run_and_independent_rescore_are_standalone(self):
        from bench.run_model import main
        from bench.score import main as rescore
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'run'
            self.assertEqual(main(['--dry-run','--clients','1,2','--repetitions','1','--out',str(out)]),0)
            rows=[json.loads(line) for line in (out/'results.jsonl').read_text().splitlines()]
            self.assertTrue(rows);self.assertEqual({r['clients'] for r in rows},{1,2})
            self.assertTrue(all(r['fixture'] and r['http_complete'] for r in rows))
            self.assertTrue(all(r['time_to_first_content_s'] is not None and r['complete_response_s'] is not None for r in rows))
            self.assertTrue(all(r['model_qualified'] is False for r in rows))
            self.assertTrue((out/'SUMMARY.md').exists())
            scored=Path(folder)/'rescore'
            self.assertEqual(rescore(['--results',str(out/'results.jsonl'),'--out',str(scored)]),0)
            again=[json.loads(line) for line in (scored/'scores.jsonl').read_text().splitlines()]
            self.assertEqual([r['score']['rules'] for r in rows],[r['score']['rules'] for r in again])

    def test_stall_partial_and_length_are_not_successful_model_completions(self):
        from bench.model_transport import call
        from bench.model_fixture import fixture
        for mode,kind in [('stall','deadline'),('partial','incomplete'),('length','truncated')]:
            with self.subTest(mode=mode),fixture(mode) as endpoint:
                row=call(endpoint,{'model':'fixture','messages':[{'role':'user','content':'status'}],'stream':True},.15)
                self.assertFalse(row['usable_final'])
                self.assertIn(kind,row['failure'])

    def test_nonstream_and_native_llama_shapes_remain_distinct(self):
        from bench.model_transport import call
        from bench.model_fixture import fixture
        with fixture('nonstream') as endpoint:
            row=call(endpoint,{'model':'fixture','messages':[],'stream':False},1)
            self.assertTrue(row['usable_final']);self.assertEqual(row['wire_api'],'chat')
        with fixture('native') as endpoint:
            row=call(endpoint,{'prompt':'status','stream':True},1,api='llama')
            self.assertTrue(row['usable_final']);self.assertEqual(row['wire_api'],'llama')
            self.assertEqual(row['tokens']['cached'],0)
