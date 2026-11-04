"""Portable bare-model benchmark. Dry run needs only this public bench package.

Chat-completions SSE/JSON and native llama.cpp completion are separate recorded
contracts. System prompts and credentials are never copied to results. There
are no implicit calls, retries, quality certification or private policy imports.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import subprocess
import threading

from .model_transport import call, decode
from .privacy import safe_text
from .score import score, summarize, summary_markdown, POLICY

ROOT=Path(__file__).resolve().parent
DEFAULT_CORPUS=ROOT/'corpus/v1.0/prompts.jsonl'
DEFAULT_SYSTEM=ROOT/'corpus/v1.0/example_system.txt'


def load_corpus(path):
    rows=[decode(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    seen=set()
    if not rows:raise ValueError('empty corpus')
    for row in rows:
        if (not isinstance(row,dict) or set(row)-{'id','category','prompt','allowed_interfaces'}
                or not all(isinstance(row.get(key),str) and row[key] for key in ('id','category','prompt'))
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',row['id'])
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',row['category'])
                or len(row['prompt'].encode())>16384 or row['id'] in seen):raise ValueError('invalid corpus row')
        allowed=row.get('allowed_interfaces',['http','https','modbus'])
        if not isinstance(allowed,list) or any(not isinstance(item,str) or not re.fullmatch(r'[a-z]{1,20}',item) for item in allowed):
            raise ValueError('invalid interface vocabulary')
        row['allowed_interfaces']=allowed;seen.add(row['id'])
    return rows


def fingerprint(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args,endpoint):
    corpus=load_corpus(args.corpus);system=args.system.read_text(encoding='utf-8')
    if not system.strip() or len(system.encode())>32768:raise ValueError('invalid system input')
    key=os.environ.get('BENCH_API_KEY')
    terms=[]
    if args.denylist:
        terms=[line.strip() for line in Path(args.denylist).read_text(encoding='utf-8-sig').splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if not terms:raise ValueError('empty configured denylist')
    started=datetime.now(timezone.utc).isoformat()
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,stderr=subprocess.DEVNULL,text=True).strip()
    except (OSError,subprocess.CalledProcessError):commit=None
    settings={'schema':'decoybench-model-v1','start_utc':started,'fixture':args.dry_run,
        'model':args.model,'wire_api':args.api,'stream':not args.no_stream,'seed':args.seed,
        'system_sha256':fingerprint(args.system),'corpus_sha256':fingerprint(args.corpus),
        'endpoint_sha256':hashlib.sha256(endpoint.encode()).hexdigest(),'deadline_s':args.deadline,
        'repetitions':args.repetitions,'clients':args.clients,'python':platform.python_version(),
        'platform':platform.system()+' '+platform.release(),'code_commit':commit,
        'code_sha256':{name:fingerprint(ROOT/name) for name in ('run_model.py','score.py','privacy.py','model_transport.py','model_fixture.py')},
        'runtime_identity':args.runtime_id,'hardware_identity':args.hardware_id,'policy_identity':args.policy_id,
        'server_identity_verified':False,'model_qualified':False,'lexical_policy':POLICY,
        'native_prompt_format':'plain-system-newline-user-v1' if args.api=='llama' else 'chat-messages-v1',
        'deployment_denylist_loaded':bool(args.denylist),'no_private_qualification_policy_included':True}
    settings['acceptance']={'require_usable_finals':args.require_usable_finals or args.fail_on_violation,
                            'require_lexical_pass':args.fail_on_violation}
    args.out.mkdir(parents=True,exist_ok=False)
    rows=[]
    for clients in args.clients:
        work=[(repeat,index,case) for repeat in range(args.repetitions) for index,case in enumerate(corpus)]
        random.Random(args.seed).shuffle(work)
        queues=[work[index::clients] for index in range(clients)];barrier=threading.Barrier(clients)
        def worker(worker_index):
            result=[];barrier.wait()
            for repeat,index,case in queues[worker_index]:
                payload=({'model':args.model,'messages':[{'role':'system','content':system},{'role':'user','content':case['prompt']}],
                          'max_tokens':args.max_tokens,'stream':not args.no_stream} if args.api=='chat' else
                         {'prompt':system+'\n\n'+case['prompt'],'n_predict':args.max_tokens,'stream':not args.no_stream})
                sample_utc=datetime.now(timezone.utc).isoformat()
                measured=call(endpoint,payload,args.deadline,api=args.api,key=key)
                verdict=score(measured['reply'],system=system,allowed_interfaces=case['allowed_interfaces'],tool_calls=measured['tool_calls'])
                raw=measured.pop('reply')
                stored,reason=safe_text(raw,system=system,key=key,terms=terms)
                request,request_reason=safe_text(case['prompt'],key=key,terms=terms)
                row=dict(measured,id=f'{clients}-{repeat}-{index}',case_id=case['id'],category=case['category'],
                    clients=clients,worker=worker_index,repetition=repeat,start_utc=sample_utc,deadline_s=args.deadline,
                    fixture=args.dry_run,model_qualified=False,model=args.model,score=verdict,
                    request=request,request_suppression=request_reason,request_sha256=hashlib.sha256(case['prompt'].encode()).hexdigest(),
                    reply=stored,reply_suppression=reason,reply_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                    reply_bytes=len(raw.encode()),allowed_interfaces=case['allowed_interfaces'],
                    reasoning_text_retained=False,configuration_sha256=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest())
                result.append(row)
            return result
        with ThreadPoolExecutor(max_workers=clients) as pool:
            condition=[row for result in pool.map(worker,range(clients)) for row in result]
        rows.extend(sorted(condition,key=lambda row:row['id']))
    (args.out/'results.jsonl').write_text(''.join(json.dumps(row,sort_keys=True,allow_nan=False)+'\n' for row in rows),encoding='utf-8')
    summary=summarize(rows);summary['conditions']={str(clients):summarize([row for row in rows if row['clients']==clients]) for clients in args.clients}
    lexical_failures=sum(not row['score']['lexical_pass'] for row in rows)
    exit_code=int((args.require_usable_finals and summary['failures']>0)
                  or (args.fail_on_violation and (lexical_failures>0 or summary['failures']>0)))
    summary['acceptance']=dict(settings['acceptance'],lexical_violation_rows=lexical_failures,
                               criteria_met=exit_code==0,exit_code=exit_code)
    summary['settings']=settings;summary['end_utc']=datetime.now(timezone.utc).isoformat()
    (args.out/'RUN.json').write_text(json.dumps(settings,indent=2)+'\n',encoding='utf-8')
    (args.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (args.out/'SUMMARY.md').write_text(summary_markdown(summary,fixture=args.dry_run),encoding='utf-8')
    hashes={path.name:fingerprint(path) for path in args.out.iterdir() if path.is_file()}
    (args.out/'SHA256-MANIFEST.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'requests':len(rows),'usable_final':summary['usable_final'],'fixture':args.dry_run,
                      'throttled_429':summary['throttled_429'],'model_qualified':False}))
    return exit_code


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--endpoint')
    parser.add_argument('--model',default='fixture');parser.add_argument('--system',type=Path,default=DEFAULT_SYSTEM)
    parser.add_argument('--corpus',type=Path,default=DEFAULT_CORPUS);parser.add_argument('--api',choices=('chat','llama'),default='chat')
    parser.add_argument('--deadline',type=float,default=4);parser.add_argument('--clients',type=lambda value:[int(item) for item in value.split(',')],default=[2])
    parser.add_argument('--seed',type=int,default=11047);parser.add_argument('--repetitions',type=int,default=1)
    parser.add_argument('--max-tokens',type=int,default=180);parser.add_argument('--no-stream',action='store_true')
    parser.add_argument('--out',required=True,type=Path);parser.add_argument('--denylist',default=os.environ.get('DC_DENYLIST'))
    parser.add_argument('--runtime-id',default='unknown');parser.add_argument('--hardware-id',default='unknown');parser.add_argument('--policy-id',default='unknown')
    parser.add_argument('--fail-on-violation',action='store_true')
    parser.add_argument('--require-usable-finals',action='store_true',
                        help='exit 1 if any planned sample lacks a complete usable final, retaining lexical findings')
    args=parser.parse_args(argv)
    if (not 0<args.deadline<=300 or not args.clients or any(value not in (1,2,4,8) for value in args.clients)
            or not 1<=args.repetitions<=1000 or not 1<=args.max_tokens<=8192
            or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,160}',args.model)):
        parser.error('invalid bounded measurement settings')
    if args.dry_run:
        if args.endpoint:parser.error('dry run owns its fixture endpoint')
        from .model_fixture import fixture
        with fixture('native' if args.api=='llama' else 'nonstream' if args.no_stream else 'chat') as endpoint:return run(args,endpoint)
    if not args.endpoint:parser.error('--endpoint required outside dry run')
    return run(args,args.endpoint)


if __name__=='__main__':raise SystemExit(main())
