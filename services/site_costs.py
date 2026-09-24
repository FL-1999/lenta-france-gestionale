"""Cost register: quantities originate in operations; money is reconciled separately."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy.orm import object_session
from models import (Site, Fiche, SitePour, MagazzinoMovimento, MagazzinoMovimentoTipoEnum,
                    PurchaseDelivery, Supplier, SiteEconomicEntry, SiteEconomicEntryTypeEnum,
                    SiteEconomicCategoryEnum, CostContract, CostDelivery, CostDeliveryLine,
                    CostInvoice, CostSharedExpense, CostAllocation)
from audit_utils import log_audit_event


def fail(it, fr, code=400):
    raise HTTPException(code, {'it': it, 'fr': fr})


def number(value, places=3, positive=False, optional=False):
    if optional and (value is None or value == ''):
        return None
    try:
        n = Decimal(str(value).replace(',', '.'))
        if not n.is_finite() or n < 0 or n > Decimal('1000000000') or (positive and n == 0):
            raise ValueError()
        n = n.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
        if positive and n == 0:
            raise ValueError()
        return n
    except (InvalidOperation, ValueError, TypeError):
        fail('Inserisci quantità e importi validi, non negativi.', 'Saisissez des quantités et montants valides, non négatifs.')


def text(value, limit=255, required=False):
    s = str(value or '').strip()
    if len(s) > limit or (required and not s):
        fail('Compila il testo richiesto senza superare la lunghezza consentita.', 'Complétez le texte demandé sans dépasser la longueur autorisée.')
    return s


def day(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        fail('Inserisci una data valida.', 'Saisissez une date valide.')


def supplier(db, sid, required=True):
    if not sid and not required:
        return None
    row = db.get(Supplier, sid) if isinstance(sid, int) else None
    if not row:
        fail('Seleziona un fornitore esistente.', 'Sélectionnez un fournisseur existant.')
    return row.id


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def sources(db, site):
    """Read-only proposals, never synthetic tickets presented as actual deliveries."""
    result = []
    members = set()
    for group in db.query(SitePour).filter_by(site_id=site.id).all():
        fs = sorted({m.fiche_id for m in group.members if m.fiche_id})
        members.update(fs)
        if group.total_m3 and group.cast_date and fs:
            result.append(dict(key=f'pour:{group.id}', label=group.label, kind='concrete',
                date=group.cast_date.isoformat(), quantity=float(group.total_m3), unit='m³', fiche_ids=fs,
                revision=group.revision, fiche_state=[(f.id, f.metri_cubi_gettati, str(f.data_getto), str(f.updated_at))
                    for f in db.query(Fiche).filter(Fiche.id.in_(fs)).order_by(Fiche.id)], supplier_id=None, price=None))
    for f in db.query(Fiche).filter_by(site_id=site.id).order_by(Fiche.id):
        if f.id in members or not f.metri_cubi_gettati or f.metri_cubi_gettati <= 0 or not f.data_getto:
            continue
        result.append(dict(key=f'fiche:{f.id}', label=f.panel_label, kind='concrete', date=f.data_getto.isoformat(),
            quantity=float(f.metri_cubi_gettati), unit='m³', fiche_ids=[f.id], revision=str(f.updated_at),
            supplier_id=None, price=None))
    direct_ids = set()
    for delivery in db.query(PurchaseDelivery).filter_by(confirmed=True, delivery_site_id=site.id).all():
        direct_ids.add(delivery.id)
        for line in delivery.lines:
            if not line.qty_delivered or line.qty_delivered <= 0:
                continue
            item = line.order_line.magazzino_item if line.order_line else None
            result.append(dict(key=f'purchase:{line.id}', label=line.order_line.description or 'Materiale',
                kind='direct', date=(delivery.delivery_date or delivery.created_at.date()).isoformat(), quantity=float(line.qty_delivered),
                unit=item.unita_misura if item else 'pz', fiche_ids=[], supplier_id=delivery.order.supplier_id,
                price=item.costo_unitario if item else None, ticket=delivery.delivery_number))
    for m in db.query(MagazzinoMovimento).filter_by(cantiere_id=site.id, tipo=MagazzinoMovimentoTipoEnum.scarico).order_by(MagazzinoMovimento.id):
        if m.purchase_delivery_id in direct_ids or not m.item:
            continue
        result.append(dict(key=f'movement:{m.id}', label=m.item.nome, kind='warehouse',
            date=m.created_at.date().isoformat(), quantity=float(m.quantita), unit=m.item.unita_misura,
            fiche_ids=[], supplier_id=None, price=m.item.costo_unitario, ticket=f'MAG-{m.id}'))
    for row in result:
        row['fingerprint'] = fingerprint(row)
    return result


def split_loads(total, capacity):
    total, capacity = number(total, positive=True), number(capacity, positive=True)
    if total / capacity > 500:
        fail('Troppi viaggi: controlla la capacità.', 'Trop de voyages : vérifiez la capacité.')
    rows = []
    while total > 0:
        qty = min(total, capacity)
        rows.append(float(qty)); total -= qty
    return rows


def line_amount(line):
    if line.invoice_id:
        return (line.invoice_quantity * line.invoice_unit_price + line.invoice_extra).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    if line.unit_price is None:
        return None
    return (line.quantity * line.unit_price + line.extra).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def refresh_entry(db, delivery, user):
    amounts = [line_amount(l) for l in delivery.lines]
    if not delivery.site_id:
        return
    entry = delivery.economic_entry
    if not entry:
        entry = SiteEconomicEntry(site_id=delivery.site_id, entry_type=SiteEconomicEntryTypeEnum.cost,
            category=SiteEconomicCategoryEnum.materiali, created_by_id=user.id)
        db.add(entry); delivery.economic_entry = entry
    entry.amount = float(sum((a for a in amounts if a is not None), Decimal(0)))
    entry.entry_date = delivery.delivery_date
    entry.description = f'Registro consegne · {delivery.label}'
    entry.notes = 'Costi parziali: prezzi mancanti' if any(a is None for a in amounts) else 'Gestito da Costi e consegne'
    entry.updated_by_id = user.id


def covered_fiches(site):
    db = object_session(site)
    if not db:
        return set()
    return {fid for d in db.query(CostDelivery).filter_by(site_id=site.id) for fid in d.source_snapshot.get('fiche_ids', [])}


def serialize_delivery(d, live=None):
    lines = []
    for l in d.lines:
        amount = line_amount(l)
        lines.append(dict(id=l.id, ticket=l.ticket, quantity=float(l.quantity), unit=l.unit,
            unit_price=float(l.unit_price) if l.unit_price is not None else None, extra=float(l.extra),
            invoice_id=l.invoice_id, amount=float(amount) if amount is not None else None))
    return dict(id=d.id, key=d.source_key, label=d.label, date=d.delivery_date.isoformat(), site_id=d.site_id,
        site_name=d.site_name, supplier_id=d.supplier_id, revision=d.revision, lines=lines,
        source=d.source_snapshot, contract=d.contract, reason=d.reason,
        drift=live is None or live['fingerprint'] != d.source_snapshot.get('fingerprint'), live=live)


def save_contract(db, site, data, user):
    row = db.query(CostContract).filter_by(site_id=site.id, id=data.get('id')).with_for_update().first() if data.get('id') else None
    if data.get('id') and (not row or row.revision != data.get('revision')):
        fail('Contratto cambiato: ricarica la pagina.', 'Contrat modifié : actualisez la page.', 409)
    sid = supplier(db, data.get('supplier_id'))
    payload = dict(name=text(data.get('name'), required=True), price=float(number(data.get('price'), 4)),
        capacity=float(number(data.get('capacity'), positive=True)), surcharge=data.get('surcharge'),
        rate=float(number(data.get('rate', 0), 2)), planned=float(number(data.get('planned', 0))))
    if payload['surcharge'] not in ('none', 'fixed', 'missing'):
        fail('Scegli il tipo di supplemento.', 'Choisissez le type de supplément.')
    if not row:
        row = CostContract(site_id=site.id, supplier_id=sid, payload=payload); db.add(row)
    else:
        row.supplier_id=sid; row.payload=payload; row.revision += 1
    db.flush()
    log_audit_event(db,user,'COST_CONTRACT_SAVED','cost_contract',row.id,payload)
    return row


def save_delivery(db, site, data, user):
    key = text(data.get('key'), 100, True)
    existing = db.query(CostDelivery).filter_by(source_key=key).with_for_update().first()
    if existing and existing.site_id != site.id:
        fail('Consegna non disponibile.', 'Livraison indisponible.', 404)
    if (existing.revision if existing else 0) != data.get('revision', 0):
        fail('Registro aggiornato da un altro utente. Ricarica prima di salvare.', 'Registre modifié par un autre utilisateur. Actualisez avant de sauvegarder.', 409)
    if existing and any(l.invoice_id for l in existing.lines):
        fail('Annulla prima la verifica della fattura collegata per correggere il buono.', 'Annulez d’abord le rapprochement de la facture liée pour corriger le bon.', 409)
    # Fiche writes do not all take the site lock. Lock their actual rows before
    # reading the source fingerprint so a concurrent saved edit is not overwritten.
    db.query(Fiche).filter_by(site_id=site.id).order_by(Fiche.id).populate_existing().with_for_update().all()
    db.query(SitePour).filter_by(site_id=site.id).order_by(SitePour.id).populate_existing().with_for_update().all()
    live = next((s for s in sources(db, site) if s['key'] == key), None)
    if not live:
        fail('La fiche o il movimento di origine non è più disponibile.', 'La fiche ou le mouvement d’origine n’est plus disponible.', 409)
    if live['fingerprint'] != data.get('fingerprint'):
        fail('La quantità di origine è cambiata. Ricarica e ricontrolla i buoni.', 'La quantité d’origine a changé. Actualisez et revérifiez les bons.', 409)
    sid = supplier(db, data.get('supplier_id'), required=live['kind'] != 'warehouse')
    if live.get('supplier_id') and live['supplier_id'] != sid:
        fail('Il fornitore deve coincidere con quello del buono.', 'Le fournisseur doit correspondre à celui du bon.')
    raw_lines=data.get('lines')
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 500:
        fail('Inserisci almeno una consegna.', 'Saisissez au moins une livraison.')
    lines=[]; tickets=set()
    for item in raw_lines:
        if not isinstance(item,dict):
            fail('Riga consegna non valida.', 'Ligne de livraison invalide.')
        ticket=text(item.get('ticket'),150)
        if ticket and ticket.casefold() in tickets and live['kind']=='concrete':
            fail('Uno stesso buono compare due volte nel getto.', 'Un même bon apparaît deux fois dans le bétonnage.')
        if ticket: tickets.add(ticket.casefold())
        lines.append(CostDeliveryLine(ticket=ticket, quantity=number(item.get('quantity'),positive=True),
            unit=text(live['unit'] or 'pz',30,True), unit_price=number(item.get('unit_price'),4,optional=True),
            extra=number(item.get('extra',0),2)))
    total=sum((l.quantity for l in lines),Decimal(0))
    delta=total-number(live['quantity'])
    reason=text(data.get('reason'),2000)
    if live['kind']!='concrete' and delta:
        fail('Correggi prima la quantità nel movimento di magazzino o nel buono di acquisto.', 'Corrigez d’abord la quantité dans le mouvement de stock ou le bon d’achat.')
    if delta:
        choice=data.get('fiche_choice')
        if choice not in ('update','keep'):
            fail('Il totale differisce dalla fiche: scegli se aggiornarla oppure mantenerla.', 'Le total diffère de la fiche : choisissez de la corriger ou de la conserver.')
        if choice=='keep' and not reason:
            fail('Indica il motivo per mantenere il volume della fiche.', 'Indiquez pourquoi vous conservez le volume de la fiche.')
        if choice=='update':
            fiches=db.query(Fiche).filter(Fiche.id.in_(live['fiche_ids'])).order_by(Fiche.id).with_for_update().all()
            if any(f.courbe_beton_active or f.courbe_beton_volume_total is not None for f in fiches):
                fail('La fiche ha una curva di getto: correggi prima la curva, oppure mantieni la fiche.', 'La fiche possède une courbe de bétonnage : corrigez la courbe ou conservez la fiche.')
            if key.startswith('pour:'):
                group=db.query(SitePour).filter_by(id=int(key.split(':')[1])).with_for_update().one()
                if group.kind=='joint':
                    from services.site_pours import record_joint
                    record_joint(db,group,float(total),day(live['date']))
                else:
                    fiches[0].metri_cubi_gettati=float(total); group.total_m3=float(total); group.revision+=1
            else:
                fiches[0].metri_cubi_gettati=float(total)
            db.flush()
            live=next(s for s in sources(db,site) if s['key']==key)
    if not existing:
        existing=CostDelivery(source_key=key,site_id=site.id,site_name=site.name,source_snapshot=live,
            label=live['label'],delivery_date=day(live['date']),supplier_id=sid)
        db.add(existing)
    else:
        # Flush deletions before inserting replacements; invoiced rows are locked above.
        existing.lines.clear(); db.flush(); existing.revision+=1
    contract={}
    if data.get('contract_id'):
        c=db.query(CostContract).filter_by(site_id=site.id,id=data['contract_id']).first()
        if not c or c.supplier_id!=sid:
            fail('Il contratto non corrisponde al fornitore.', 'Le contrat ne correspond pas au fournisseur.')
        if c.revision!=data.get('contract_revision'):
            fail('Il contratto è cambiato. Ricarica i prezzi.', 'Le contrat a changé. Actualisez les prix.',409)
        contract=dict(c.payload,id=c.id,revision=c.revision)
    elif existing.contract:
        contract=existing.contract
    existing.lines=lines; existing.source_snapshot=live; existing.reason=reason; existing.supplier_id=sid
    existing.delivery_date=day(live['date']); existing.contract=contract
    refresh_entry(db,existing,user); db.flush()
    log_audit_event(db,user,'COST_DELIVERY_VERIFIED','cost_delivery',existing.id,
        {'total':str(total),'delta':str(delta),'fiche_choice':data.get('fiche_choice'),'reason':reason,
         'source':live,'lines':[dict(ticket=l.ticket,quantity=str(l.quantity),price=str(l.unit_price),extra=str(l.extra)) for l in lines]})
    return existing


def save_invoice(db,data,user):
    sid=supplier(db,data.get('supplier_id'))
    # Serialize invoice reconciliation per supplier, including concurrent requests.
    db.query(Supplier).filter_by(id=sid).with_for_update().one()
    invoice_number=text(data.get('number'),150,True)
    previous=db.query(CostInvoice).filter_by(supplier_id=sid,number=invoice_number).populate_existing().first()
    if previous and previous.status!='cancelled':
        fail('Numero fattura già registrato. Consulta la fattura esistente.', 'Numéro de facture déjà enregistré. Consultez la facture existante.',409)
    total=number(data.get('total'),2,positive=True)
    items=data.get('lines')
    if not isinstance(items,list) or not items or len(items)>1000:
        fail('Seleziona i buoni da abbinare.', 'Sélectionnez les bons à rapprocher.')
    if not all(isinstance(i,dict) for i in items):
        fail('Selezione di buoni non valida.', 'Sélection de bons invalide.')
    ids=[i.get('id') for i in items]
    if len(set(ids))!=len(ids) or not all(isinstance(i,int) for i in ids):
        fail('Selezione di buoni non valida.', 'Sélection de bons invalide.')
    # Same lock order as register updates: site, delivery, line.
    deliveries=db.query(CostDelivery).join(CostDeliveryLine).filter(CostDeliveryLine.id.in_(ids)).order_by(CostDelivery.id).all()
    for site_id in sorted({d.site_id for d in deliveries if d.site_id}):
        db.query(Site).filter_by(id=site_id).with_for_update().one()
    for d in deliveries:
        db.query(CostDelivery).filter_by(id=d.id).populate_existing().with_for_update().one()
    lines={l.id:l for l in db.query(CostDeliveryLine).filter(CostDeliveryLine.id.in_(ids)).populate_existing().with_for_update()}
    computed=Decimal(0)
    for item in items:
        l=lines.get(item['id'])
        if not l or l.invoice_id or not l.ticket or l.delivery.supplier_id!=sid or not l.delivery.site_id:
            fail('Un buono è già fatturato, senza numero o di un altro fornitore.', 'Un bon est déjà facturé, sans numéro ou lié à un autre fournisseur.',409)
        if l.delivery.source_snapshot.get('kind')=='warehouse':
            fail('Gli scarichi di magazzino sono costi interni, non nuovi acquisti da fatturare.', 'Les sorties de stock sont des coûts internes, pas de nouveaux achats à facturer.')
        if l.delivery.revision!=item.get('revision'):
            fail('Un buono è cambiato: ricarica la selezione.', 'Un bon a changé : actualisez la sélection.',409)
        qty=number(item.get('quantity'),positive=True); price=number(item.get('unit_price'),4); extra=number(item.get('extra',0),2)
        reason=text(item.get('reason'),2000)
        if qty!=l.quantity and not reason:
            fail('Spiega la differenza tra quantità fatturata e consegnata.', 'Expliquez l’écart entre quantité facturée et livrée.')
        l.invoice_quantity=qty; l.invoice_unit_price=price; l.invoice_extra=extra; l.invoice_reason=reason
        computed+=(qty*price+extra).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    if computed!=total:
        fail(f'La somma dei buoni ({computed} €) non coincide con il totale netto della fattura ({total} €).',
             f'La somme des bons ({computed} €) ne correspond pas au total HT de la facture ({total} €).')
    invoice=previous or CostInvoice(supplier_id=sid,number=invoice_number,invoice_date=day(data.get('date')),total=total)
    if previous:
        invoice.invoice_date=day(data.get('date')); invoice.total=total; invoice.status='confirmed'; invoice.revision+=1
    db.add(invoice); db.flush()
    for l in lines.values(): l.invoice_id=invoice.id
    for d in deliveries: d.revision+=1; refresh_entry(db,d,user)
    log_audit_event(db,user,'COST_INVOICE_RECONCILED','cost_invoice',invoice.id,{'number':invoice_number,'date':str(invoice.invoice_date),'total':str(total),'lines':items})
    return invoice


def cancel_invoice(db,invoice,data,user):
    if invoice.revision!=data.get('revision') or invoice.status!='confirmed':
        fail('La fattura è già cambiata.', 'La facture a déjà changé.',409)
    reason=text(data.get('reason'),2000,True)
    lines=db.query(CostDeliveryLine).filter_by(invoice_id=invoice.id).all()
    before=[{'id':l.id,'quantity':str(l.invoice_quantity),'price':str(l.invoice_unit_price),'extra':str(l.invoice_extra)} for l in lines]
    for sid in sorted({l.delivery.site_id for l in lines if l.delivery.site_id}):
        db.query(Site).filter_by(id=sid).with_for_update().one()
    for l in lines:
        l.invoice_id=None; l.invoice_quantity=None; l.invoice_unit_price=None; l.invoice_extra=None; l.invoice_reason=None
    for d in {l.delivery for l in lines}: d.revision+=1; refresh_entry(db,d,user)
    invoice.status='cancelled'; invoice.revision+=1
    # Keep original number/audit, allow a corrected revision under a new explicit reference.
    log_audit_event(db,user,'COST_INVOICE_CANCELLED','cost_invoice',invoice.id,{'reason':reason,'lines':before})


def save_shared(db,data,user):
    row=db.query(CostSharedExpense).filter_by(id=data.get('id')).with_for_update().first() if data.get('id') else None
    if data.get('id') and (not row or row.revision!=data.get('revision')):
        fail('La spesa è cambiata. Ricarica la pagina.', 'La dépense a changé. Actualisez la page.',409)
    request_key=text(data.get('request_key'),64,True) if not row else row.request_key
    if not row and db.query(CostSharedExpense).filter_by(request_key=request_key).first():
        fail('Questa spesa è già stata salvata. Ricarica il registro.', 'Cette dépense a déjà été enregistrée. Actualisez le registre.',409)
    total=number(data.get('total'),2,positive=True)
    allocations=data.get('allocations',[])
    if not isinstance(allocations,list) or len(allocations)>200 or not all(isinstance(a,dict) for a in allocations):
        fail('Ripartizione non valida.', 'Répartition invalide.')
    if len({a.get('site_id') for a in allocations})!=len(allocations):
        fail('Seleziona ogni cantiere una sola volta.', 'Sélectionnez chaque chantier une seule fois.')
    amounts=[number(a.get('amount'),2) for a in allocations]
    if sum(amounts,Decimal(0))>total:
        fail('La ripartizione supera il totale.', 'La répartition dépasse le total.')
    label=text(data.get('description'),255,True); when=day(data.get('date'))
    if not row:
        row=CostSharedExpense(request_key=request_key,description=label,expense_date=when,total=total); db.add(row)
    else:
        for a in row.allocations:
            if a.economic_entry: db.delete(a.economic_entry)
        row.allocations.clear(); db.flush(); row.revision+=1
    row.description=label; row.expense_date=when; row.total=total
    for a,amount in zip(allocations,amounts):
        site=db.get(Site,a.get('site_id'))
        if not site: fail('Cantiere non disponibile.', 'Chantier indisponible.')
        entry=SiteEconomicEntry(site_id=site.id,entry_date=when,entry_type=SiteEconomicEntryTypeEnum.cost,
            category=SiteEconomicCategoryEnum.altri_costi,amount=float(amount),description=label,
            notes='Ripartizione spesa comune',created_by_id=user.id,updated_by_id=user.id)
        row.allocations.append(CostAllocation(site_id=site.id,site_name=site.name,amount=amount,economic_entry=entry))
    db.flush()
    log_audit_event(db,user,'COST_SHARED_SAVED','cost_shared_expense',row.id,data)
    return row


def unverify_delivery(db,site,data,user):
    row=db.query(CostDelivery).filter_by(id=data.get('id'),site_id=site.id).with_for_update().first()
    if not row or row.revision!=data.get('revision'):
        fail('Il registro è già cambiato.', 'Le registre a déjà changé.',409)
    if any(l.invoice_id for l in row.lines):
        fail('Annulla prima la verifica della fattura.', 'Annulez d’abord le rapprochement de la facture.',409)
    reason=text(data.get('reason'),2000,True)
    log_audit_event(db,user,'COST_DELIVERY_UNVERIFIED','cost_delivery',row.id,
        {'reason':reason,'before':serialize_delivery(row),'fiche_unchanged':True})
    entry=row.economic_entry
    db.delete(row)
    if entry: db.delete(entry)
    db.flush()
    return row
