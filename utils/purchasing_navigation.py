"""Presentation-only location metadata for the purchasing workspace."""
import re
from permissions import has_perm


def purchasing_navigation(request, user, context):
    if not user or not (has_perm(user, 'manager.access') or has_perm(user, 'inventory.read')):
        return None
    path = request.url.path.rstrip('/')
    roots = {
        'items': ('/manager/magazzino', 'Articoli', 'Articles'),
        'orders': ('/manager/ordini', 'Ordini', 'Commandes'),
        'suppliers': ('/manager/fornitori', 'Fornitori', 'Fournisseurs'),
        'movements': ('/manager/magazzino/movimenti', 'Movimenti', 'Mouvements'),
        'requests': ('/manager/magazzino/richieste', 'Richieste', 'Demandes'),
        'categories': ('/manager/magazzino/categorie', 'Categorie', 'Catégories'),
        'macros': ('/manager/magazzino/macros', 'Macro categorie', 'Macro catégories'),
        'archived': ('/manager/magazzino/archiviati', 'Articoli archiviati', 'Articles archivés'),
        'low_stock': ('/manager/magazzino/sotto-soglia', 'Sotto soglia', 'Sous seuil'),
    }
    if path == '/manager/ordini' or path.startswith('/manager/ordini/'):
        section = 'orders'
    elif path == '/manager/fornitori' or path.startswith('/manager/fornitori/'):
        section = 'suppliers'
    elif path == '/manager/magazzino' or path.startswith('/manager/magazzino/'):
        suffix = path.removeprefix('/manager/magazzino').strip('/').split('/')[0]
        section = {'movimenti':'movements','report-consumi':'movements','richieste':'requests',
                   'categorie':'categories','macro':'macros','macros':'macros',
                   'archiviati':'archived','sotto-soglia':'low_stock'}.get(suffix, 'items')
    else:
        return None
    root, it, fr = roots[section]
    label = fr if request.cookies.get('lang') == 'fr' else it
    lists = {value[0] for value in roots.values()} | {'/manager/ordini/chiusi', '/manager/magazzino/items', '/manager/magazzino/dashboard'}
    is_list = path in lists
    parent = root
    parent_label = label
    # Forms return to their record by default, even when opened in a fresh tab.
    order_match = re.fullmatch(r'/manager/ordini/(\d+)/.+', path)
    item_match = re.fullmatch(r'/manager/magazzino/(?:items/)?(\d+)/(?:modifica|duplica|rettifica|classificazione|elimina)', path)
    if order_match:
        parent = '/manager/ordini/' + order_match[1]
        order = context.get('order')
        parent_label = ('Commande' if request.cookies.get('lang') == 'fr' else 'Ordine') + ' ' + str(getattr(order, 'order_number', order_match[1]))
    elif item_match:
        parent = '/manager/magazzino/items/' + item_match[1] + '/scheda'
        parent_label = getattr(context.get('item'), 'nome', label)
    return {'section':section, 'root':root, 'label':label, 'is_list':is_list, 'parent':parent, 'parent_label':parent_label}
