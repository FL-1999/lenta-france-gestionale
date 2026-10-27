"""Document language is independent of the application's UI language.

Only fixed labels and recognized technical vocabulary are translated. Free
observations, names and identifiers are never rewritten by a PDF export.
"""
import re


REPORT_IT = {
    "Départ du forage": "Partenza scavo",
    "Voir annexe": "Vedi allegato",
    "Rapport d'exécution": "Rapporto di esecuzione",
    "RAPPORT D’EXÉCUTION DE": "RAPPORTO DI ESECUZIONE",
    "Rapport d'exécution imprimable": "Rapporto di esecuzione stampabile",
    "À VÉRIFIER — NON CONFIRMÉE": "DA VERIFICARE — NON CONFERMATA",
    "Pieu": "Palo", "Paroi moulée": "Paratia", "Panneau": "Pannello",
    "PIEU": "PALO", "PANNEAU": "PANNELLO", "CHANTIER": "CANTIERE",
    "RESPONSABLE": "RESPONSABILE", "COUPE": "SEZIONE", "DATE DE FORAGE": "DATA DI SCAVO",
    "Données générales": "Dati generali", "Date de forage": "Data di scavo",
    "Chantier": "Cantiere", "Responsable": "Responsabile", "Machine": "Macchinario",
    "Bétonnage": "Getto", "Type béton": "Tipo calcestruzzo", "Type coulage": "Tipo getto",
    "Terrain naturel (TN)": "Terreno naturale (TN)", "Cote tête béton": "Quota testa getto",
    "Largeur": "Larghezza", "Épaisseur": "Spessore", "Epaisseur": "Spessore",
    "Longueur forée": "Profondità scavata", "Base paroi mécanique": "Base paratia meccanica",
    "Volume théorique": "Volume teorico", "Volume réel": "Volume reale",
    "Différence / surconsommation": "Differenza / sovraconsumo",
    "Contrôles spéciaux": "Controlli speciali", "Contrôles spéciaux réalisés": "Controlli speciali eseguiti",
    "Sonique": "Prova sonica", "Inclinomètre": "Inclinometro",
    "Contrôle boue": "Controllo fanghi", "Densité": "Densità", "Sable %": "Sabbia %",
    "Viscosité": "Viscosità", "Observation": "Osservazioni", "Observations": "Osservazioni",
    "Observations détaillées : voir annexe A4.": "Osservazioni complete: vedi allegato A4.",
    "Armature": "Armatura", "Sols rencontrés": "Terreni incontrati",
    "Modèle géologique théorique": "Modello geologico teorico", "couches": "strati",
    "Description et cotes": "Descrizione e quote", "voir annexe A4.": "vedi allegato A4.",
    "non renseigné": "non indicato", "Non renseigné": "Non indicato",
    "Section paroi/pieu avec cotes": "Sezione paratia/palo con quote",
    "Départ du forage (profondeur 0 m)": "Partenza scavo (profondità 0 m)",
    "Murette Guide": "Muretto guida", "Diamètre en tête": "Diametro in testa",
    "BASE PAROI MECANIQUE": "BASE PARATIA MECCANICA",
    "BASE PAROI HYDRAULIQUE": "BASE PARATIA IDRAULICA",
    "Comparaison des sols et cotes": "Confronto terreni e quote", "Cotes": "Quote",
    "Rencontré": "Incontrato", "Théorique": "Teorico",
    "Même échelle de profondeur": "Stessa scala di profondità",
    "Paroi, murettes guides et sols à la même échelle": "Paratia, muretti guida e terreni alla stessa scala",
    "COURBE DE BÉTONNAGE": "CURVA DI GETTO", "Réalisée": "Reale", "Tube": "Tubo",
    "Volume total": "Volume totale", "Hauteur init.": "Altezza iniz.", "Pts relevés": "Punti rilevati",
    "Pts tube": "Punti tubo", "Volume en m³": "Volume in m³", "Hauteur en m": "Altezza in m",
    "Profondeur restante (m)": "Profondità residua (m)",
    "Synthèse des valeurs théoriques et des relevés réalisés.": "Riepilogo dei valori teorici e delle misure rilevate.",
    "Données théoriques courbe de bétonnage": "Dati teorici della curva di getto",
    "Volume total théorique": "Volume totale teorico", "Hauteur initiale": "Altezza iniziale",
    "Hauteur finale": "Altezza finale", "Points relevés": "Punti rilevati", "Points tube": "Punti tubo",
    "VISA": "FIRME", "ENTREPRISE": "IMPRESA", "CLIENT": "CLIENTE", "MAÎTRE D'ŒUVRE": "DIREZIONE LAVORI",
    "Annexe - terrains et observations": "Allegato - terreni e osservazioni",
    "Profondeur 0 m": "Profondità 0 m", "Profondeur (m)": "Profondità (m)",
    "De": "Da", "À": "A", "Nature du sol": "Tipo di terreno",
    "ANGLE": "ANGOLO", "BÉTONNAGE COMMUN": "GETTO CONGIUNTO",
    "Fiche unique": "Fiche unica", "Schéma : développement des bras, largeur nette totale.": "Schema: sviluppo dei bracci, larghezza netta complessiva.",
    "Total commun": "Totale comune", "Part de cette fiche": "Quota di questa fiche",
    "répartie, non mesurée séparément": "ripartita, non misurata separatamente",
    "Client": "Cliente", "Maître d'œuvre": "Direzione lavori", "Entreprise": "Impresa",
    "PAROIS ET PIEUX": "PARATIE E PALI", "PIEUX": "PALI", "PAROI MOULEE": "PARATIA",
    "SUIVI DE MISSION G3": "MONITORAGGIO MISSIONE G3",
    "FICHES DE FORAGES DES": "SCHEDE DI SCAVO",
    "PANNEAUX ET PIEUX": "PANNELLI E PALI", "PANNEAUX": "PANNELLI",
    "AFFAIRE": "COMMESSA", "INDICE": "REVISIONE", "Descriptif des terrains": "Descrizione dei terreni",
    "Les rapports d'étude géotechnique du projet ont établi le modèle géologique suivant :": "Le relazioni geotecniche di progetto definiscono il seguente modello geologico:",
    "L'exécution de la fondation profonde ne nous permet pas d'avoir une description aussi précise.": "L'esecuzione della fondazione profonda non consente una descrizione altrettanto precisa.",
    "L'exécution de la paroi moulée ne nous permet pas d'avoir une description aussi précise.": "L'esecuzione della paratia non consente una descrizione altrettanto precisa.",
    "Notre descriptif sera plus général car les outils utilisés pour la foration déorganisent le terrain en place (benne preneuse, bucket,…)": "La descrizione è più generale perché gli utensili di scavo rimaneggiano il terreno in posto (benna mordente, bucket, ecc.).",
    "indice": "revisione", "date": "data", "Sujet révision": "Oggetto revisione",
    "Rédaction": "Redazione", "Contrôle": "Verifica", "Première diffusion": "Prima emissione",
}

# Whole phrases first, then individual terms. User-entered free descriptions
# are preserved; these replacements only standardize known soil terminology.
TECHNICAL_PAIRS = (
    ("Quota testa getto", "Cote tête béton"), ("Quota testa", "Cote tête"), ("Quota fondo", "Cote fond"),
    ("Paratia", "Paroi moulée"), ("Pannello", "Paroi"), ("Palo", "Pieu"),
    ("Incontrato", "Rencontré"), ("Teorico", "Théorique"),
    ("Ciottoli grossi", "Gros cailloux"), ("Senza frazione fine", "Sans fines"),
    ("Molto fine", "Très fin"), ("Grossolano", "Grossier"), ("Fine", "Fin"),
    ("Roccia", "Roche"), ("Riporto", "Remblais"), ("Sabbia", "Sable"),
    ("Argilla", "Argile"), ("Ghiaia", "Gravier"), ("Limo", "Limon"), ("Altro", "Autre"),
    ("Gravitazionale", "Gravitaire"),
)


def report_language(value):
    return value if value in ("fr", "it") else "fr"


def report_translator(language="fr"):
    return (lambda text: REPORT_IT.get(text, text)) if language == "it" else (lambda text: text)


def technical_text(value, language="fr"):
    text = "" if value is None else str(value)
    pairs = TECHNICAL_PAIRS if language != "it" else tuple((fr, it) for it, fr in TECHNICAL_PAIRS)
    pattern = r"\b(?:" + "|".join(re.escape(source) for source, _ in pairs) + r")\b"
    targets = {source.casefold(): target for source, target in pairs}
    return re.sub(pattern, lambda match: targets[match.group().casefold()], text, flags=re.IGNORECASE)


def technical_translator(language="fr"):
    return lambda value: technical_text(value, language)
