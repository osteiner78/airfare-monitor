"""Airline name -> IATA code, shared by every layer that needs one identity
for one carrier.

Three consumers, deliberately in a leaf module with no project imports:
`fingerprint.py` (the flight_key identity), `pages.py`'s logo lookup, and
`pages.py`'s airline facet grouping. fingerprint.py cannot import pages.py,
and that import direction is part of why the identity and the facet
normalisations diverged (plan 024 phase 4).

Deliberately excludes generated labels like "Multiple airlines" (Kayak's own
placeholder for a multi-carrier self-transfer itinerary, not a bookable
airline) -- an unmapped name falls back to plain text for the logo and to a
casefolded identity for the key, which is the correct outcome for those.
"""

AIRLINE_NAME_TO_CODE: dict[str, str] = {
    "TAP AIR PORTUGAL": "TP",
    "TAP PORTUGAL": "TP",
    "AZUL": "AD",
    "AIR EUROPA": "UX",
    "ITA AIRWAYS": "AZ",
    "ITA": "AZ",
    "IBERIA": "IB",
    "ARAJET": "DM",
    "GOL": "G3",
    "LUFTHANSA": "LH",
    "AIR FRANCE": "AF",
    "KLM": "KL",
    "EMIRATES": "EK",
    "TURKISH AIRLINES": "TK",
    "UNITED": "UA",
    "UNITED AIRLINES": "UA",
    "AVIANCA": "AV",
    "SWISS": "LX",
    "BRITISH AIRWAYS": "BA",
    "DELTA": "DL",
    "DELTA AIR LINES": "DL",
    "AIR CANADA": "AC",
    "AEROMEXICO": "AM",
    "LATAM": "LA",
    "LATAM AIRLINES": "LA",
    "AMERICAN AIRLINES": "AA",
    "AMERICAN": "AA",
    "EASYJET": "U2",
    "VUELING": "VY",
    "RYANAIR": "FR",
    "NORWEGIAN": "DY",
    "NORWEGIAN AIR SHUTTLE": "DY",
    "FINNAIR": "AY",
    "AUSTRIAN": "OS",
    "AUSTRIAN AIRLINES": "OS",
    "BRUSSELS AIRLINES": "SN",
    "LOT POLISH AIRLINES": "LO",
    "COPA AIRLINES": "CM",
    "QATAR AIRWAYS": "QR",
    "ETIHAD AIRWAYS": "EY",
    "SINGAPORE AIRLINES": "SQ",
    "CATHAY PACIFIC": "CX",
    "ANA": "NH",
    "ALL NIPPON AIRWAYS": "NH",
    "JAPAN AIRLINES": "JL",
    "ALASKA AIRLINES": "AS",
    "JETBLUE": "B6",
    "SOUTHWEST": "WN",
    "WESTJET": "WS",
    "AIR INDIA": "AI",
    "ETHIOPIAN AIRLINES": "ET",
    "KENYA AIRWAYS": "KQ",
    "SOUTH AFRICAN AIRWAYS": "SA",
    "ROYAL AIR MAROC": "AT",
    "EGYPTAIR": "MS",
    "SAUDIA": "SV",
    "AEROFLOT": "SU",
    "WIZZ AIR": "W6",
    "VOLARIS": "Y4",
}
