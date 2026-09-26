"""Intent detection: deterministic rules first; LLM classification when ambiguous."""
from __future__ import annotations

import re
import unicodedata
from enum import Enum


class Intent(str, Enum):
    SEARCH_PROPERTY = "SEARCH_PROPERTY"
    PROPERTY_DETAILS = "PROPERTY_DETAILS"
    PROPERTY_IMAGES = "PROPERTY_IMAGES"
    COMPARE_PROPERTIES = "COMPARE_PROPERTIES"
    PROPERTY_DOCUMENT_QUESTION = "PROPERTY_DOCUMENT_QUESTION"
    PRICE_QUERY = "PRICE_QUERY"
    LOCATION_QUERY = "LOCATION_QUERY"
    SAVE_PROPERTY = "SAVE_PROPERTY"
    REMOVE_PROPERTY = "REMOVE_PROPERTY"
    SAVE_SEARCH = "SAVE_SEARCH"
    LIST_SAVED_SEARCHES = "LIST_SAVED_SEARCHES"
    CREATE_ALERT = "CREATE_ALERT"
    LIST_ALERTS = "LIST_ALERTS"
    UPDATE_ALERT = "UPDATE_ALERT"
    PAUSE_ALERT = "PAUSE_ALERT"
    RESUME_ALERT = "RESUME_ALERT"
    DELETE_ALERT = "DELETE_ALERT"
    SCHEDULE_VISIT = "SCHEDULE_VISIT"
    CANCEL_APPOINTMENT = "CANCEL_APPOINTMENT"
    CONTACT_AGENT = "CONTACT_AGENT"
    FINANCING_QUESTION = "FINANCING_QUESTION"
    SELL_PROPERTY = "SELL_PROPERTY"
    RENT_PROPERTY = "RENT_PROPERTY"
    GENERAL_FAQ = "GENERAL_FAQ"
    GENERAL = "GENERAL"
    GREETING = "GREETING"
    UNKNOWN = "UNKNOWN"


_FAV = r"\b(?:guarda(?:r|me|d[oa])?|favorit[oa]s?|me (?:interesa|gusta) (?:esa|esta|ese|esta)|gu[aá]rdal[oa])"
_UNFAV = r"\b(?:quita(?:r|me|rl[oa])?|elimina(?:r|me|rl[oa])?|remueve|borra|qu[ií]tal[oa])"
_VISIT = r"\b(?:agend|agenda|cita|visita|visitarel|visitar|reserv(?:ar|a) (?:una )?visita|programar)"
_COMP = r"\b(?:compar(?:a|ar|ame|e)|diferencias? entre|versus|vs\.?)"
_DOCQ = r"\b(?:reglamento|reglamentos|norma|normas|manual|documento|documentos|dossier|escritura|hoja|pdf|brochure|administraci[oó]n|cuota|expensas)"
_PRICE = r"\b(?:precio|cuesta|vale|cu[aá]nto cuesta|cu[aá]nto vale|costo|valor)"
_LOC = r"\b(?:d[oó]nde|donde queda|ubicaci[oó]n|ubicado|direcci[oó]n|mapa|cerca de)"
_FIN = r"\b(?:financiaci[oó]n|financiar|cr[eé]dito|hipoteca|cuota inicial|subsidio|leasing)"
_SELL = r"\b(?:vender mi|quiero vender|tengo una (?:casa|apartamento)|publicar mi)"
_RENTOUT = r"\b(?:alquilar mi|arrendar mi|doy en arriendo|quiero arrendar)"
_SEARCH_HINTS = r"\b(?:busco|buscar|encu[eé]ntrame|encontrame|muestrame|muestra|quiero ver|tienes|tienen|hay|disponibles?|opciones|describe|detalla|lista)"
# Single image request patterns: "una imagen", "solo una", "una foto", etc.
_SINGLE_IMAGE_REQUEST = r"\b(?:solo\s+una|solamente\s+una|una\s+sola)\s+(?:imagen|foto|fotografia)\b|\b(?:mu[eé]strame|ens[eé]name|quiero\s+ver|dame|env[ií]ame|mandame)\s+una\s+(?:imagen|foto|fotografia)\b|\b(?:quiero|necesito)\s+una\s+(?:imagen|foto)\b"
# Multiple images request patterns: "las fotos", "las imagenes", "todas las fotos", etc.
_MULTI_IMAGE_REQUEST = r"\b(?:las|todas\s+las)\s+(?:fotos|fotografias|imagenes)\b|\b(?:ver|mostrar|mu[eé]strame|enviar|mandar)\s+(?:las|todas)\s+(?:fotos|imagenes)\b|\b(?:todas\s+las\s+fotos|ver\s+todas)\b"
# General image request (fallback)
_IMAGE_REQUEST = r"\b(?:foto|fotos|fotografia|fotografias|imagen|imagenes|picture|pictures)\b|\b(?:ver|ve|mostrar|muestra|mu[eé]strame|enviar|envia|mandar|manda|mandame|enviame|compartir|comparte)\b.*\b(?:foto|fotos|fotografia|fotografias|imagen|imagenes)\b|\b(?:puedo|quiero)\s+(?:ver|tener)\b.*\b(?:foto|fotos|imagen|imagenes)\b|\b(?:envialas|enviamelas|mandalas|mandamelas|muestralas|muestramelas)\b"
# Cover/portada specific request
_COVER_REQUEST = r"\b(?:portada|cover)\b"
# Ordinal image request: "la segunda imagen", "la tercera foto", etc.
_ORDINAL_IMAGE_REQUEST = r"\b(?:la|el)\s+(?:primera|segunda|tercera|cuarta|quinta|\d+)\s+(?:imagen|foto|fotografia)\b"
_LIST_SAVED = r"\b(?:mis b[u\u00fa]squedas?|b[u\u00fa]squedas guardadas|mis alertas|ver (?:mis )?alertas|listar alertas)\b"
_SAVE_SEARCH = r"\b(?:av[\u00ed]same|avisame|notif[i\u00ed]came|gu[a\u00e1]rdame (?:esta |la )?b[u\u00fa]squeda|guardar b[u\u00fa]squeda|crear alerta|alerta)\b"
_CREATE_ALERT = r"\b(?:crear alerta|nueva alerta|quiero alerta|pon(?:er|me) (?:en )?alerta)\b"
_LIST_ALERTS = r"\b(?:mis alertas|ver alertas|listar alertas|qu[eé] alertas tengo)\b"
_UPDATE_ALERT = r"\b(?:cambiar alerta|modificar alerta|actualizar alerta|editar alerta)\b"
_PAUSE_ALERT = r"\b(?:pausar alerta|detener alerta|suspender alerta|parar alerta)\b"
_RESUME_ALERT = r"\b(?:reactivar alerta|reanudar alerta|continuar alerta|activar alerta)\b"
_DELETE_ALERT = r"\b(?:cancelar alerta|eliminar alerta|borrar alerta|quitar alerta)\b"
_CANCEL = r"\b(?:cancel(?:ar|a|ame) (?:la|mi)? ?(?:cita|visita|reserva))"
_CONTACT = r"\b(?:hablar con (?:un )?asesor|contactar asesor|asesor humano|llamar a un asesor|agente humano)"
_SLOTS = r"\b(?:horarios?|horas disponibles|qu[eé] horarios)"
_FAQ = r"\b(?:hola|buenas|gracias|qui[eé]n eres|qu[eé] puedes hacer|ayuda|help)\b"

# --- attribute (feature) questions: "¿la casa tiene piscina?" -----------------
# These must NEVER be answered as a fresh search: the user is asking about a
# specific property, so the answer comes from that property's stored data.
_ATTR_NOUNS = (
    r"\b(?:piscina|garaje|garajes|parqueader[oa]s?|ascensor|ascensores|jardin|terraza|balcon|"
    r"amoblad[oa]|amueblad[oa]|mascotas?|cuartos?|closets?|chimenea|jacuzzi|gimnasio|"
    r"sal[oó]n comun|zonas? verde|vista|deposito|porteria)\b"
)
_POSSESS = r"\b(?:tiene|tienen|cuenta con|incluye|trae|viene con|acepta|aceptan|permiten|hay)\b"
_SINGULAR_REF = (
    r"\b(?:la|el|esa|ese|esta|este|aquel|aquella)\s+"
     r"(?:casa|casita|apartamento|apto|propiedad|inmueble|"
     r"penthouse|torre|codigo)\b"
)
# plural property nouns signal a NEW search ("¿tienen casas con piscina?")
_PLURAL_TYPE = r"\b(?:casas|apartamentos|aptos|inmuebles|propiedades)\b"


def _deaccent_low(message: str) -> str:
    low = (message or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", low) if not unicodedata.combining(c))


def mentions_attribute(message: str) -> bool:
    """True when the message names a concrete property feature/amenity."""
    return bool(re.search(_ATTR_NOUNS, _deaccent_low(message)))


def is_attribute_question(message: str) -> bool:
    """True for questions about an attribute of a *referenced* property.

    'la casa familiar tiene piscina?'  -> True  (answer from stored features)
    'tienen casas con piscina?'        -> False (that is a new search)
    '¿dónde queda la casa con garaje?' -> False (that is a location question)
    """
    low = _deaccent_low(message)
    if not re.search(_ATTR_NOUNS, low):
        return False
    if re.search(_PLURAL_TYPE, low):
        return False
    # location / price questions ask about another field entirely
    if re.search(_LOC, low) or re.search(_PRICE, low):
        return False
    return bool(re.search(_POSSESS, low) or re.search(_SINGULAR_REF, low))


def detect_intent(message: str) -> Intent:
    low = (message or "").lower().strip()
    if not low:
        return Intent.UNKNOWN
    # work on de-accented text so "compárame"/"cuántos" match reliably
    low = "".join(c for c in unicodedata.normalize("NFD", low) if not unicodedata.combining(c))

    if re.search(_CANCEL, low):
        return Intent.CANCEL_APPOINTMENT
    
    # Check for explicit search criteria (operation, property type, budget, location)
    # These indicate a NEW search, not a follow-up on current property
    has_operation = bool(re.search(r"\b(arriendo|alquiler|alquilar|arrendar|venta|comprar|comprar)\b", low))
    has_property_type = bool(re.search(r"\b(casa|apartamento|apto)\b", low))
    has_budget = bool(re.search(r"\b(\d+\s*(?:millones?|palos?|k|mil)|un\s+mill[oó]n|dos\s+millones?|tres\s+millones?|cuatro\s+millones?|cinco\s+millones?)\b", low))
    has_location = bool(re.search(r"\b(en|cerca de|zona|barrio|ciudad)\b", low))
    has_rooms = bool(re.search(r"\b(\d+\s*hab|habitaciones?|alcobas?|cuartos?)\b", low))
    
    # Count how many search criteria are present
    search_criteria_count = sum([has_operation, has_property_type, has_budget, has_location, has_rooms])
    
    # If message has 2+ search criteria AND mentions images, it's a NEW search with image request
    # (not a follow-up for current property images)
    if search_criteria_count >= 2 and re.search(_IMAGE_REQUEST, low):
        return Intent.SEARCH_PROPERTY
    
    # Cover/portada specific request
    if re.search(_COVER_REQUEST, low):
        return Intent.PROPERTY_IMAGES
    
    # Ordinal image request: "la segunda imagen", "la tercera foto", etc.
    if re.search(_ORDINAL_IMAGE_REQUEST, low):
        return Intent.PROPERTY_IMAGES
    
    # Photo/image requests for a specific property (no significant search criteria)
    if re.search(_IMAGE_REQUEST, low):
        return Intent.PROPERTY_IMAGES
    # comparison wins over the explicit-code rule ("diferencias entre PROP-0001 y PROP-0002")
    if re.search(_COMP, low):
        return Intent.COMPARE_PROPERTIES
    # explicit property code → details (even with extra questions)
    if re.search(r"\bprop[- ]?\d+\b", low):
        return Intent.PROPERTY_DETAILS
    if re.search(_VISIT, low) or re.search(_SLOTS, low):
        return Intent.SCHEDULE_VISIT
    if re.search(_FIN, low):
        return Intent.FINANCING_QUESTION
    if re.search(_SELL, low):
        return Intent.SELL_PROPERTY
    if re.search(_RENTOUT, low):
        return Intent.RENT_PROPERTY
    # "avísame cuando aparezca una casa..." creates an alert → SAVE_SEARCH wins
    # over LIST_SAVED_SEARCHES, which is only about reading existing alerts.
    if re.search(_SAVE_SEARCH, low):
        return Intent.SAVE_SEARCH
    if re.search(_LIST_SAVED, low):
        return Intent.LIST_SAVED_SEARCHES
    # Alert management intents
    if re.search(_CREATE_ALERT, low):
        return Intent.CREATE_ALERT
    if re.search(_LIST_ALERTS, low):
        return Intent.LIST_ALERTS
    if re.search(_UPDATE_ALERT, low):
        return Intent.UPDATE_ALERT
    if re.search(_PAUSE_ALERT, low):
        return Intent.PAUSE_ALERT
    if re.search(_RESUME_ALERT, low):
        return Intent.RESUME_ALERT
    if re.search(_DELETE_ALERT, low):
        return Intent.DELETE_ALERT
    if re.search(_UNFAV, low):
        return Intent.REMOVE_PROPERTY
    if re.search(_FAV, low):
        return Intent.SAVE_PROPERTY
    if re.search(_CONTACT, low):
        return Intent.CONTACT_AGENT

    # attribute questions about a referenced property ("¿la casa tiene piscina?")
    # are NOT searches: they are answered from that property's stored data.
    if is_attribute_question(low):
        return Intent.PROPERTY_DETAILS

    # document questions win over generic search when they ask about docs/quantities
    asks_docs = bool(re.search(_DOCQ, low))
    asks_quantity = bool(re.search(r"\b(cuant[oa]s?|numero de|cuantos)\b", low))
    if (asks_docs or (asks_quantity and "?" in low)) and not re.search(_PRICE, low):
        return Intent.PROPERTY_DOCUMENT_QUESTION

    if re.search(_PRICE, low) and len(low.split()) <= 14:
        return Intent.PRICE_QUERY

    has_search_hint = bool(re.search(_SEARCH_HINTS, low))
    has_criteria = bool(
        re.search(
            r"(\d+\s*(?:millones?|hab|habitaciones)|casa|apartamento|"
             r"garaje|parqueadero|banos|m2|metros)",
            low,
        )
    )
    if has_search_hint and (has_criteria or len(low.split()) >= 4):
        return Intent.SEARCH_PROPERTY
    if re.search(_LOC, low):
        return Intent.LOCATION_QUERY
    if asks_docs:
        return Intent.PROPERTY_DOCUMENT_QUESTION

    # reference/short follow-ups about previously listed properties
    if re.search(r"\b(?:la|el|esa|ese|opcion)\s*(?:primera|segunda|tercera|cuarta|quinta|\d)", low) or low in (
        "la primera", "la segunda", "la tercera", "la cuarta", "la quinta",
        "esa", "ese", "la anterior",
        "cuentame mas", "mas informacion", "mas", "dime mas",
    ):
        return Intent.PROPERTY_DETAILS
    # price-based reference to a shown property ("la de 280 millones")
    if re.search(r"\b(?:la|el|esa|ese|aquella|aquel)\s+(?:que\s+)?de\s*\$?\d", low):
        return Intent.PROPERTY_DETAILS

    if has_criteria and len(low.split()) >= 3:
        return Intent.SEARCH_PROPERTY
    if re.search(r"\b(?:hola|buenas|hey|que tal|buenos dias|buenas tardes|buenas noches)\b", low) and len(low.split()) <= 4:
        return Intent.GREETING
    if re.search(_FAQ, low):
        return Intent.GENERAL_FAQ
    if "?" in low:
        return Intent.PROPERTY_DOCUMENT_QUESTION
    return Intent.UNKNOWN
