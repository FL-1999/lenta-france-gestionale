"""One stock balance, expressed in the article's immutable base unit."""
from decimal import Decimal, InvalidOperation
import math

ARTICLE_UNITS = {'pz', 'unita', 'kg', 'm', 'm2', 'm3', 'l', 'sacco', 'bancale', 'rotolo'}
PACKAGING_UNITS = ('bancale', 'sacco', 'kg')
ROLL_UNITS = ('bancale', 'rotolo', 'm')


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


def validate_article_packaging(enabled, base, kind, bags, weight, rolls, length):
    if not enabled:
        return None, None, None, None
    if kind == 'sacchi':
        bags, weight = validate_packaging(True, base, bags, weight)
        return bags, weight, None, None
    if kind != 'rotoli' or base not in ROLL_UNITS:
        raise ValueError('Per i rotoli scegli m, rotolo o bancale / Pour les rouleaux choisissez m, rotolo ou bancale.')
    rolls, length = number(rolls), number(length)
    if rolls <= 0 or rolls != rolls.to_integral_value() or length < Decimal('0.001'):
        raise ValueError('Inserisci un numero intero di rotoli e almeno 0,001 m per rotolo / Nombre entier de rouleaux et au moins 0,001 m par rouleau requis.')
    if rolls > 1000000 or length > 1000000:
        raise ValueError('Formato confezione fuori limite / Conditionnement hors limite.')
    return None, None, int(rolls), float(length)


def factors(bags=None, weight=None, rolls=None, length=None):
    if rolls and length:
        return {'bancale': Decimal(str(rolls)) * Decimal(str(length)),
                'rotolo': Decimal(str(length)), 'm': Decimal(1)}
    if bags and weight:
        return {'bancale': Decimal(str(bags)) * Decimal(str(weight)),
                'sacco': Decimal(str(weight)), 'kg': Decimal(1)}
    return {}


def convert_quantity(value, source, base, bags=None, weight=None, rolls=None, length=None):
    value = number(value)
    source = source or base
    if value < 0:
        raise ValueError('La quantità non può essere negativa / La quantité ne peut pas être négative.')
    if source != base:
        units = factors(bags, weight, rolls, length)
        if source not in units or base not in units:
            raise ValueError('Unità non compatibile con questo articolo / Unité incompatible avec cet article.')
        value = value * units[source] / units[base]
    result = float(value)
    if not math.isfinite(result) or result > 1e12 or (value > 0 and result == 0):
        raise ValueError('Quantità convertita fuori limite / Quantité convertie hors limite.')
    return result


def equivalents(item):
    units = factors(item.sacchi_per_bancale, item.kg_per_sacco, item.rotoli_per_bancale, item.metri_per_rotolo)
    if item.unita_misura not in units:
        return {}
    total = Decimal(str(item.quantita_disponibile or 0)) * units[item.unita_misura]
    return {unit: float(total / factor) for unit, factor in units.items()}


def movement_quantity(item, quantity, unit, note):
    converted = convert_quantity(quantity, unit, item.unita_misura, item.sacchi_per_bancale, item.kg_per_sacco,
                                 item.rotoli_per_bancale, item.metri_per_rotolo)
    if converted <= 0:
        raise ValueError('Inserisci una quantità positiva / Saisissez une quantité positive.')
    if unit and unit != item.unita_misura:
        note = f'{quantity} {unit} = {converted:g} {item.unita_misura}. {(note or "").strip()}'
    return converted, note
