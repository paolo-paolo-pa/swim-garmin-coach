"""Costruire HTML in modo che sfuggire il testo sia la cosa che succede da sola.

## Perché non un motore di template

Il secondo audit ha scartato Jinja2 (§4). Non per il peso — è un pacchetto
piccolo e ottimo — ma per la direzione del suo default: in Jinja l'escape è
automatico e *disattivarlo* costa sette caratteri, ``|safe``. Qui succede il
contrario: il testo è **sempre** sfuggito, e per emettere HTML grezzo bisogna
avvolgerlo in :class:`Raw`, che è una cosa che si vede leggendo il codice e che
si può cercare con grep.

Non è pedanteria. I nomi delle attività arrivano da Garmin, li scrive l'utente
o l'applicazione, e la Regola di sicurezza del progetto li dichiara **dato non
fidato**. Una seduta chiamata ``<script>`` non deve poter fare niente.

## Perché non c'è un file .html da nessuna parte

Le pagine sono funzioni Python che ricevono un ``InsightPacket`` già completo di
testi formattati e lo dispongono. Nessuna calcola: il test
``test_app_computes_nothing`` lo verifica leggendo l'albero sintattico e
fallendo se in questo pacchetto compare un'operazione aritmetica.

Un template che divide per mille per mostrare i chilometri è una formula in un
template, ed è il modo in cui due verità nascono senza che nessuno lo decida.
"""

from __future__ import annotations

from html import escape as _escape

# Elementi che non hanno tag di chiusura.
VOID = {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "source"}

# Attributi il cui nome Python non può essere quello HTML.
ATTRIBUTE_NAMES = {"class_": "class", "for_": "for", "id_": "id"}


class Raw(str):
    """Testo già sicuro, che non va sfuggito di nuovo.

    Esiste solo per essere raro e visibile. Ogni punto del codice che lo usa
    afferma «questo l'ho costruito io», e va letto come tale in revisione.
    """

    __slots__ = ()


def escape(value: object) -> Raw:
    """Qualunque cosa, resa innocua."""
    if isinstance(value, Raw):
        return value
    if value is None:
        return Raw("")
    return Raw(_escape(str(value), quote=True))


def _attributes(pairs: dict) -> str:
    parts = []
    for key, value in pairs.items():
        if value is None or value is False:
            continue
        name = ATTRIBUTE_NAMES.get(key, key.replace("_", "-"))
        if value is True:
            parts.append(f" {name}")
        else:
            parts.append(f' {name}="{_escape(str(value), quote=True)}"')
    return "".join(parts)


# Il nome dell'elemento e posizionale-solo (la barra): `name` e anche un
# attributo HTML vero, e senza la barra `tag("meta", name="viewport")` finirebbe
# per assegnare due volte lo stesso parametro.
def tag(_tag_name: str, /, *children: object, **attributes: object) -> Raw:
    """Un elemento. I figli di tipo ``str`` vengono sfuggiti, i ``Raw`` no."""
    inside = "".join(escape(child) for child in children if child is not None)
    opening = f"<{_tag_name}{_attributes(attributes)}>"
    if _tag_name in VOID:
        return Raw(opening)
    return Raw(f"{opening}{inside}</{_tag_name}>")


def _element(element_name: str):
    def build(*children: object, **attributes: object) -> Raw:
        return tag(element_name, *children, **attributes)
    build.__name__ = element_name
    return build


# Gli elementi che servono davvero. Se ne serve un altro, si aggiunge qui: la
# lista corta è un modo di accorgersi quando una pagina sta diventando densa.
a = _element("a")
article = _element("article")
button = _element("button")
details = _element("details")
div = _element("div")
form = _element("form")
h1, h2, h3 = _element("h1"), _element("h2"), _element("h3")
header = _element("header")
input_ = _element("input")
label = _element("label")
li = _element("li")
main = _element("main")
nav = _element("nav")
option = _element("option")
p = _element("p")
section = _element("section")
select = _element("select")
span = _element("span")
strong = _element("strong")
summary = _element("summary")
table, tbody, td, th, thead, tr = (_element(n) for n in
                                   ("table", "tbody", "td", "th", "thead", "tr"))
textarea = _element("textarea")
ul = _element("ul")


def join(pieces) -> Raw:
    """Più elementi in fila, senza un contenitore che non serve."""
    return Raw("".join(escape(piece) for piece in pieces))


def document(title: str, body: Raw, *, active: str = "", style: str = "",
             script: str = "", extra_areas: tuple = ()) -> Raw:
    """La pagina intera.

    ``lang="it"`` non è un dettaglio: senza, un lettore di schermo legge
    l'italiano con la pronuncia inglese.
    """
    return Raw(
        "<!doctype html>"
        + tag("html",
              tag("head",
                  tag("meta", charset="utf-8"),
                  tag("meta", name="viewport",
                      content="width=device-width, initial-scale=1"),
                  tag("title", f"{title} · Garmin Coach"),
                  tag("style", Raw(style)) if style else Raw("")),
              tag("body", _navigation(active, extra_areas), body,
                  tag("script", Raw(script)) if script else Raw("")),
              lang="it"))


AREAS = (
    ("/", "Oggi"),
    ("/settimana", "Settimana"),
    ("/sedute", "Sedute"),
    ("/progressi", "Progressi"),
    ("/gare", "Gare"),
    ("/chiedi", "Chiedi"),
)


def _navigation(active: str, extra_areas: tuple = ()) -> Raw:
    """Le sei aree. Impostazioni e profilo non sono una settima homepage.

    ``extra_areas`` esiste per una sola cosa: un'area che compare **quando c'è
    qualcosa da fare** e sparisce quando non c'è più. «Da decidere» senza dubbi
    aperti sarebbe una voce di menu che porta a una pagina vuota, e una voce di
    menu che porta a una pagina vuota insegna a non cliccarla.
    """
    return nav(
        join(a(name, href=href,
               class_="area attiva" if href == active else "area",
               aria_current="page" if href == active else None)
             for href, name in tuple(AREAS) + tuple(extra_areas)),
        aria_label="Aree del coach")
