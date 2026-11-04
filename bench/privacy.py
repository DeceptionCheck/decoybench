"""Standalone benchmark export filter, independent of private application policy.

Score original text in memory, then retain only a safe reply or a suppression
marker and fingerprint. Reversible encodings are not redaction. Suppressed rows
are explicitly not fully replayable from their exported content.
"""
import json
import re

FIELDS={'password','password_or_hash','passwd','pwd','pass','token','secret','authorization','cookie',
        'api_key','apikey','access_token','refresh_token','client_secret','set-cookie'}
PROVIDER=re.compile(r'(?:sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})')
PRIVATE=re.compile(r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----')
ASSIGN=re.compile(r'''(?i)\b(?:password|passwd|pwd|pass|token|secret|authorization|cookie|(?:\w+_)?api_?key)\b["']?\s*[:=]\s*\S+''')
XML=re.compile(r'(?i)<(?:\w+:)?(?:password|passwd|pwd|token|secret|authorization|cookie|api_?key)\b')


def words(value):return re.findall(r'[a-z0-9_]+',value.casefold())


def system_overlap(text,system):
    """Eight consecutive system words are a lexical signal, not semantic proof."""
    source,target=words(system),words(text)
    spans={tuple(source[index:index+8]) for index in range(max(0,len(source)-7))}
    return any(tuple(target[index:index+8]) in spans for index in range(max(0,len(target)-7)))


def safe_text(text,*,system='',key=None,terms=()):
    """Return (stored text, reason). Never copy a detected sensitive value."""
    if not isinstance(text,str):return '[REDACTED: unsupported text]','unsupported'
    reason=None
    if key and key in text:reason='configured_key_reflection'
    elif PROVIDER.search(text) or PRIVATE.search(text) or ASSIGN.search(text) or XML.search(text):reason='credential_pattern'
    elif system and system_overlap(text,system):reason='system_overlap'
    elif re.search(r'(?i)<\s*/?\s*(?:think|analysis)\b|\bchain.of.thought\b|^\s*analysis\s*:',text):reason='reasoning_markers'
    elif any(term.casefold() in text.casefold() for term in terms):reason='configured_denylist'
    def structured(value,depth=0):
        if depth>8:return True
        if isinstance(value,dict):return any(str(name).casefold() in FIELDS or structured(item,depth+1) for name,item in value.items())
        if isinstance(value,list):return any(structured(item,depth+1) for item in value)
        if isinstance(value,str):
            if PROVIDER.search(value) or PRIVATE.search(value) or ASSIGN.search(value) or XML.search(value):return True
            try:decoded=json.loads(value)
            except (ValueError,RecursionError):return False
            return structured(decoded,depth+1) if decoded!=value else False
        return False
    if reason is None:
        try:decoded=json.loads(text)
        except (ValueError,RecursionError):decoded=None
        if decoded is not None and structured(decoded):reason='structured_credential'
    return ('[REDACTED: sensitive benchmark text]',reason) if reason else (text,None)
