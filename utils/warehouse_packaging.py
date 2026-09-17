"""One stock balance, expressed in the article's immutable base unit."""
from decimal import Decimal, InvalidOperation
import math

ARTICLE_UNITS = {'pz', 'kg', 'm', 'm2', 'm3', 'l', 'sacco', 'bancale'}
PACKAGING_UNITS = ('bancale', 'sacco', 'kg')


def number(value):
    try:
        result = Decimal(str(value).strip().replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Inserisci una quantità valida / Saisissez une quantité valide.')
    if not result.is_finite() or abs(result) > Decimal('1e12'):
        raise ValueError('Quantità fuori limite / Quantité hors limite.')
    return result


def validate_packaging(enabled, base, bags, weight):
    if not enabled:
        return None, None
    if base not in PACKAGING_UNITS:
        raise ValueError('Per le confezioni scegli kg, sacco o bancale / Choisissez kg, sacco ou bancale.')
    bags, weight = number(bags), number(weight)
    if bags <= 0 or bags != bags.to_integral_value() or weight < Decimal('0.001'):
        raise ValueError('Inserisci un numero intero di sacchi e almeno 0,001 kg per sacco / Nombre entier de sacs et au moins 0,001 kg par sac requis.')
    if bags > 1000000 or weight > 1000000:
        raise ValueError('Formato confezione fuori limite / Conditionnement hors limite.')
    return int(bags), float(weight)


def convert_quantity(value, source, base, bags=None, weight=None):
    value = number(value)
    source = source or base
    if value < 0:
        raise ValueError('La quantità non può essere negativa / La quantité ne peut pas être négative.')
    if source != base:
        if not bags or not weight or source not in PACKAGING_UNITS or base not in PACKAGING_UNITS:
            raise ValueError('Unità non compatibile con questo articolo / Unité incompatible avec cet article.')
        kg = {'kg': Decimal(1), 'sacco': number(weight), 'bancale': number(bags) * number(weight)}
        value = value * kg[source] / kg[base]
    result = float(value)
    if not math.isfinite(result) or result > 1e12 or (value > 0 and result == 0):
        raise ValueError('Quantità convertita fuori limite / Quantité convertie hors limite.')
    return result


def equivalents(item):
    if not item.sacchi_per_bancale or not item.kg_per_sacco or item.unita_misura not in PACKAGING_UNITS:
        return {}
    kg = {'kg': Decimal(1), 'sacco': Decimal(str(item.kg_per_sacco)),
          'bancale': Decimal(str(item.sacchi_per_bancale)) * Decimal(str(item.kg_per_sacco))}
    total = Decimal(str(item.quantita_disponibile or 0)) * kg[item.unita_misura]
    return {unit: float(total / kg[unit]) for unit in PACKAGING_UNITS}


def movement_quantity(item, quantity, unit, note):
    converted = convert_quantity(quantity, unit, item.unita_misura, item.sacchi_per_bancale, item.kg_per_sacco)
    if converted <= 0:
        raise ValueError('Inserisci una quantità positiva / Saisissez une quantité positive.')
    if unit and unit != item.unita_misura:
        note = f'{quantity} {unit} = {converted:g} {item.unita_misura}. {(note or "").strip()}'
    return converted, note
