"""Conservative response export policy; reversible encoding is never redaction.

Assess decoded structured fields before retaining bytes. Unsupported/ambiguous
or malformed formats are suppressed, without claiming a credential was proven.
Headers use a tiny value-validated projection, not arbitrary server strings.
"""

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl

from .privacy import FIELDS as CREDENTIALS, PRIVATE as PRIVATE_KEY, PROVIDER

REDACTED = '[redacted]'


KEYS = "|".join(re.escape(key) for key in sorted(CREDENTIALS))
SENSITIVE = re.compile(rf'''(?i)(?:\b(?:{KEYS})\b["']?\s*[:=]|<(?:\w+:)?(?:{KEYS})\b|\bname\s*=\s*["'](?:{KEYS})["'])''')
HTML = {"html", "head", "body", "p", "div", "span", "meta", "title", "br", "h1", "h2"}
MEDIA = {"application/json", "text/plain", "text/html", "application/xml", "text/xml",
         "application/x-www-form-urlencoded", "multipart/form-data"}


def assessment(body, headers):
    """Return (credential_detected, suppress, reason), without raw values."""
    try:
        text = body.decode("utf-8", "strict")
    except UnicodeError:
        return False, True, "unsupported_encoding"
    media = next((value.split(";", 1)[0].strip().lower() for key, value in headers if key.lower() == "content-type"), "")
    literal = bool(SENSITIVE.search(text) or PROVIDER.search(text) or PRIVATE_KEY.search(text))
    detected, ambiguous = literal, False
    def pairs(items):
        nonlocal ambiguous
        if len({key for key, _ in items}) != len(items):
            ambiguous = True
        return dict(items)
    def inspect(value):
        nonlocal ambiguous
        if isinstance(value, dict):
            return any(key.casefold() in CREDENTIALS or inspect(item) for key, item in value.items())
        if isinstance(value, list):
            return any(inspect(item) for item in value)
        if isinstance(value, str):
            # Embedded structured/escaped strings have another interpretation
            # layer. Suppress rather than guess or export reversible bytes.
            if value.lstrip().startswith(("{", "[", "<")) or re.search(r"\\[ux]|%[0-9a-fA-F]{2}", value):
                ambiguous = True
            return bool(SENSITIVE.search(value) or PROVIDER.search(value) or PRIVATE_KEY.search(value))
        return False
    stripped = text.lstrip()
    if media == "multipart/form-data" or "content-disposition:" in text.casefold():
        return detected, True, "unsupported_multipart"
    if media == "application/json" or stripped.startswith(("{", "[")):
        try:
            decoded = json.loads(text, object_pairs_hook=pairs)
            detected |= inspect(decoded)
        except (ValueError, RecursionError):
            return detected, True, "malformed_json"
        return detected, detected or ambiguous, "credential" if detected else "ambiguous_json" if ambiguous else "safe_json"
    if stripped.startswith("<") or media in {"application/xml", "text/xml", "text/html"}:
        if "<!" in text:
            return detected, True, "unsupported_markup"
        try:
            root = ET.fromstring(text)
        except (ValueError, ET.ParseError):
            return detected, True, "malformed_markup"
        local = lambda name: name.rsplit("}", 1)[-1].casefold()
        for element in root.iter():
            detected |= local(element.tag) in CREDENTIALS
            detected |= any(local(key) in CREDENTIALS or (local(key) in {"name", "id"} and value.casefold() in CREDENTIALS)
                            for key, value in element.attrib.items())
            detected |= inspect(element.text or "") or inspect(element.tail or "")
            for value in element.attrib.values():
                detected |= inspect(value)
        supported = not ambiguous and all(local(element.tag) in HTML and all(
            local(key) == "charset" and value.casefold() in {"utf-8", "utf8", "us-ascii"}
            for key, value in element.attrib.items()) for element in root.iter())
        return detected, detected or not supported, "credential" if detected else "safe_html" if supported else "unsupported_xml"
    if media == "application/x-www-form-urlencoded" or "=" in text:
        try:
            decoded = parse_qsl(text, keep_blank_values=True, strict_parsing=True)
            detected |= any(key.casefold() in CREDENTIALS or inspect(value) for key, value in decoded)
        except ValueError:
            return detected, True, "ambiguous_form"
        return detected, True, "credential" if detected else "unsupported_form"
    if media not in {"", "text/plain"} or re.search(r"\\[ux]|%[0-9a-fA-F]{2}", text):
        return detected, True, "unsupported_or_escaped"
    return detected, detected, "credential" if detected else "safe_text"


def safe_headers(headers):
    """Keep validated media/length only; known credential headers are masked.

    Unknown header names and values are omitted, since either may contain a
    reflected credential. No raw Server, Location, cookie or receipt is kept.
    """
    result = {}
    for key, value in headers:
        name = key.casefold()
        if name in CREDENTIALS | {"set-cookie"}:
            result[key] = REDACTED
        elif name == "content-type":
            media = value.split(";", 1)[0].strip().lower()
            if media in MEDIA:
                result["Content-Type"] = media
        elif name == "content-length" and re.fullmatch(r"[0-9]{1,12}", value):
            result["Content-Length"] = value
    return result
