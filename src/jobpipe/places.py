"""Where a posting is: city, countries and whether it is remote, from free text.

Sources describe places their own way: "Zürich, Zürich, Switzerland",
"New York, NY" with the country in a separate field, "Barcelona (HQ)", or
several places joined by ";". The text is kept as published; this adds:

- countries: ISO 3166 alpha-2 codes, in the order they appear;
- city: the first city named, with one spelling for the cities that have
  several (Zürich, Genève, München...);
- remote: the text offers remote work.

A place's country comes from a country named in it, else from the source's
country field, else from the short list of cities below (Personio and HN give
only a city). Two-letter codes are trusted only in the country field: in the
text, "CA" is more often California than Canada. An unknown place gives no
country rather than a guess.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

COUNTRIES: dict[str, str] = {
    "CH": "switzerland|schweiz|suisse|svizzera",
    "ES": "spain|espana",
    "DE": "germany|deutschland",
    "AT": "austria|osterreich",
    "FR": "france",
    "IT": "italy|italia",
    "NL": "netherlands|the netherlands|holland|nederland",
    "BE": "belgium|belgique|belgie",
    "LU": "luxembourg",
    "IE": "ireland",
    "GB": "united kingdom|uk|great britain|britain|england|scotland|wales|northern ireland",
    "PT": "portugal",
    "DK": "denmark|danmark",
    "SE": "sweden|sverige",
    "NO": "norway|norge",
    "FI": "finland|suomi",
    "IS": "iceland",
    "PL": "poland|polska",
    "CZ": "czech republic|czechia",
    "SK": "slovakia",
    "HU": "hungary",
    "RO": "romania",
    "BG": "bulgaria",
    "GR": "greece",
    "HR": "croatia",
    "SI": "slovenia",
    "EE": "estonia",
    "LV": "latvia",
    "LT": "lithuania",
    "CY": "cyprus",
    "MT": "malta",
    "LI": "liechtenstein",
    "RS": "serbia",
    "MK": "north macedonia|macedonia",
    "BA": "bosnia|bosnia and herzegovina",
    "AL": "albania",
    "UA": "ukraine",
    "TR": "turkey|turkiye",
    "US": "united states|united states of america|usa|us|u.s.|u.s.a.",
    "CA": "canada",
    "MX": "mexico",
    "BR": "brazil|brasil",
    "AR": "argentina",
    "CL": "chile",
    "CO": "colombia",
    "IN": "india",
    "JP": "japan",
    "KR": "south korea|korea|republic of korea",
    "CN": "china",
    "HK": "hong kong",
    "TW": "taiwan",
    "SG": "singapore",
    "AU": "australia",
    "NZ": "new zealand",
    "IL": "israel",
    "AE": "united arab emirates|uae",
    "ZA": "south africa",
    "PH": "philippines",
    "SA": "saudi arabia",
    "ID": "indonesia",
    "MY": "malaysia",
    "TH": "thailand",
    "VN": "vietnam",
    "EG": "egypt",
    "MA": "morocco",
    "KE": "kenya",
    "NG": "nigeria",
    "PE": "peru",
    "UY": "uruguay",
    "CR": "costa rica",
    "QA": "qatar",
    "PK": "pakistan",
}

# Cities seen in the sources, or likely to be. Ambiguous names (Cambridge,
# Santiago, Baden, Birmingham...) are left out on purpose.
CITIES: dict[str, str] = {
    "CH": "Zurich|Geneva|Lausanne|Basel|Bern|Lugano|Zug|Winterthur|Lucerne|St. Gallen|Neuchâtel|Fribourg"
          "|Gland|Rolle|Epalinges|Nyon|Schaffhausen|Chur|Sion|Biel|Aarau|Olten|Thun|Renens|Ecublens|Morges"
          "|Vevey|Montreux|Yverdon-les-Bains|Schlieren|Dubendorf|Wallisellen|Opfikon|Kloten|Rotkreuz|Baar"
          "|Cham|Allschwil|Plan-les-Ouates|Meyrin|Carouge|Lancy",
    "ES": "Madrid|Barcelona|Valencia|Seville|Málaga|Bilbao|Zaragoza|Palma|Alicante|Murcia|Valladolid|Vigo"
          "|A Coruna|Gijon|Oviedo|Granada|San Sebastian|Pamplona|Santander|Las Palmas|Tarragona|Girona"
          "|Sant Cugat del Valles|Badalona|Terrassa|Sabadell|Salamanca|Vitoria-Gasteiz|Alcobendas|Getafe"
          "|Las Rozas|Tres Cantos|Pozuelo de Alarcon|Santiago de Compostela",
    "DE": "Berlin|Munich|Hamburg|Frankfurt|Cologne|Stuttgart|Düsseldorf|Leipzig|Dresden|Hanover|Nuremberg"
          "|Karlsruhe|Heidelberg|Mannheim|Bonn|Essen|Dortmund|Bremen|Aachen|Freiburg|Potsdam|Darmstadt"
          "|Munster|Augsburg|Ulm|Regensburg|Jena|Mainz|Wiesbaden|Kiel|Erlangen",
    "AT": "Vienna|Graz|Linz|Salzburg|Innsbruck",
    "FR": "Paris|Lyon|Marseille|Toulouse|Nice|Nantes|Bordeaux|Lille|Montpellier|Strasbourg|Rennes|Grenoble"
          "|Annecy|Sophia Antipolis|Saint-Mandé|Boulogne-Billancourt|Issy-les-Moulineaux|Levallois-Perret"
          "|Puteaux|Courbevoie|Bidart|Aix-en-Provence",
    "IT": "Milan|Rome|Turin|Bologna|Florence|Naples|Genoa|Padua|Verona|Venice|Trieste|Bari|Pisa",
    "NL": "Amsterdam|Rotterdam|The Hague|Utrecht|Eindhoven|Delft|Leiden|Groningen|Haarlem|Amstelveen"
          "|Hilversum|Nijmegen|Arnhem|Enschede|Tilburg|Breda|Maastricht",
    "BE": "Brussels|Antwerp|Ghent|Leuven|Liege|Mechelen|Namur",
    "IE": "Dublin|Cork|Galway|Limerick",
    "GB": "London|Manchester|Edinburgh|Glasgow|Bristol|Leeds|Oxford|Belfast|Liverpool|Sheffield|Nottingham"
          "|Reading|Brighton|Cardiff|Milton Keynes|Guildford",
    "PT": "Lisbon|Porto|Braga|Coimbra|Aveiro|Faro",
    "DK": "Copenhagen|Aarhus|Odense",
    "SE": "Stockholm|Gothenburg|Malmö|Uppsala|Lund|Linkoping",
    "NO": "Oslo|Bergen|Trondheim|Stavanger",
    "FI": "Helsinki|Espoo|Tampere|Oulu|Turku|Vantaa",
    "PL": "Warsaw|Krakow|Wroclaw|Gdansk|Poznan|Lodz|Katowice|Lublin|Gdynia",
    "CZ": "Prague|Brno|Ostrava",
    "SK": "Bratislava|Kosice",
    "HU": "Budapest|Debrecen",
    "RO": "Bucharest|Cluj-Napoca|Iasi|Timisoara|Brasov",
    "BG": "Sofia|Plovdiv|Varna",
    "GR": "Athens|Thessaloniki",
    "HR": "Zagreb",
    "LU": "Luxembourg",
    "SI": "Ljubljana",
    "EE": "Tallinn|Tartu",
    "LV": "Riga",
    "LT": "Vilnius|Kaunas",
    "CY": "Limassol|Nicosia|Larnaca",
    "MT": "Valletta|Sliema",
    "RS": "Belgrade|Novi Sad",
    "MK": "Skopje|Ohrid",
    "UA": "Kyiv|Lviv|Kharkiv",
    "TR": "Istanbul|Ankara|Izmir",
    "US": "New York|San Francisco|Los Angeles|Seattle|Boston|Chicago|Austin|Denver|Washington, D.C."
          "|Palo Alto|Mountain View|Menlo Park|Sunnyvale|San Jose|San Diego|Atlanta|Miami|Dallas|Houston"
          "|Philadelphia|Pittsburgh|Salt Lake City|Raleigh|Nashville|Phoenix|Minneapolis|Detroit|Honolulu"
          "|Redmond|Bellevue|Cupertino|Santa Clara|Oakland|Brooklyn",
    "CA": "Toronto|Montreal|Vancouver|Ottawa|Calgary|Quebec City|Edmonton",
    "MX": "Mexico City|Guadalajara|Monterrey",
    "BR": "São Paulo|Rio de Janeiro",
    "AR": "Buenos Aires",
    "CO": "Bogotá|Medellín",
    "IN": "Bengaluru|Mumbai|New Delhi|Delhi|Hyderabad|Pune|Chennai|Gurugram|Noida",
    "JP": "Tokyo|Osaka",
    "KR": "Seoul",
    "CN": "Shanghai|Beijing|Shenzhen|Chengdu",
    "HK": "Hong Kong",
    "TW": "Taipei",
    "SG": "Singapore",
    "AU": "Sydney|Melbourne|Brisbane",
    "NZ": "Auckland",
    "IL": "Tel Aviv",
    "AE": "Dubai|Abu Dhabi",
    "PH": "Manila",
}  # fmt: skip

# Other spellings, keyed like CITIES after fold().
CITY_ALIASES: dict[str, str] = {
    "zuerich": "Zurich", "geneve": "Geneva", "genf": "Geneva", "ginevra": "Geneva", "bale": "Basel",
    "berne": "Bern", "luzern": "Lucerne", "st gallen": "St. Gallen", "sankt gallen": "St. Gallen",
    "biel/bienne": "Biel", "bienne": "Biel", "yverdon": "Yverdon-les-Bains",
    "sevilla": "Seville", "la coruna": "A Coruna", "donostia": "San Sebastian", "palma de mallorca": "Palma",
    "sant cugat": "Sant Cugat del Valles", "vitoria": "Vitoria-Gasteiz",
    "munchen": "Munich", "muenchen": "Munich", "koln": "Cologne", "koeln": "Cologne",
    "duesseldorf": "Düsseldorf", "hannover": "Hanover", "nurnberg": "Nuremberg", "nuernberg": "Nuremberg",
    "frankfurt am main": "Frankfurt", "wien": "Vienna", "milano": "Milan", "roma": "Rome", "torino": "Turin",
    "firenze": "Florence", "napoli": "Naples", "genova": "Genoa", "padova": "Padua", "venezia": "Venice",
    "den haag": "The Hague", "bruxelles": "Brussels", "brussel": "Brussels", "antwerpen": "Antwerp",
    "gent": "Ghent", "lisboa": "Lisbon", "oporto": "Porto", "kobenhavn": "Copenhagen", "goteborg": "Gothenburg",
    "warszawa": "Warsaw", "cracow": "Krakow", "praha": "Prague", "bucuresti": "Bucharest", "cluj": "Cluj-Napoca",
    "athina": "Athens", "beograd": "Belgrade", "kiev": "Kyiv", "new york city": "New York", "nyc": "New York",
    "washington dc": "Washington, D.C.", "washington d.c.": "Washington, D.C.", "bangalore": "Bengaluru",
    "gurgaon": "Gurugram", "ciudad de mexico": "Mexico City", "tel aviv-yafo": "Tel Aviv",
}  # fmt: skip

REMOTE = re.compile(r"\b(remote|remoto|teletrabajo|home[- ]?office|work from home|anywhere|fully distributed)\b", re.I)
# Places in one location field: "Boston, MA; New York, NY", "London & San Francisco".
PLACE_SEPARATOR = re.compile(r"\s*(?:;|\||/| & | and | or |\n)\s*")
# Parts of one place: "Zurich, Zürich, Switzerland", "Remote - Spain".
PART_SEPARATOR = re.compile(r"\s*(?:,| - | – )\s*")


def fold(text: str) -> str:
    """Lowercase, without accents or extra spaces, for lookups."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


COUNTRY_BY_NAME = {name: iso for iso, names in COUNTRIES.items() for name in names.split("|")}
CITY_BY_KEY: dict[str, tuple[str, str]] = {
    fold(city): (city, iso) for iso, cities in CITIES.items() for city in cities.split("|")
}
for _alias, _city in CITY_ALIASES.items():
    CITY_BY_KEY[_alias] = CITY_BY_KEY[fold(_city)]


@dataclass(frozen=True)
class Place:
    city: str | None = None
    countries: tuple[str, ...] = ()
    remote: bool = False

    @property
    def country(self) -> str | None:
        return self.countries[0] if self.countries else None


def country_code(value: str | None) -> str | None:
    """ISO code from a source's country field: a code ("ch", "US") or a name ("Finland", "USA")."""
    if not value:
        return None
    key = fold(value)
    if len(key) == 2 and key.isalpha():
        return "GB" if key == "uk" else key.upper()
    return COUNTRY_BY_NAME.get(key)


def city_of(part: str) -> tuple[str, str] | None:
    """(city, country) for a known city, else None."""
    key = fold(re.sub(r"\(.*?\)", "", part))
    return CITY_BY_KEY.get(key) or CITY_BY_KEY.get(key.removesuffix(" city"))


def parse(location: str | None, country: str | None = None, known_cities_only: bool = False) -> Place:
    """City, countries and remote from a location text and an optional country field.

    ``known_cities_only``: take the city from the list above only. For text
    where the first part may be anything else, like an HN header ("Acme |
    Zurich | Onsite").
    """
    field_country = country_code(country)
    text = location or ""
    places = [p for p in PLACE_SEPARATOR.split(text) if p.strip()]
    countries: list[str] = [field_country] if field_country else []
    city: str | None = None
    for place in places:
        parts = [p for p in PART_SEPARATOR.split(place) if p.strip()]
        named = [COUNTRY_BY_NAME.get(fold(re.sub(r"\(.*?\)", "", p))) for p in parts]
        known = [city_of(p) for p in parts]
        if any(named):
            countries += [iso for iso in named if iso]
        elif field_country and len(places) == 1:
            pass  # the field already says where this place is
        else:
            countries += [found[1] for found in known if found]
        if city is None:
            city = next((found[0] for found in known if found), None)
        if city is None and not known_cities_only and len(parts) >= 2 and not REMOTE.search(place):
            first = re.sub(r"\(.*?\)", "", parts[0]).strip()
            if first and not named[0] and not first.isupper():
                city = first
    return Place(city, tuple(dict.fromkeys(countries)), bool(REMOTE.search(text)))
