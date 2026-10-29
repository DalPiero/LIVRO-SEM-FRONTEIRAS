"""Livro sem Fronteiras — catálogo público sincronizado, sem credenciais."""
import os, json, re, time, threading
from urllib.parse import urlparse
from flask import Flask, jsonify, render_template, request
import requests
from bs4 import BeautifulSoup

app = Flask(__name__, static_folder='static', template_folder='templates')
SOURCE_URL = os.environ.get('CATALOG_SOURCE_URL', 'https://livro-sem-fronteiras-dal-piero.fadal573536.chatgpt.site/')
CACHE_SECONDS = int(os.environ.get('CACHE_SECONDS', '10800'))
_cache = {'items': [], 'updated_at': None, 'expires': 0, 'error': None}
_lock = threading.Lock()


def source_items(html):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    seen = set()
    # Each original entry is a heading followed by a Google Drive link.
    for h in soup.find_all(re.compile('^h[2-6]$')):
        title = h.get_text(' ', strip=True)
        if not title or len(title) > 270: continue
        # Search in document order until next heading; the public catalogue has one link per title.
        link = None
        node = h
        for _ in range(24):
            node = node.find_next()
            if node is None or (node.name in ('h2', 'h3', 'h4') and node is not h): break
            if node.name == 'a' and 'drive.google.com/file/d/' in (node.get('href') or ''):
                link = node.get('href'); break
        if not link: continue
        m = re.search(r'/file/d/([\w-]+)', link)
        if not m: continue
        ident = m.group(1)
        if ident in seen: continue
        seen.add(ident)
        out.append({'title': title, 'url': link, 'id': ident, 'source':'Catálogo público', 'kind':'arquivo'})
    # Fallback for alternate HTML nesting. Never fabricate titles.
    if not out:
        for a in soup.select('a[href*="drive.google.com/file/d/"]'):
            href=a.get('href',''); m=re.search(r'/file/d/([\w-]+)',href)
            if not m or m.group(1) in seen:continue
            parent=a.find_parent(['article','li','section'])
            heading=parent.find(['h2','h3','h4']) if parent else None
            if not heading:continue
            seen.add(m.group(1))
            out.append({'title':heading.get_text(' ',strip=True), 'url':href,'id':m.group(1),'source':'Catálogo público','kind':'arquivo'})
    return out


def curated_items():
    path=os.path.join(os.path.dirname(__file__),'catalogo_adicional.json')
    try:
        with open(path, encoding='utf-8') as f: entries=json.load(f)
    except (OSError, ValueError):return []
    clean=[]
    for e in entries:
        if not isinstance(e,dict):continue
        title=str(e.get('title','')).strip(); url=str(e.get('url','')).strip()
        if not title or not url or urlparse(url).scheme != 'https':continue
        clean.append({'title':title,'url':url,'id':str(e.get('id') or url),'source':str(e.get('source') or 'Inclusão editorial'),'kind':str(e.get('kind') or 'publicação'),'summary':str(e.get('summary') or '')[:1000],'cover_url':str(e.get('cover_url') or '') if str(e.get('cover_url') or '').startswith('https://') else '','language':str(e.get('language') or '')[:60],'author':str(e.get('author') or '')[:180],'summary_verified':bool(e.get('summary_verified',False)),'cover_verified':bool(e.get('cover_verified',False)),'source_url':str(e.get('source_url') or url) if urlparse(str(e.get('source_url') or url)).scheme=='https' else url,'edition':str(e.get('edition') or '')[:90],'verified_at':str(e.get('verified_at') or '')[:30]})
    return clean


def collect(force=False):
    now=time.time()
    if not force and now < _cache['expires']:return dict(_cache)
    with _lock:
        now=time.time()
        if not force and now < _cache['expires']:return dict(_cache)
        try:
            r=requests.get(SOURCE_URL,timeout=18,headers={'User-Agent':'LivroSemFronteirasCatalogo/1.0 (public-library-catalog)'})
            r.raise_for_status()
            items=source_items(r.text)
            if not items:raise ValueError('A página não forneceu registros de livros identificáveis.')
            _cache.update(items=items,updated_at=int(time.time()),expires=now+CACHE_SECONDS,error=None)
        except Exception as exc:
            # Keep last valid dataset on temporary upstream failure.
            _cache.update(error=f'Não foi possível atualizar o catálogo público: {type(exc).__name__}',expires=now+300)
        return dict(_cache)

@app.get('/')
def home():return render_template('index.html')

@app.get('/api/health')
def health():return jsonify(status='ok',service='livro-sem-fronteiras',catalog_source=SOURCE_URL)

@app.get('/api/catalog-audit')
def catalog_audit():
    state=collect()
    source=state['items']; curated=curated_items()
    ids={i['id'].lower() for i in source}
    verified_covers=sum(1 for i in curated if i.get('cover_verified') and i.get('cover_url'))
    verified_summaries=sum(1 for i in curated if i.get('summary_verified') and i.get('summary'))
    return jsonify(source_records=len(source),editorial_records=len(curated),new_records=sum(1 for i in curated if i['id'].lower() not in ids),verified_covers=verified_covers,verified_summaries=verified_summaries,source_warning=state['error'],last_source_sync=state['updated_at'])

@app.get('/api/catalog')
def catalog():
    state=collect()
    merged=[]; seen=set()
    extras=curated_items()
    extra_by_id={i['id'].lower():i for i in extras}
    extra_by_url={i['url'].rstrip('/').lower():i for i in extras}
    for item in state['items']+extras:
        key=item['id'].lower()
        if key in seen:continue
        seen.add(key)
        enriched=dict(item)
        metadata=extra_by_id.get(key) or extra_by_url.get(item['url'].rstrip('/').lower())
        if metadata:
            for field in ('language','author','edition','verified_at','source_url'):
                if metadata.get(field):enriched[field]=metadata[field]
            if metadata.get('summary') and metadata.get('summary_verified'):enriched['summary']=metadata['summary'];enriched['summary_verified']=True
            if metadata.get('cover_url') and metadata.get('cover_verified'):enriched['cover_url']=metadata['cover_url'];enriched['cover_verified']=True
        merged.append(enriched)
    # If upstream hasn't been fetched yet or is inaccessible, show only verified curated records.
    return jsonify(count=len(merged),source_count=len(state['items']),additional_count=len(merged)-len(state['items']),updated_at=state['updated_at'],warning=state['error'],items=merged)

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
