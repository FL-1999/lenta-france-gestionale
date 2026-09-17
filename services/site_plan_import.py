"""Conservative vector PDF import. Proposals are never approved automatically.

PDFs have drawing primitives, not semantic panel objects. Text orientation and
nearby edges/quotations yield editable proposals; uncertain boundaries remain
explicitly marked for review. Original colours are not interpreted as progress.
"""
from collections import Counter
from io import BytesIO
import math
import re
from statistics import median
from threading import Lock
from uuid import uuid4

MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PANELS = 500
_PDF_RENDER_LOCK = Lock()  # PDFium calls must not run concurrently in worker threads.


def _tokens(chars, height):
    runs, run = [], []
    previous = None
    for ch in chars:
        matrix = ch.get('matrix', (1, 0, 0, 1, ch['x0'], height-ch['bottom']))
        a, b, _, _, x, y = matrix
        if previous:
            pa, pb, _, _, px, py = previous['matrix']
            step = previous.get('adv', 0)
            close = math.hypot(x-px-step*pa, y-py-step*pb) < max(2, ch['size']*.65)
            same = abs(a-pa)+abs(b-pb) < .01
            if not close or not same:
                if run: runs.append(run)
                run = []
        run.append(ch)
        previous = {**ch, 'matrix': matrix}
    if run: runs.append(run)
    result = []
    for run in runs:
        text = ''.join(c['text'] for c in run).strip()
        if not text: continue
        a, b = run[0]['matrix'][:2]
        angle = math.atan2(-b, a)
        result.append({'text':text,
            'x':(min(c['x0'] for c in run)+max(c['x1'] for c in run))/2,
            'y':(min(c['top'] for c in run)+max(c['bottom'] for c in run))/2,
            'angle':angle, 'size':max(c['size'] for c in run)})
    return result


def _segments(page):
    segments = []
    for obj in page.lines + page.curves + page.rects:
        # CAD text masks are white filled polygons, not physical boundaries.
        if not obj.get('stroke', False): continue
        color=obj.get('stroking_color')
        if isinstance(color,(tuple,list)) and color and all(c>=.95 for c in color): continue
        pts = list(obj.get('pts', []))
        if obj.get('object_type')=='rect' and pts and pts[-1]!=pts[0]: pts.append(pts[0])
        if len(pts) < 2: continue
        # Curves with Bezier commands are not panel edges.
        if any(cmd[0] == 'c' for cmd in obj.get('path', [])): continue
        for a,b in zip(pts, pts[1:]):
            if math.dist(a,b) > 3: segments.append((a,b))
    return segments


def _geometry(token, segments, target_length=None):
    x,y,angle = token['x'],token['y'],token['angle']
    ux,uy = math.cos(angle),math.sin(angle)
    def local(pt):
        dx,dy=pt[0]-x,pt[1]-y
        return dx*ux+dy*uy, -dx*uy+dy*ux
    sides,ends=[],[]
    for a,b in segments:
        u,v=local(a),local(b)
        if abs(u[1]-v[1]) < 1.5 and min(u[0],v[0])-2<=0<=max(u[0],v[0])+2:
            sides.append((u[1]+v[1])/2)
        if abs(u[0]-v[0]) < 1.5 and min(u[1],v[1])-3<=0<=max(u[1],v[1])+3:
            ends.append((u[0]+v[0])/2)
    def bounds(values, limit):
        lo=[v for v in values if -limit<v<-1]
        hi=[v for v in values if 1<v<limit]
        return (max(lo),min(hi)) if lo and hi else None
    thickness=bounds(sides, max(25,token['size']*2))
    length=bounds(ends, max(180,token['size']*15))
    if target_length:
        pairs=[(lo,hi) for lo in ends for hi in ends if lo < -1 and hi > 1
               and abs((hi-lo)/target_length-1)<.06]
        if pairs: length=min(pairs,key=lambda pair:abs(pair[1]-pair[0]-target_length))
    exact=bool(thickness and length and length[1]-length[0]>token['size']*2)
    lo,hi=length or (-token['size']*3,token['size']*3)
    bottom,top=thickness or (-max(4,token['size']*.6),max(4,token['size']*.6))
    points=[[round(x+u*ux-v*uy,3),round(y+u*uy+v*ux,3)]
            for u,v in [(lo,bottom),(hi,bottom),(hi,top),(lo,top)]]
    return points, exact


def _dimension(label, dimensions):
    candidates=[]
    ux,uy=math.cos(label['angle']),math.sin(label['angle'])
    for d in dimensions:
        if abs(math.cos(d['angle']-label['angle'])) < .98: continue
        dx,dy=d['x']-label['x'],d['y']-label['y']
        along,across=abs(dx*ux+dy*uy),abs(-dx*uy+dy*ux)
        if along < max(18,label['size']*1.5) and across < 180:
            candidates.append((across+3*along,d))
    candidates.sort(key=lambda v:v[0])
    if not candidates: return None
    # Nearby conflicting quotations require human confirmation.
    if len(candidates)>1 and candidates[1][0]-candidates[0][0]<10 and candidates[1][1]['text']!=candidates[0][1]['text']:
        return None
    return float(candidates[0][1]['text'].replace(',','.'))


def scaled_points(points, length):
    """Resize both longitudinal edges equally about their centres, preserving rotation."""
    result=[list(p) for p in points]
    for i,j in ((0,1),(3,2)):
        a,b=points[i],points[j]; old=math.dist(a,b)
        if old<=0: continue
        dx,dy=(b[0]-a[0])/old,(b[1]-a[1])/old
        cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
        result[i]=[cx-dx*length/2,cy-dy*length/2]
        result[j]=[cx+dx*length/2,cy+dy*length/2]
    return result


def layout_scale(layout):
    if layout.get('scale_ppm'): return layout['scale_ppm']
    ratios=[math.dist(*p['points'][:2])/p['width_m'] for p in layout['panels']
            if p.get('width_m') and p.get('recognition')=='edges']
    return median(ratios) if ratios else None


def needs_extent_review(points, reference, width, height, tolerance=2):
    """Detect departures from recognised geometry, not a guessed building boundary."""
    if any(not 0<=x<=width or not 0<=y<=height for x,y in points): return True
    if not reference: return False
    area=sum(reference[i][0]*reference[(i+1)%4][1]-reference[(i+1)%4][0]*reference[i][1] for i in range(4))
    sign=1 if area>=0 else -1
    for x,y in points:
        for i,a in enumerate(reference):
            b=reference[(i+1)%4]; length=math.dist(a,b)
            if length and sign*((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])) < -tolerance*length:
                return True
    return False


def import_pdf(data: bytes, page_number: int = 1):
    import pdfplumber
    import pypdfium2 as pdfium
    if not data.startswith(b'%PDF-') or len(data)>MAX_PDF_BYTES:
        raise ValueError('Carica un PDF valido, massimo 15 MB.')
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not 1<=page_number<=len(pdf.pages):
                raise ValueError('La pagina selezionata non esiste nel PDF.')
            page=pdf.pages[page_number-1]
            w,h=float(page.width),float(page.height)
            if min(w,h)<=0 or max(w,h)>15000:
                raise ValueError('Dimensioni del foglio non supportate.')
            if len(page.chars)>50000 or sum(len(page.objects.get(k,[])) for k in ('curve','line','rect'))>25000:
                raise ValueError('Disegno troppo complesso: esporta la sola pianta dei pannelli.')
            tokens=_tokens(page.chars,h)
            labels=[t for t in tokens if re.fullmatch(r'P\s*\d{1,5}[A-Za-z]{0,2}',t['text'],re.I)]
            dims=[t for t in tokens if re.fullmatch(r'\d{1,2}[,.]\d{1,3}',t['text']) and 0<float(t['text'].replace(',','.'))<=50]
            if len(labels)>MAX_PANELS: raise ValueError('Sono supportati al massimo 500 pannelli per pianta.')
            segments=_segments(page)
            panels=[]
            for label in labels:
                points,exact=_geometry(label,segments)
                width=_dimension(label,dims)
                panels.append({'key':uuid4().hex,'label':re.sub(r'\s+','',label['text']),
                    'points':points, 'reference_points':points,
                    'width_m':width,'element':None,'reviewed':False,
                    'recognition':'edges' if exact else 'estimated',
                    'warnings':([] if exact else ['Contorno da verificare'])+([] if width else ['Larghezza da inserire'])})
            counts=Counter(p['label'].upper() for p in panels)
            scales=[math.dist(p['points'][0],p['points'][1])/p['width_m'] for p in panels if p['width_m'] and p['recognition']=='edges']
            typical=median(scales) if scales else None
            for p,label in zip(panels,labels):
                if counts[p['label'].upper()]>1: p['warnings'].append('Sigla ripetuta: verificare il collegamento')
                if typical and p['width_m']:
                    target=p['width_m']*typical
                    points,exact=_geometry(label,segments,target)
                    if abs(math.dist(*p['points'][:2])/target-1)>.15:
                        p['warnings'].append('Possibile sbordo: controllare gli estremi rispetto al PDF')
                    p['points']=scaled_points(points,target)
            pages=len(pdf.pages)
        with _PDF_RENDER_LOCK, pdfium.PdfDocument(data) as doc:
            page=doc[page_number-1]
            bitmap=page.render(scale=min(2,1800/max(w,h)))
            try:
                out=BytesIO(); bitmap.to_pil().save(out,format='PNG',optimize=True)
                preview=out.getvalue()
            finally:
                bitmap.close();page.close()
        return {'width':w,'height':h,'panels':panels,'page_count':pages,'scale_ppm':typical,
                'notice': 'Verifica contorni, sigle e larghezze prima della convalida.' if panels else
                'Nessun pannello riconosciuto. Puoi tracciarlo sull’originale; scansioni e sigle diverse da P… richiedono inserimento manuale.'},preview
    except ValueError: raise
    except Exception as exc:
        raise ValueError('PDF non leggibile o protetto. Esporta un nuovo PDF e riprova.') from exc
