"""Direct bounded chat/SSE and llama.cpp completion measurement, standard library.

No redirects, proxy inheritance, retries or payload logs. DNS is a killable
subprocess. First-content time excludes role-only and hidden-reasoning deltas.
Transport completion, usable final output and natural termination are distinct.
"""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


def decode(raw):
    def rejected(value):raise ValueError('nonfinite JSON')
    def pairs(items):
        if len({key for key,value in items})!=len(items):raise ValueError('duplicate JSON key')
        return dict(items)
    return json.loads(raw,parse_constant=rejected,object_pairs_hook=pairs)


def resolve(host,deadline):
    try:return str(ipaddress.ip_address(host))
    except ValueError:pass
    remaining=min(.15,deadline-time.monotonic())
    if remaining<=0:raise TimeoutError('deadline')
    code='import socket,sys; print(socket.getaddrinfo(sys.argv[1],None,socket.AF_INET,socket.SOCK_STREAM)[0][4][0])'
    env={name:value for name,value in os.environ.items() if name.upper() in {'PATH','SYSTEMROOT','WINDIR'}}
    result=subprocess.run([sys.executable,'-I','-c',code,host],capture_output=True,timeout=remaining,env=env)
    if result.returncode or len(result.stdout)>64:raise OSError('resolver failed')
    return str(ipaddress.ip_address(result.stdout.decode().strip()))


def call(endpoint,payload,budget,*,api='chat',key=None):
    """Measure one complete attempt. Failures return class-only safe metadata.

    Returned reply exists in memory only; callers must apply the export filter
    before persistence. A complete HTTP200 with length termination is not usable.
    """
    entered=time.monotonic();deadline=entered+budget
    row={'http_status':None,'http_complete':False,'usable_final':False,'failure':None,
         'time_to_first_content_s':None,'complete_response_s':None,'elapsed_s':None,
         'finish_reason':None,'reply':'','tool_calls':False,'wire_api':api,
         'tokens':{'prompt':None,'completion':None,'reasoning':None,'cached':None},
         'native_timings':None,'dns_s':None,'connection_setup_s':None}
    conn=None;active=[None];timer=None;setup_timer=None
    def abort():
        sock=(conn.sock if conn else None) or active[0]
        if sock:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    def content(text):
        if not isinstance(text,str):raise ValueError('malformed content')
        if text:
            if row['time_to_first_content_s'] is None:row['time_to_first_content_s']=time.monotonic()-entered
            row['reply']+=text
    def usage(value):
        if value is None:return
        if not isinstance(value,dict):raise ValueError('malformed usage')
        completion=value.get('completion_tokens_details');prompt=value.get('prompt_tokens_details')
        if completion is not None and not isinstance(completion,dict) or prompt is not None and not isinstance(prompt,dict):raise ValueError('malformed usage details')
        fields={'prompt':value.get('prompt_tokens'),'completion':value.get('completion_tokens'),
                'reasoning':(completion or {}).get('reasoning_tokens'),
                'cached':(prompt or {}).get('cached_tokens')}
        for name,item in fields.items():
            if type(item) is int and item>=0:row['tokens'][name]=item
    def packet(value,streaming):
        if not isinstance(value,dict):raise ValueError('malformed envelope')
        if api=='llama':
            if 'content' not in value:raise ValueError('malformed native envelope')
            for flag in ('stop','stopped_limit','stopped_eos','stopped_word'):
                if flag in value and type(value[flag]) is not bool:raise ValueError('malformed native stop flag')
            content(value['content'])
            if value.get('stop') is True:
                row['finish_reason']=('length' if value.get('stopped_limit') or value.get('stop_type')=='limit' else
                    'stop' if value.get('stopped_eos') or value.get('stopped_word') or value.get('stop_type') in {'eos','word'} else 'unknown')
            for name,field in [('prompt','tokens_evaluated'),('completion','tokens_predicted')]:
                if type(value.get(field)) is int and value[field]>=0:row['tokens'][name]=value[field]
            if type(value.get('tokens_cached')) is int and value['tokens_cached']>=0:row['tokens']['cached']=value['tokens_cached']
            if isinstance(value.get('timings'),dict):
                row['native_timings']={name:value['timings'][name] for name in ('prompt_ms','predicted_ms','prompt_n','predicted_n')
                                       if type(value['timings'].get(name)) in (int,float)}
            return
        usage(value.get('usage'))
        choices=value.get('choices')
        if choices==[] and value.get('usage') is not None:return
        if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):raise ValueError('malformed envelope')
        choice=choices[0];message=choice.get('delta' if streaming else 'message')
        if not isinstance(message,dict):raise ValueError('malformed message')
        if message.get('role') not in ({None,'assistant'} if streaming else {'assistant'}):raise ValueError('malformed role')
        if message.get('tool_calls') or message.get('function_call'):row['tool_calls']=True
        part=message.get('content')
        if part is not None:content(part)
        if choice.get('finish_reason') is not None:row['finish_reason']=str(choice['finish_reason'])
    try:
        target=urlsplit(endpoint)
        if target.scheme not in {'http','https'} or not target.hostname or target.username or target.password or target.query or target.fragment:
            raise ValueError('invalid endpoint')
        if api not in {'chat','llama'} or not 0<budget<=300:raise ValueError('invalid measurement settings')
        port=target.port or (443 if target.scheme=='https' else 80)
        before=time.monotonic();address=resolve(target.hostname,deadline);row['dns_s']=time.monotonic()-before
        timeout=min(.15,max(.001,deadline-time.monotonic()))
        if target.scheme=='https':
            context=ssl.create_default_context(cafile=os.environ.get('BENCH_CA_FILE') or None)
            conn=http.client.HTTPSConnection(target.hostname,port,timeout=timeout,context=context)
        else:conn=http.client.HTTPConnection(target.hostname,port,timeout=timeout)
        setup_deadline=min(deadline,time.monotonic()+.15)
        def connect_numeric(unused,timeout,source=None):
            family=socket.AF_INET6 if ipaddress.ip_address(address).version==6 else socket.AF_INET
            sock=socket.socket(family,socket.SOCK_STREAM);active[0]=sock
            try:
                remaining=setup_deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('setup deadline')
                sock.settimeout(remaining);sock.connect((address,port))
                sock.settimeout(max(.001,setup_deadline-time.monotonic()));return sock
            except BaseException:sock.close();raise
        conn._create_connection=connect_numeric
        timer=threading.Timer(max(0,deadline-time.monotonic()),abort);timer.daemon=True;timer.start()
        setup_timer=threading.Timer(max(0,setup_deadline-time.monotonic()),abort);setup_timer.daemon=True;setup_timer.start()
        before=time.monotonic();conn.connect();row['connection_setup_s']=time.monotonic()-before;setup_timer.cancel()
        if time.monotonic()>=setup_deadline:raise TimeoutError('setup deadline')
        conn.sock.settimeout(max(.001,deadline-time.monotonic()))
        headers={'Content-Type':'application/json','Accept':'text/event-stream, application/json'}
        if key:headers['Authorization']='Bearer '+key
        conn.request('POST',target.path or '/',json.dumps(payload),headers)
        response=conn.getresponse();row['http_status']=response.status
        if response.status!=200:
            response.read(1024*1024+1)
            row['http_complete']=response.length in (None,0)
            row['complete_response_s']=time.monotonic()-entered if row['http_complete'] else None
            row['failure']='throttled_429' if response.status==429 else 'http_error'
        elif 'text/event-stream' in response.getheader('Content-Type',''):
            size=0;done=False
            while True:
                line=response.readline(65537)
                if not line:break
                size+=len(line)
                if size>1024*1024:raise ValueError('response limit')
                if not line.startswith(b'data:'):continue
                if not line.endswith(b'\n'):raise http.client.IncompleteRead(line)
                data=line[5:].strip()
                if not data:continue
                if data==b'[DONE]':done=True;continue
                packet(decode(data),True)
            row['http_complete']=response.length in (None,0)
            row['complete_response_s']=time.monotonic()-entered if row['http_complete'] else None
            if not row['http_complete'] or (api=='chat' and not done) or row['finish_reason'] is None:
                row['failure']='incomplete_stream'
        else:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('response limit')
            packet(decode(raw),False)
            row['http_complete']=response.length in (None,0)
            row['complete_response_s']=time.monotonic()-entered if row['http_complete'] else None
        row['usable_final']=bool(row['http_status']==200 and row['http_complete'] and row['reply']
                                 and row['finish_reason']=='stop' and not row['tool_calls']
                                 and not row['failure'] and time.monotonic()<deadline)
        if not row['usable_final'] and row['failure'] is None:
            row['failure']='truncated_final' if row['finish_reason']=='length' else 'empty_or_unsupported_final'
    except subprocess.TimeoutExpired:row['failure']='dns_deadline'
    except (TimeoutError,socket.timeout):row['failure']='deadline_or_setup_timeout'
    except http.client.IncompleteRead:row['failure']='incomplete_body'
    except (OSError,http.client.HTTPException):
        row['failure']='deadline_incomplete' if time.monotonic()>=deadline-.01 else 'connection_or_http_failure'
    except (ValueError,TypeError,KeyError,IndexError):row['failure']='malformed_or_rejected_envelope'
    finally:
        if setup_timer:setup_timer.cancel()
        if timer:timer.cancel()
        if conn:conn.close()
        row['elapsed_s']=time.monotonic()-entered
        if row['elapsed_s']>=budget:
            row['usable_final']=False
            row['failure']='deadline_'+(row['failure'] or 'exceeded')
    return row
