/* Monochrome icons for legacy UI labels. Only decorative glyphs in controls,
   headings and icon slots are replaced; stored text, inputs and paper are untouched. */
(() => {
  'use strict';
  const paths = {
    edit:'<path d="m15 4 5 5M4 20l4-1L20 7a2 2 0 0 0-4-4L4 15z"/>',
    trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    users:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v2"/>',
    calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18"/>',
    file:'<path d="M5 3h9l5 5v13H5zM14 3v6h5M9 13h6M9 17h6"/>',
    box:'<path d="m3 7 9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10"/>',
    truck:'<path d="M3 5h11v12H3zM14 9h4l3 4v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    back:'<path d="M20 12H4m6-6-6 6 6 6"/>',
    next:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
    site:'<path d="M3 20h18M5 20V8h9v12M14 12h5v8M8 11h3M8 15h3M5 8V4h9v4"/>',
    pin:'<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
    chart:'<path d="M4 3v17h17M8 15l4-5 4 2 5-7"/>',
    tools:'<path d="m14 5 4 4 3-3a7 7 0 0 1-9 9l-6 6-3-3 6-6a7 7 0 0 1 9-9z"/>',
    save:'<path d="M4 3h13l4 4v14H3V3zM7 3v6h9V3M7 21v-8h10v8"/>',
    print:'<path d="M6 9V3h12v6M6 17H3V9h18v8h-3M6 14h12v7H6z"/>',
    warning:'<path d="m12 3 10 18H2zM12 9v5M12 17v1"/>',
    home:'<path d="m3 10 9-7 9 7v10H3zM9 20v-7h6v7"/>',
    tag:'<path d="M3 3h8l10 10-8 8L3 11z"/><circle cx="7" cy="7" r="1"/>',
    download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    layers:'<path d="m3 7 9-4 9 4-9 4zM3 12l9 4 9-4M3 17l9 4 9-4"/>',
    lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>'
  };
  const groups = {
    edit:['✏','📝'], trash:['🗑'], plus:['➕'], users:['👥','👤','👷'],
    calendar:['📅','🗓'], file:['📄','📃','📋','🧾','📚','📁','📂'], box:['📦'],
    truck:['🚐','🚚','🚛','🚗'], check:['✅','✔'], clock:['🟡','⏱','⏰','🕒','⏳'],
    search:['🔎','🔍'], back:['⬅','◀','🔙'], next:['➡','▶'], site:['🏗'],
    pin:['📍','📌','🗺'], chart:['📈','📊'], tools:['🛠','🔧','⚙','🧰'],
    save:['💾'], print:['🖨'], warning:['⚠'], home:['🏠','🏡'], tag:['🏷'],
    download:['📥','⬇'], layers:['🪨'], lock:['🔐','🔒']
  };
  const names = new Map(Object.entries(groups).flatMap(([name, glyphs]) => glyphs.map(glyph => [glyph,name])));
  const pattern = new RegExp(`(${[...names.keys()].join('|')})[\\uFE0E\\uFE0F]?`, 'gu');
  const selector = 'h1,h2,h3,h4,.card-title,.btn,.kpi-icon,.card-icon,.shortcut-icon,.module-card-icon,.page-icon,.workspace-current-page';
  document.querySelectorAll(selector).forEach(label => {
    if (label.closest('#technical-sheet-export,script,style,textarea,select')) return;
    const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) if (!walker.currentNode.parentElement.closest('svg')) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      const text = node.textContent;
      const matches = [...text.matchAll(pattern)];
      if (!matches.length) return;
      // Icon-only controls keep an accessible name from their original label.
      if (label.matches('button,a,summary') && !label.textContent.replace(pattern,'').trim() && !label.hasAttribute('aria-label')) return;
      const fragment = document.createDocumentFragment();
      let start = 0;
      matches.forEach(match => {
        fragment.append(document.createTextNode(text.slice(start,match.index)));
        const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
        Object.entries({class:'workspace-icon',width:'18',height:'18',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}).forEach(([key,value]) => svg.setAttribute(key,value));
        svg.innerHTML = paths[names.get(match[1])]; // Only constant, trusted SVG paths.
        fragment.append(svg);
        start = match.index + match[0].length;
      });
      fragment.append(document.createTextNode(text.slice(start)));
      node.replaceWith(fragment);
    });
  });
})();
