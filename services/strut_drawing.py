"""Conservative CAD proposals; no colour, circled count or raster table is treated as progress."""
from io import BytesIO
import math
import re
from statistics import median
from uuid import uuid4

from services.site_plan_import import MAX_PDF_BYTES, _PDF_RENDER_LOCK, _tokens, _segments, _dimension


def axis_proposal(label, segments):
    x,y = label['x'],label['y']
    u = (math.cos(label['angle']), math.sin(label['angle']))
    candidates = []
    for a,b in segments:
        length = math.dist(a,b)
        if length < 12:
            continue
        v = ((b[0]-a[0])/length, (b[1]-a[1])/length)
        if abs(u[0]*v[1]-u[1]*v[0]) > .025:
            continue
        if v[0]*u[0]+v[1]*u[1]<0:
            a,b=b,a; v=(-v[0],-v[1])
        offset = (x-a[0])*-v[1]+(y-a[1])*v[0]
        if abs(offset)>max(30,label['size']*2):
            continue
        # Join collinear CAD dashes, without assuming a specific drafting colour.
        ranges=[]
        for c,d in segments:
            if abs((c[0]-a[0])*-v[1]+(c[1]-a[1])*v[0])>1.2 or abs((d[0]-a[0])*-v[1]+(d[1]-a[1])*v[0])>1.2:
                continue
            lo,hi=sorted(((c[0]-a[0])*v[0]+(c[1]-a[1])*v[1], (d[0]-a[0])*v[0]+(d[1]-a[1])*v[1]))
            ranges.append((lo,hi))
        merged=[]
        for lo,hi in sorted(ranges):
            if merged and lo-merged[-1][1]<=max(45,label['size']*3):
                merged[-1][1]=max(hi,merged[-1][1])
            else:
                merged.append([lo,hi])
        along=(x-a[0])*v[0]+(y-a[1])*v[1]
        for lo,hi in merged:
            if lo-5<=along<=hi+5 and hi-lo>label['size']*5:
                candidates.append((abs(offset), [[a[0]+lo*v[0],a[1]+lo*v[1]], [a[0]+hi*v[0],a[1]+hi*v[1]]]))
    return min(candidates,key=lambda c:c[0])[1] if candidates else None


def read_pdf(data, page_number=1, crop=None):
    import pdfplumber
    import pypdfium2 as pdfium
    if len(data)>MAX_PDF_BYTES or not data.startswith(b'%PDF-'):
        raise ValueError('Carica un PDF valido, massimo 15 MB.')
    if crop is not None and (not isinstance(crop,list) or len(crop)!=4 or
            any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in crop) or
            crop[2]-crop[0]<.01 or crop[3]-crop[1]<.01):
        raise ValueError('Rettangolo di selezione non valido.')
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not 1<=page_number<=len(pdf.pages):
                raise ValueError('Pagina non presente nel PDF.')
            page=pdf.pages[page_number-1]; w,h=float(page.width),float(page.height)
            if min(w,h)<=0 or max(w,h)>15000 or len(page.chars)>50000 or sum(len(page.objects.get(k,[])) for k in ('line','curve','rect'))>25000:
                raise ValueError('Pagina troppo complessa. Esporta la sola pianta dei puntoni.')
            tokens=_tokens(page.chars,h)
            segments=_segments(page)
            if crop:
                tokens=[t for t in tokens if crop[0]*w<=t['x']<=crop[2]*w and crop[1]*h<=t['y']<=crop[3]*h]
                segments=[(a,b) for a,b in segments if all(crop[0]*w<=p[0]<=crop[2]*w and crop[1]*h<=p[1]<=crop[3]*h for p in (a,b))]
            labels=[]
            for t in tokens:
                match=re.fullmatch(r'(B\s*\d{1,4}(?:\s*[-/]\s*[A-Z0-9]+)?)\s*(?:[Øø∅]\s*(\d+(?:[.,]\d+)?)\s*[/xX]\s*(\d+(?:[.,]\d+)?))?',t['text'],re.I)
                if match:
                    labels.append((t,match))
            if len(labels)>300:
                raise ValueError('Troppi puntoni: seleziona una sola pianta o un livello.')
            dims=[t for t in tokens if re.fullmatch(r'\d{1,3}[,.]\d{1,3}',t['text'])]
            quoted_dims=[t for t in tokens if re.fullmatch(r'\d{1,3}(?:[,.]\d{1,3})?',t['text']) and float(t['text'].replace(',','.'))>0]
            rows=[]
            for t,m in labels:
                axis=axis_proposal(t,segments)
                rows.append(dict(id=uuid4().hex,label=re.sub(r'\s+','',m[1]).upper(),
                    a=axis[0] if axis else None,b=axis[1] if axis else None,
                    length_m=_dimension(t,dims), diameter_mm=float(m[2].replace(',','.')) if m[2] else None,
                    thickness_mm=float(m[3].replace(',','.')) if m[3] else None,
                    evidence=t['text'], reviewed=False))
            # Cross-check nearby quotations against a consensus drawing scale.
            # This discards an adjacent buton's dimension instead of trusting proximity alone.
            ratios=[math.dist(r['a'],r['b'])/r['length_m'] for r in rows if r['a'] and r['length_m']]
            scale=median(ratios) if len(ratios)>=3 else None
            if scale and sum(abs(v/scale-1)<.04 for v in ratios)<max(3,len(ratios)*.6):
                scale=None
            angles=[t for t in tokens if re.fullmatch(r'\d{1,3}(?:[.,]\d+)?\s*°',t['text'])]
            for row,(t,_) in zip(rows,labels):
                if not row['a']:
                    continue
                if scale:
                    expected=math.dist(row['a'],row['b'])/scale
                    choices=[d for d in quoted_dims if abs(float(d['text'].replace(',','.'))/expected-1)<.006
                             and abs(math.cos(d['angle']-t['angle']))>.98
                             and math.dist((d['x'],d['y']),(t['x'],t['y']))<max(180,math.dist(row['a'],row['b'])*.3)]
                    values={float(d['text'].replace(',','.')) for d in choices}
                    row['length_m']=values.pop() if len(values)==1 else None
                for end in ('a','b'):
                    candidates=sorted((math.dist(row[end],(a['x'],a['y'])),float(a['text'].replace('°','').replace(',','.'))) for a in angles)
                    row['angle_'+end]=candidates[0][1] if candidates and candidates[0][0]<100 and (len(candidates)==1 or candidates[1][0]-candidates[0][0]>15) else None
            rows.sort(key=lambda r:int(re.search(r'\d+',r['label'])[0]))
            result=dict(width=w,height=h,page_count=len(pdf.pages),crop=crop,struts=rows,
                evidence='\n'.join(t['text'] for t in tokens)[:20000],
                notice='Verifica assi, misure, angoli e appoggi. Quote, fissaggi e tabelle raster vanno completati dal PDF. I colori non indicano lo stato dei lavori.')
        with _PDF_RENDER_LOCK, pdfium.PdfDocument(data) as doc:
            page=doc[page_number-1]
            try:
                bitmap=page.render(scale=min(2,2400/max(w,h)))
                try:
                    out=BytesIO();bitmap.to_pil().save(out,format='PNG')
                finally:
                    bitmap.close()
            finally:
                page.close()
        return result,out.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF non leggibile o protetto. Esporta un nuovo PDF.') from exc
