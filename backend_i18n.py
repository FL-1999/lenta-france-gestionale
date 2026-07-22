"""
Traduzione IT/FR dei messaggi di errore del backend (HTTPException detail).

I messaggi vengono sollevati nel codice in una lingua sola (per lo più italiano,
alcuni già in francese). Invece di toccare ~170 punti di `raise`, traduciamo in
uscita: `translate_message(msg, lang)` cerca il testo sorgente nel dizionario e
restituisce la versione nella lingua richiesta.

Il dizionario è indicizzato sulla stringa SORGENTE così com'è scritta nel codice
(che sia italiana o francese) e mappa a (italiano, francese).
Per i messaggi dinamici (f-string) usiamo regole regex che preservano la parte
variabile.
"""
from __future__ import annotations

import re

# sorgente -> (italiano, francese)
_MESSAGES: dict[str, tuple[str, str]] = {
    "La profondità totale deve essere maggiore di zero.": (
        "La profondità totale deve essere maggiore di zero.",
        "La profondeur totale doit être supérieure à zéro.",
    ),
    "Inserisci il diametro del palo in centimetri.": (
        "Inserisci il diametro del palo in centimetri.",
        "Saisissez le diamètre du pieu en centimètres.",
    ),
    "Il diametro del palo deve essere maggiore di zero.": (
        "Il diametro del palo deve essere maggiore di zero.",
        "Le diamètre du pieu doit être supérieur à zéro.",
    ),
    "Per la paratia devi indicare larghezza e spessore pannello.": (
        "Per la paratia devi indicare larghezza e spessore pannello.",
        "Pour la paroi, indiquez la largeur et l'épaisseur du panneau.",
    ),
    "La larghezza del pannello deve essere maggiore di zero.": (
        "La larghezza del pannello deve essere maggiore di zero.",
        "La largeur du panneau doit être supérieure à zéro.",
    ),
    "Lo spessore del pannello deve essere maggiore di zero.": (
        "Lo spessore del pannello deve essere maggiore di zero.",
        "L'épaisseur du panneau doit être supérieure à zéro.",
    ),
    "Le volume total théorique ne peut pas être négatif.": (
        "Il volume totale teorico non può essere negativo.",
        "Le volume total théorique ne peut pas être négatif.",
    ),
    "Ogni valore Da (m) deve essere minore del relativo A (m).": (
        "Ogni valore Da (m) deve essere minore del relativo A (m).",
        "Chaque valeur De (m) doit être inférieure au A (m) correspondant.",
    ),
    "Gli strati di stratigrafia devono essere continui.": (
        "Gli strati di stratigrafia devono essere continui.",
        "Les couches de stratigraphie doivent être continues.",
    ),
    "Il campo Metri cubi gettati è obbligatorio.": (
        "Il campo Metri cubi gettati è obbligatorio.",
        "Le champ Mètres cubes coulés est obligatoire.",
    ),
    "Il campo Metri cubi gettati non può essere negativo.": (
        "Il campo Metri cubi gettati non può essere negativo.",
        "Le champ Mètres cubes coulés ne peut pas être négatif.",
    ),
    "La quota testa getto non può essere superiore alla quota TN.": (
        "La quota testa getto non può essere superiore alla quota TN.",
        "La cote de tête de coulage ne peut pas dépasser la cote TN.",
    ),
    "Décrire le sol rencontré est obligatoire pour le terrain Autre.": (
        "Descrivere il terreno incontrato è obbligatorio per il terreno Altro.",
        "Décrire le sol rencontré est obligatoire pour le terrain Autre.",
    ),
    "Macchinario non valido": (
        "Macchinario non valido",
        "Machine non valide",
    ),
    "Capocantiere non valido": (
        "Capocantiere non valido",
        "Chef de chantier non valide",
    ),
    "Coupe di progetto non valida": (
        "Coupe di progetto non valida",
        "Coupe de projet non valide",
    ),
    "Ce numéro n’appartient pas à la coupe sélectionnée": (
        "Questo numero non appartiene alla coupe selezionata",
        "Ce numéro n’appartient pas à la coupe sélectionnée",
    ),
    "Il campo profondità totale scavata è obbligatorio.": (
        "Il campo profondità totale scavata è obbligatorio.",
        "Le champ profondeur totale excavée est obligatoire.",
    ),
    "Ogni strato di stratigrafia deve avere Da (m) e A (m).": (
        "Ogni strato di stratigrafia deve avere Da (m) e A (m).",
        "Chaque couche de stratigraphie doit avoir De (m) et A (m).",
    ),
    "Inserire almeno uno strato di stratigrafia.": (
        "Inserire almeno uno strato di stratigrafia.",
        "Saisissez au moins une couche de stratigraphie.",
    ),
    "Il campo Operatore / squadra è obbligatorio.": (
        "Il campo Operatore / squadra è obbligatorio.",
        "Le champ Opérateur / équipe est obligatoire.",
    ),
    "Cantiere non trovato": (
        "Cantiere non trovato",
        "Chantier introuvable",
    ),
    "Cantiere non valido": (
        "Cantiere non valido",
        "Chantier non valide",
    ),
    "Sonic réalisé ? è obbligatorio.": (
        "Sonic réalisé ? è obbligatorio.",
        "Sonic réalisé ? est obligatoire.",
    ),
    "Inclinomètre réalisé ? è obbligatorio.": (
        "Inclinomètre réalisé ? è obbligatorio.",
        "Inclinomètre réalisé ? est obligatoire.",
    ),
    "Macchinario non trovato": (
        "Macchinario non trovato",
        "Machine introuvable",
    ),
    "Utente disattivato": (
        "Utente disattivato",
        "Utilisateur désactivé",
    ),
    "Ruolo non valido": (
        "Ruolo non valido",
        "Rôle non valide",
    ),
    "Utente non trovato": (
        "Utente non trovato",
        "Utilisateur introuvable",
    ),
    "Cambio ruolo non consentito": (
        "Cambio ruolo non consentito",
        "Changement de rôle non autorisé",
    ),
    "Ruolo non assegnato all'utente": (
        "Ruolo non assegnato all'utente",
        "Rôle non attribué à l'utilisateur",
    ),
    "Permessi insufficienti": (
        "Permessi insufficienti",
        "Autorisations insuffisantes",
    ),
    "Non autorizzato": (
        "Non autorizzato",
        "Non autorisé",
    ),
    "Errore durante l'aggiornamento dei permessi": (
        "Errore durante l'aggiornamento dei permessi",
        "Erreur lors de la mise à jour des autorisations",
    ),
    "Non puoi modificare il tuo stato attivo": (
        "Non puoi modificare il tuo stato attivo",
        "Vous ne pouvez pas modifier votre propre statut actif",
    ),
    "Errore durante l'aggiornamento dello stato utente": (
        "Errore durante l'aggiornamento dello stato utente",
        "Erreur lors de la mise à jour du statut de l'utilisateur",
    ),
    "Il totale paratie da scavare non è valido.": (
        "Il totale paratie da scavare non è valido.",
        "Le total des parois à excaver n'est pas valide.",
    ),
    "Il totale paratie da scavare non può essere negativo.": (
        "Il totale paratie da scavare non può essere negativo.",
        "Le total des parois à excaver ne peut pas être négatif.",
    ),
    "Selezionare una tipologia di scavo valida: paratia o palo.": (
        "Selezionare una tipologia di scavo valida: paratia o palo.",
        "Sélectionnez un type d'excavation valide : paroi ou pieu.",
    ),
    "Cantiere non assegnato": (
        "Cantiere non assegnato",
        "Chantier non attribué",
    ),
    "Titolo obbligatorio": (
        "Titolo obbligatorio",
        "Titre obligatoire",
    ),
    "Assegnatario non valido": (
        "Assegnatario non valido",
        "Attributaire non valide",
    ),
    "Assegnatario non trovato": (
        "Assegnatario non trovato",
        "Attributaire introuvable",
    ),
    "Associazione paratie/pali non valida.": (
        "Associazione paratie/pali non valida.",
        "Association parois/pieux non valide.",
    ),
    "Non puoi eliminare una coupe già associata a fiches salvate.": (
        "Non puoi eliminare una coupe già associata a fiches salvate.",
        "Vous ne pouvez pas supprimer une coupe déjà associée à des fiches enregistrées.",
    ),
    "Una paratia/palo non può essere associata a più coupe.": (
        "Una paratia/palo non può essere associata a più coupe.",
        "Une paroi/un pieu ne peut pas être associé à plusieurs coupes.",
    ),
    "Task non trovato": (
        "Task non trovato",
        "Tâche introuvable",
    ),
    "Nome e codice sono obbligatori": (
        "Nome e codice sono obbligatori",
        "Le nom et le code sont obligatoires",
    ),
    "Stato non valido": (
        "Stato non valido",
        "Statut non valide",
    ),
    "Caposquadra non valido": (
        "Caposquadra non valido",
        "Chef d'équipe non valide",
    ),
    "Solo un amministratore può eliminare un cantiere": (
        "Solo un amministratore può eliminare un cantiere",
        "Seul un administrateur peut supprimer un chantier",
    ),
    "Il nome digitato non coincide: eliminazione annullata": (
        "Il nome digitato non coincide: eliminazione annullata",
        "Le nom saisi ne correspond pas : suppression annulée",
    ),
    "Solo un amministratore può eliminare una coupe": (
        "Solo un amministratore può eliminare una coupe",
        "Seul un administrateur peut supprimer une coupe",
    ),
    "Coupe non trovata": (
        "Coupe non trovata",
        "Coupe introuvable",
    ),
    "Il totale personale deve essere almeno 1": (
        "Il totale personale deve essere almeno 1",
        "Le total du personnel doit être d'au moins 1",
    ),
    "Il totale personale deve corrispondere a caposquadra + operai selezionati": (
        "Il totale personale deve corrispondere a caposquadra + operai selezionati",
        "Le total du personnel doit correspondre au chef d'équipe + ouvriers sélectionnés",
    ),
    "Non puoi selezionare la stessa persona due volte": (
        "Non puoi selezionare la stessa persona due volte",
        "Vous ne pouvez pas sélectionner la même personne deux fois",
    ),
    "Il caposquadra è già incluso nel totale personale": (
        "Il caposquadra è già incluso nel totale personale",
        "Le chef d'équipe est déjà inclus dans le total du personnel",
    ),
    "Fiche non trovata": (
        "Fiche non trovata",
        "Fiche introuvable",
    ),
    "Type non valide": (
        "Tipo non valido",
        "Type non valide",
    ),
    "Chantier non trouvé": (
        "Cantiere non trovato",
        "Chantier non trouvé",
    ),
    # messaggi fallback usati altrove
    "Errore durante la creazione della nota": (
        "Errore durante la creazione della nota",
        "Erreur lors de la création de la note",
    ),
}

# Messaggi dinamici (f-string): (regex sorgente, template_it, template_fr)
# I gruppi nominati vengono reinseriti nelle traduzioni.
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"^Il campo (?P<f>.+) non è valido\.$"),
        "Il campo {f} non è valido.",
        "Le champ {f} n'est pas valide.",
    ),
    (
        re.compile(r"^Il campo (?P<f>.+) non può essere negativo\.$"),
        "Il campo {f} non può essere negativo.",
        "Le champ {f} ne peut pas être négatif.",
    ),
    (
        re.compile(r"^(?P<f>.+) non valido$"),
        "{f} non valido",
        "{f} non valide",
    ),
    (
        re.compile(r"^Chaque ligne (?P<f>.+) doit avoir Volume \(m³\) et Hauteur \(m\)\.$"),
        "Ogni riga {f} deve avere Volume (m³) e Altezza (m).",
        "Chaque ligne {f} doit avoir Volume (m³) et Hauteur (m).",
    ),
    (
        re.compile(r"^Le volume (?P<f>.+) ne peut pas être négatif\.$"),
        "Il volume {f} non può essere negativo.",
        "Le volume {f} ne peut pas être négatif.",
    ),
    (
        re.compile(r"^(?P<n>.+) già registrato per questo cantiere$"),
        "{n} già registrato per questo cantiere",
        "{n} déjà enregistré pour ce chantier",
    ),
    (
        re.compile(r"^Aucune fiche (?P<f>.+) pour ce chantier$"),
        "Nessuna fiche {f} per questo cantiere",
        "Aucune fiche {f} pour ce chantier",
    ),
]


def translate_message(message: object, lang: str) -> object:
    """Traduce un messaggio di errore backend nella lingua richiesta.

    Se il messaggio non è mappato (o non è una stringa) viene restituito
    invariato, così non rischiamo mai di nascondere un errore.
    """
    if not isinstance(message, str):
        return message
    idx = 0 if lang != "fr" else 1

    entry = _MESSAGES.get(message)
    if entry is not None:
        return entry[idx]

    for pattern, tmpl_it, tmpl_fr in _PATTERNS:
        m = pattern.match(message)
        if m:
            tmpl = tmpl_it if idx == 0 else tmpl_fr
            try:
                return tmpl.format(**m.groupdict())
            except (KeyError, IndexError):
                return message

    return message
