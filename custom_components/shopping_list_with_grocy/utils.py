from .const import DOMAIN


def update_domain_data(hass, key, content):
    if hass.data.get(DOMAIN) and hass.data[DOMAIN].get(key):
        hass.data[DOMAIN][key].update(content)
    else:
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][key] = content


def is_update_paused(hass):
    entity = hass.data[DOMAIN]["entities"].get("pause_update_shopping_list_with_grocy")

    if entity is None:
        return False

    return entity.is_on


def convert_word_to_number(word_input):
    """Convert spoken numbers (in French, English, Spanish, German) to integers.

    Args:
        word_input: String that could be a number or a word representing a number

    Returns:
        int: The number as integer, or None if conversion fails
    """
    if not word_input:
        return None

    word = str(word_input).strip().lower()

    try:
        return int(word)
    except ValueError:
        pass

    word_to_num = {
        "un": 1,
        "une": 1,
        "premier": 1,
        "première": 1,
        "deux": 2,
        "deuxième": 2,
        "second": 2,
        "seconde": 2,
        "trois": 3,
        "troisième": 3,
        "quatre": 4,
        "quatrième": 4,
        "cinq": 5,
        "cinquième": 5,
        "six": 6,
        "sixième": 6,
        "sept": 7,
        "septième": 7,
        "huit": 8,
        "huitième": 8,
        "neuf": 9,
        "neuvième": 9,
        "dix": 10,
        "dixième": 10,
        "one": 1,
        "first": 1,
        "two": 2,
        "second": 2,
        "three": 3,
        "third": 3,
        "four": 4,
        "fourth": 4,
        "five": 5,
        "fifth": 5,
        "six": 6,
        "sixth": 6,
        "seven": 7,
        "seventh": 7,
        "eight": 8,
        "eighth": 8,
        "nine": 9,
        "ninth": 9,
        "ten": 10,
        "tenth": 10,
        "uno": 1,
        "una": 1,
        "primero": 1,
        "primera": 1,
        "dos": 2,
        "segundo": 2,
        "segunda": 2,
        "tres": 3,
        "tercero": 3,
        "tercera": 3,
        "cuatro": 4,
        "cuarto": 4,
        "cuarta": 4,
        "cinco": 5,
        "quinto": 5,
        "quinta": 5,
        "seis": 6,
        "sexto": 6,
        "sexta": 6,
        "siete": 7,
        "séptimo": 7,
        "séptima": 7,
        "ocho": 8,
        "octavo": 8,
        "octava": 8,
        "nueve": 9,
        "noveno": 9,
        "novena": 9,
        "diez": 10,
        "décimo": 10,
        "décima": 10,
        "eins": 1,
        "ein": 1,
        "eine": 1,
        "erste": 1,
        "erster": 1,
        "erstes": 1,
        "zwei": 2,
        "zweite": 2,
        "zweiter": 2,
        "zweites": 2,
        "drei": 3,
        "dritte": 3,
        "dritter": 3,
        "drittes": 3,
        "vier": 4,
        "vierte": 4,
        "vierter": 4,
        "viertes": 4,
        "fünf": 5,
        "fünfte": 5,
        "fünfter": 5,
        "fünftes": 5,
        "sechs": 6,
        "sechste": 6,
        "sechster": 6,
        "sechstes": 6,
        "sieben": 7,
        "siebte": 7,
        "siebter": 7,
        "siebtes": 7,
        "acht": 8,
        "achte": 8,
        "achter": 8,
        "achtes": 8,
        "neun": 9,
        "neunte": 9,
        "neunter": 9,
        "neuntes": 9,
        "zehn": 10,
        "zehnte": 10,
        "zehnter": 10,
        "zehntes": 10,
    }

    if word in word_to_num:
        return word_to_num[word]

    words = word.split()
    for w in words:
        if w in word_to_num:
            return word_to_num[w]

    for char in reversed(word):
        if char.isdigit():
            try:
                return int(char)
            except ValueError:
                pass

    return None
