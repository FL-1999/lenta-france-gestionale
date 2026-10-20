"""Optional field descriptions, stored with the existing layer material."""

GRAIN = {"molto_fine": "molto fine", "fine": "fine", "grossolano": "grossolano"}
SIZE = {"0_50": "0-50 mm", "50_100": "50-100 mm", "oltre_100": ">100 mm"}
FINES = {"assenti": "senza frazione fine"}
SEPARATOR = " · "


def split_description(material):
    """Only decode our exact suffixes; leave historical free text untouched."""
    parts = str(material or "").split(SEPARATOR)
    grain, size, fines = "", "", ""
    while len(parts) > 1:
        value = parts[-1]
        if not fines and value in FINES.values():
            fines = next(key for key, label in FINES.items() if label == value)
        elif not size and value in SIZE.values():
            size = next(key for key, label in SIZE.items() if label == value)
        elif not grain and value in GRAIN.values():
            grain = next(key for key, label in GRAIN.items() if label == value)
        else:
            break
        parts.pop()
    return SEPARATOR.join(parts), grain, size, fines


def describe_material(material, grain="", size="", fines=""):
    if grain and grain not in GRAIN or size and size not in SIZE or fines and fines not in FINES:
        raise ValueError("Caratteristica del terreno non valida.")
    base, _, _, _ = split_description(material)
    if (grain or size or fines) and not base.strip():
        raise ValueError("Seleziona il materiale prima delle caratteristiche del terreno.")
    result = SEPARATOR.join(filter(None, (base, GRAIN.get(grain), SIZE.get(size), FINES.get(fines))))
    if len(result) > 100:
        raise ValueError("La descrizione completa del terreno può contenere al massimo 100 caratteri.")
    return result
