from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator
from typing import Literal
from models import (Supplier, SupplierService, ServiceRecord, Site, Machine, Veicolo,
                    SiteEconomicEntry, SiteEconomicEntryTypeEnum, SiteEconomicCategoryEnum)
from audit_utils import log_audit_event


class Offering(BaseModel):
    supplier_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)
    kind: Literal['service', 'rental'] = 'service'
    category: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=30)
    price: Decimal = Field(ge=0, le=1000000, max_digits=12, decimal_places=4)


class Record(Offering):
    date: date
    quantity: Decimal = Field(gt=0, le=1000000, max_digits=12, decimal_places=3)
    status: Literal['planned', 'executed', 'cancelled'] = 'planned'
    site_id: int | None = Field(default=None, gt=0)
    vehicle_id: int | None = Field(default=None, gt=0)
    machine_id: int | None = Field(default=None, gt=0)
    catalogue_id: int | None = Field(default=None, gt=0)
    start: date | None = None
    end: date | None = None
    reference: str = Field(default='', max_length=150)
    notes: str = Field(default='', max_length=2000)
    maintenance: bool = False
    meter: Decimal | None = Field(default=None, ge=0, le=100000000, decimal_places=1)
    next_date: date | None = None
    next_meter: Decimal | None = Field(default=None, ge=0, le=100000000, decimal_places=1)
    reason: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def coherent(self):
        if self.machine_id and self.vehicle_id:
            raise ValueError('Seleziona un solo mezzo / Sélectionnez un seul équipement')
        if self.maintenance and (not (self.vehicle_id or self.machine_id) or self.kind != 'service'):
            raise ValueError('La manutenzione richiede un mezzo / La maintenance nécessite un équipement')
        if self.kind == 'rental' and (not self.start or not self.end or self.end < self.start):
            raise ValueError('Controlla inizio e fine noleggio / Vérifiez les dates de location')
        if self.status == 'cancelled' and not self.reason.strip():
            raise ValueError('Indica il motivo di annullamento / Indiquez le motif d’annulation')
        if self.status == 'executed' and self.date > date.today():
            raise ValueError('Una prestazione futura resta prevista / Une prestation future reste prévue')
        if self.next_date and self.next_date < self.date:
            raise ValueError('Controlla la prossima scadenza / Vérifiez la prochaine échéance')
        if self.meter is not None and self.next_meter is not None and self.next_meter < self.meter:
            raise ValueError('La prossima lettura deve essere successiva / Le prochain compteur doit être supérieur')
        if self.quantity * self.price > Decimal('1000000000'):
            raise ValueError('Importo troppo elevato / Montant trop élevé')
        return self


def parse(model, data):
    try:
        value = model.model_validate(data)
        if not value.title.strip() or not value.category.strip() or not value.unit.strip():
            raise ValueError('Compila descrizione, categoria e unità / Complétez la description, la catégorie et l’unité')
        return value
    except ValidationError as exc:
        raise HTTPException(400, [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()])
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def related(db, model, id):
    if id is None:
        return None
    obj = db.query(model).filter_by(id=id).with_for_update().first()
    if not obj:
        raise HTTPException(400, 'Collegamento non trovato / Association introuvable')
    return obj


def row_for_edit(db, model, data):
    id = data.get('id')
    if id is None:
        return None
    if not isinstance(id, int):
        raise HTTPException(400, 'ID non valido / Identifiant invalide')
    row = db.query(model).filter_by(id=id).with_for_update().first()
    if not row:
        raise HTTPException(404)
    if data.get('revision') != row.revision:
        raise HTTPException(409, 'Dati modificati da un altro utente. Ricarica. / Données modifiées par un autre utilisateur. Actualisez.')
    return row


def save_offering(db, data, user):
    value = parse(Offering, data)
    supplier = related(db, Supplier, value.supplier_id)
    if not supplier.is_active:
        raise HTTPException(400, 'Fornitore disattivato / Fournisseur désactivé')
    row = row_for_edit(db, SupplierService, data)
    before = row.payload if row else None
    if row:
        row.revision += 1
    else:
        row = SupplierService(); db.add(row)
    row.supplier_id = value.supplier_id
    row.payload = value.model_dump(mode='json')
    row.active = data.get('active', True) is True
    db.flush()
    log_audit_event(db, user, 'SUPPLIER_SERVICE_SAVED', 'supplier_service', row.id, {'before': before, 'after': row.payload, 'active': row.active})
    return row


def save_record(db, data, user):
    value = parse(Record, data)
    # Lock references first: supplier deletion and simultaneous edits cannot race this write.
    supplier = related(db, Supplier, value.supplier_id)
    site = related(db, Site, value.site_id)
    vehicle = related(db, Veicolo, value.vehicle_id)
    machine = related(db, Machine, value.machine_id)
    row = row_for_edit(db, ServiceRecord, data)
    if not supplier.is_active and (not row or row.supplier_id != supplier.id):
        raise HTTPException(400, 'Fornitore disattivato / Fournisseur désactivé')
    if value.catalogue_id:
        offering = related(db, SupplierService, value.catalogue_id)
        if offering.supplier_id != supplier.id:
            raise HTTPException(400, 'Catalogo di un altro fornitore / Catalogue d’un autre fournisseur')
    before = row.payload if row else None
    if row:
        row.revision += 1
    else:
        key = data.get('request_key')
        if not isinstance(key, str) or not 8 <= len(key) <= 64:
            raise HTTPException(400, 'Ricarica il modulo / Rechargez le formulaire')
        if db.query(ServiceRecord.id).filter_by(request_key=key).first():
            raise HTTPException(409, 'Registrazione già salvata / Enregistrement déjà sauvegardé')
        row = ServiceRecord(request_key=key); db.add(row)
    payload = value.model_dump(mode='json')
    payload.update(supplier_name=supplier.name, site_name=site.name if site else '',
                   asset_label=f'{vehicle.marca} {vehicle.modello} · {vehicle.targa}' if vehicle else machine.name if machine else '')
    row.supplier_id, row.catalogue_id = supplier.id, value.catalogue_id
    row.site_id, row.vehicle_id, row.machine_id = value.site_id, value.vehicle_id, value.machine_id
    row.service_date, row.status = value.date, value.status
    row.amount = (value.quantity * value.price).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    row.payload = payload
    entry = row.economic_entry
    if site and value.status == 'executed':
        if not entry:
            entry = SiteEconomicEntry(created_by_id=user.id, entry_type=SiteEconomicEntryTypeEnum.cost)
            db.add(entry); row.economic_entry = entry
        entry.site_id, entry.entry_date = site.id, value.date
        entry.category = SiteEconomicCategoryEnum.mezzi if (vehicle or machine) else SiteEconomicCategoryEnum.altri_costi
        entry.amount, entry.description = float(row.amount), value.title
        entry.notes, entry.updated_by_id = 'Servizi e noleggi · '+value.reference, user.id
    elif entry:
        row.economic_entry = None
        db.delete(entry)
    db.flush()
    log_audit_event(db, user, 'SERVICE_RECORD_SAVED', 'service_record', row.id, {'before': before, 'after': payload})
    return row


def history(db, *, vehicle_id=None, machine_id=None):
    q = db.query(ServiceRecord).filter(ServiceRecord.status == 'executed')
    q = q.filter_by(vehicle_id=vehicle_id) if vehicle_id else q.filter_by(machine_id=machine_id)
    return [r for r in q.order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc()) if r.payload.get('maintenance')]
