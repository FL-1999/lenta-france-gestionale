"""Translate only literal interface text in templates, never database/user values."""
import html
import json
import re
from pathlib import Path
from jinja2 import pass_context
from jinja2.ext import Extension

CATALOG_PATH=Path(__file__).parent/'static'/'i18n'/'fr.json'
CATALOG=json.loads(CATALOG_PATH.read_text(encoding='utf-8')) if CATALOG_PATH.exists() else {}
TOKENS=re.compile(r'({{.*?}}|{%.*?%}|{#.*?#}|<!--.*?-->|<[^>]+>)',re.S)
ATTR=re.compile(r'(?P<prefix>\b(?:placeholder|title|aria-label)\s*=\s*)(?P<quote>[\"\'])(?P<value>.*?)(?P=quote)',re.S)

def normalized(text): return re.sub(r'\s+',' ',html.unescape(text)).strip()

@pass_context
def ui_text(context,text):
    request=context.get('request')
    language=request.cookies.get('lang','it') if request else context.get('lang','it')
    return CATALOG.get(text,text) if language=='fr' else text


def expression(source):
    # Translate displayed string literals, not comparisons, keys or database values.
    literal=re.compile(r"(['\"])(?:\\.|(?!\1).)*?\1",re.S)
    def replace(match):
        raw=match[0]
        try:
            import ast
            value=ast.literal_eval(raw)
        except (ValueError,SyntaxError):return raw
        before=source[:match.start()].rstrip();after=source[match.end():].lstrip()
        if value not in CATALOG or after.startswith(':') or re.search(r'(==|!=|\bin|\bis|\.get\()$',before):return raw
        return 'ui_text('+raw+')'
    return literal.sub(replace,source)


def process(source, collect=False):
    skip=None; result=[]; found=set()
    def translated(raw):
        text=normalized(raw)
        if not text or not re.search(r'[A-Za-zÀ-ÿ]',text) or any(c in text for c in '{}'):return raw
        found.add(text)
        if collect or text not in CATALOG:return raw
        start=raw[:len(raw)-len(raw.lstrip())];end=raw[len(raw.rstrip()):]
        return start+'{{ ui_text('+json.dumps(text,ensure_ascii=False)+') }}'+end
    for token in TOKENS.split(source):
        if token.startswith(('<script','<style','<textarea','<pre','<code')):
            skip=re.match(r'<(\w+)',token)[1]
        if token.startswith('<'):
            if token.startswith('</') and skip and token.startswith('</'+skip):skip=None
            # Do not rewrite embedded JS or dynamic attributes.
            if (not skip or token.startswith('<textarea')) and not token.startswith(('<!--','<!')):
                token=ATTR.sub(lambda m:m['prefix']+m['quote']+translated(m['value'])+m['quote'],token)
        elif not skip and token.startswith('{{') and not collect:token=expression(token)
        elif not skip and not token.startswith(('{%','{{','{#')):token=translated(token)
        result.append(token)
    return sorted(found) if collect else ''.join(result)

class InterfaceTranslation(Extension):
    def __init__(self,environment):
        super().__init__(environment);environment.globals['ui_text']=ui_text
    def preprocess(self,source,name,filename=None):
        return process(source) if name and name.endswith('.html') and '/pdf' not in name else source
