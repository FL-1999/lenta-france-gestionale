"""Build the browser catalogue from the reviewed IT/FR interface catalogue."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
catalogue=json.loads((root/'static/i18n/fr.json').read_text(encoding='utf-8'))
(root/'static/js/ui-catalogue.js').write_text('// Generated from static/i18n/fr.json by scripts/build_ui_catalogue.py\n(()=>{const catalogue='+json.dumps(catalogue,ensure_ascii=False,separators=(',',':'))+';window.LentaText=text=>document.documentElement.lang===\'fr\'?(catalogue[text]??text):text;})();\n',encoding='utf-8')
