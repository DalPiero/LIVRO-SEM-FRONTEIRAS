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



def corrigir_codificacao(texto):
    """Repara somente padrões inequívocos de UTF-8 interpretado como Latin-1."""
    if not isinstance(texto,str):return texto
    for _ in range(2):
        if not any(x in texto for x in ('Ã','Â','â€','â€™','â€œ','â€“','â€”')):break
        try:
            novo=texto.encode('latin-1').decode('utf-8')
        except (UnicodeError,ValueError):
            try:novo=texto.encode('cp1252').decode('utf-8')
            except (UnicodeError,ValueError):break
        if novo==texto:break
        texto=novo
    return texto


def source_items(html):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    seen = set()
    # Each original entry is a heading followed by a Google Drive link.
    for h in soup.find_all(re.compile('^h[2-6]$')):
        title = corrigir_codificacao(h.get_text(' ', strip=True))
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
            out.append({'title':corrigir_codificacao(heading.get_text(' ',strip=True)), 'url':href,'id':m.group(1),'source':'Catálogo público','kind':'arquivo'})
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


_cover_cache = {}
def publisher_cover(page_url):
    """Recupera somente a imagem declarada como capa social pela editora oficial."""
    parsed=urlparse(page_url)
    if parsed.hostname not in ('clubedeautores.com.br','www.clubedeautores.com.br'):
        return ''
    cache=_cover_cache.get(page_url)
    if cache and time.time()-cache[0]<86400:
        return cache[1]
    value=''
    try:
        response=requests.get(page_url,timeout=7,headers={'User-Agent':'Mozilla/5.0 LivroSemFronteiras/1.0'})
        response.raise_for_status()
        soup=BeautifulSoup(response.text,'html.parser')
        tags=[soup.find('meta',attrs={'property':'og:image'}),soup.find('meta',attrs={'name':'twitter:image'})]
        candidates=[t.get('content','').strip() for t in tags if t]
        for el in soup.select('img[itemprop="image"], img[class*="cover"], img[class*="capa"], img[src*="capa"], img[src*="cover"]')[:12]:
            url=el.get('data-src') or el.get('src') or ''
            if url: candidates.append(url.strip())
        from urllib.parse import urljoin
        for candidate in candidates:
            candidate=urljoin(page_url,candidate)
            if candidate.startswith('https://') and urlparse(candidate).hostname:
                value=candidate
                break
    except (requests.RequestException,ValueError):
        pass
    _cover_cache[page_url]=(time.time(),value)
    return value

@app.get('/capa/<int:numero>')
def capa_editorial(numero):
    from flask import abort, Response
    livros=curated_items()
    if numero<1 or numero>len(livros):abort(404)
    url=publisher_cover(livros[numero-1]['url'])
    if not url:abort(404)
    try:
        resp=requests.get(url,timeout=10,headers={'User-Agent':'Mozilla/5.0','Referer':livros[numero-1]['url']})
        resp.raise_for_status()
        mime=resp.headers.get('Content-Type','').split(';')[0].lower()
        if mime not in ('image/jpeg','image/png','image/webp') or len(resp.content)>5000000:abort(404)
        return Response(resp.content,mimetype=mime,headers={'Cache-Control':'public, max-age=3600'})
    except requests.RequestException:abort(404)

def collect(force=False):
    now=time.time()
    if not force and now < _cache['expires']:return dict(_cache)
    with _lock:
        now=time.time()
        if not force and now < _cache['expires']:return dict(_cache)
        try:
            r=requests.get(SOURCE_URL,timeout=18,headers={'User-Agent':'LivroSemFronteirasCatalogo/1.0 (public-library-catalog)'})
            r.raise_for_status()
            r.encoding=r.apparent_encoding if r.encoding is None or r.encoding.lower() in ('iso-8859-1','latin-1') else r.encoding
            items=source_items(r.text)
            if not items:raise ValueError('A página não forneceu registros de livros identificáveis.')
            _cache.update(items=items,updated_at=int(time.time()),expires=now+CACHE_SECONDS,error=None)
        except Exception as exc:
            # Keep last valid dataset on temporary upstream failure.
            _cache.update(error=f'Não foi possível atualizar o catálogo público: {type(exc).__name__}',expires=now+300)
        return dict(_cache)

@app.get('/')
def home():return render_template('index.html')


@app.get('/audio/<int:number>.wav')
def generated_music(number):
    """Arranjo instrumental digital original, sem arquivos binários externos."""
    import io, math, struct, wave
    from flask import send_file, abort
    if number < 1 or number > 15: abort(404)
    motifs = [
      [0,2,4,7,9,7,4,2], [0,4,7,9,7,4,2,0],
      [4,7,9,12,9,7,4,2], [0,2,5,7,5,2,0,-3],
      [0,4,5,9,7,5,4,0], [0,5,7,12,9,7,5,2],
      [0,2,4,9,7,4,2,0], [0,3,5,7,10,7,5,3],
      [2,4,7,9,12,9,7,4], [0,5,9,12,9,5,4,0],
      [0,2,7,9,7,5,2,0], [0,4,7,11,9,7,4,2],
      [0,2,4,5,7,5,4,2], [0,4,9,7,5,4,2,0],
      [0,5,7,9,12,9,7,0],
    ]
    # Quinze arranjos distintos: andamento, duração, registro e timbre variáveis.
    rate=11025
    bpm=[66,82,108,57,94,74,122,68,88,100,62,116,70,96,80][number-1]
    style=(number-1)%5
    base=[196,220,246.94,174.61,261.63][style]
    melody=motifs[number-1]
    notes=(melody+list(reversed(melody)))*2
    out=io.BytesIO()
    with wave.open(out,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        for index,step in enumerate(notes):
            beats=(.5 if index%4==3 else 1.0) * (1.5 if index%7==0 else 1.0)
            note_samples=int(rate*60/bpm*beats)
            hz=base*2**(step/12)
            frames=bytearray()
            for i in range(note_samples):
                t=i/rate
                attack=min(1.0,i/(rate*.03))
                release=min(1.0,(note_samples-i)/(rate*.13))
                envelope=max(0,min(attack,release))
                phase=2*math.pi*hz*t
                if style==0: wave_value=math.sin(phase)+.3*math.sin(phase*2)
                elif style==1: wave_value=math.sin(phase)+.2*math.sin(phase*3)+.15*math.sin(phase*4)
                elif style==2: wave_value=math.sin(phase)+.35*math.sin(phase*2)+.2*math.sin(phase*5)
                elif style==3: wave_value=math.sin(phase)+.25*math.sin(phase*.5)
                else: wave_value=math.sin(phase)+.2*math.sin(phase*2)+.1*math.sin(phase*6)
                value=int(7000*envelope*wave_value/1.6)
                frames.extend(struct.pack('<h',max(-32768,min(32767,value))))
            wav.writeframesraw(frames)
    out.seek(0)
    response=send_file(out,mimetype='audio/wav',download_name=f'livro-sem-fronteiras-{number:02d}.wav')
    response.headers['Cache-Control']='no-store'
    return response

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
    enriched_count=0
    for item in state['items']+extras:
        key=item['id'].lower()
        if key in seen:continue
        seen.add(key)
        enriched=dict(item)
        metadata=extra_by_id.get(key) or extra_by_url.get(item['url'].rstrip('/').lower())
        if metadata:
            if item in state['items']: enriched_count+=1
            for field in ('language','author','edition','verified_at','source_url'):
                if metadata.get(field):enriched[field]=metadata[field]
            if metadata.get('summary') and metadata.get('summary_verified'):enriched['summary']=metadata['summary'];enriched['summary_verified']=True
            if metadata.get('cover_url') and metadata.get('cover_verified'):enriched['cover_url']=metadata['cover_url'];enriched['cover_verified']=True
        if enriched.get('source')=='Clube de Autores' and not enriched.get('cover_url'):
            cover=publisher_cover(enriched['url'])
            if cover:
                enriched['cover_preview_url']='/capa/'+str(extras.index(metadata)+1) if metadata in extras else cover
                enriched['cover_verified']=False
        merged.append(enriched)
    # If upstream hasn't been fetched yet or is inaccessible, show only verified curated records.
    return jsonify(count=len(merged),source_count=len(state['items']),additional_count=sum(1 for item in merged if item['id'].lower() not in {r['id'].lower() for r in state['items']}),enriched_count=enriched_count,updated_at=state['updated_at'],warning=state['error'],items=merged)

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
