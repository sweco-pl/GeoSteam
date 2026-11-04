"""Porównanie obiektów warstwy przed i po pobraniu: bez zmian, zmienione, dodane, usunięte."""
import collections
import hashlib
import numbers

import pandas as pd
import shapely

# pola techniczne, których zmiana między pobraniami nie oznacza zmiany danych
POMIJANE_KOLUMNY = {"geometry", "data_pobrania", "godzina_pobrania", "fid", "gml_id", "id"}

# poniżej tej odległości (w jednostkach układu warstwy, dla EPSG:2180 to metry) uznajemy, że dodany/usunięty
# obiekt ma bliźniaczy odpowiednik po drugiej stronie - prawdopodobnie ta sama lokalizacja z geometrią zmienioną
# na tyle mocno (reprojekcja, przeliczenie przez źródło), że dopasowanie po skrócie geometrii się nie powiodło
PROG_PRZESUNIECIA_M = 1.0


def _tekst(wartosc):
    """Ujednolica wartość atrybutu przed haszowaniem, żeby sam format (a nie treść) nie dawał fałszywej zmiany:
    brak danych zawsze jako pusty tekst (None/NaN/<NA> bywają różne między GML a GeoPackage) oraz liczby zawsze
    jako float o stałej precyzji (int 2000 i float 2000.0 to ta sama wartość, ale inny tekst)."""
    if pd.isna(wartosc):
        return ""
    if isinstance(wartosc, numbers.Real) and not isinstance(wartosc, bool):
        return f"{float(wartosc):.6f}"
    return str(wartosc)


def _sygnatury(gdf, kolumny):
    geometrie = shapely.normalize(gdf.geometry.to_numpy())
    # pointwise: samo zaokrąglenie współrzędnych, bez operacji topologicznych (te zgłaszały TopologyException na niepoprawnych poligonach)
    wkb = shapely.to_wkb(shapely.set_precision(geometrie, 0.001, mode="pointwise"))  # zaokrąglenie do 1 mm
    # gdf[[]].itertuples(index=False) nie zwraca żadnych krotek niezależnie od liczby wierszy (pusty wybór
    # kolumn), dlatego przy braku kolumn do porównania (dopasowanie po samej geometrii) podstawiamy puste
    # krotki ręcznie, zamiast polegać na itertuples
    atrybuty = gdf[kolumny].itertuples(index=False) if kolumny else [()] * len(gdf)
    sygnatury = []
    for geometria, wiersz in zip(wkb, atrybuty):
        skrot = hashlib.sha1(geometria or b"")
        skrot.update("\x1f".join(_tekst(wartosc) for wartosc in wiersz).encode("utf-8"))
        sygnatury.append(skrot.hexdigest())
    return sygnatury


def _czytelnie(wartosc):
    """Wartość atrybutu do wyświetlenia w raporcie (brak danych jako pusty tekst, reszta bez zmian formatu)."""
    return "" if pd.isna(wartosc) else str(wartosc)


def _diagnoza_braku_pary(geometrie, geometrie_drugiej_strony, okreslenie_drugiej_strony):
    """Dla obiektów bez pary (dodane/usunięte) tłumaczy, dlaczego nie zostały uznane za 'zmienione':
    szuka najbliższej geometrii po drugiej stronie i na podstawie odległości ocenia, czy to raczej ten sam
    obiekt (geometria zmieniła się za bardzo, by dopasować ją po skrócie) czy faktycznie inna lokalizacja."""
    if len(geometrie) == 0:
        return []
    if len(geometrie_drugiej_strony) == 0:
        return [f"brak jakichkolwiek obiektów {okreslenie_drugiej_strony} do porównania"] * len(geometrie)
    drzewo = shapely.STRtree(geometrie_drugiej_strony)
    indeksy = drzewo.nearest(geometrie)
    odleglosci = shapely.distance(geometrie, geometrie_drugiej_strony[indeksy])
    opisy = []
    for odleglosc in odleglosci:
        if odleglosc <= PROG_PRZESUNIECIA_M:
            opisy.append(
                f"najbliższy obiekt {okreslenie_drugiej_strony} w odległości {odleglosc:.3f} m - "
                "prawdopodobnie ten sam obiekt z geometrią zmienioną na tyle, że nie dopasował się do pary"
            )
        else:
            opisy.append(
                f"najbliższy obiekt {okreslenie_drugiej_strony} w odległości {odleglosc:.1f} m - "
                "prawdopodobnie inna lokalizacja (nowy/usunięty obiekt, nie zmiana istniejącego)"
            )
    return opisy


def _opisz_zmiany(stara, nowa, kolumny, pary):
    """Dla par (indeks w starej, indeks w nowej) tego samego obiektu zwraca wiersze nowej wersji z dopisaną
    kolumną 'zmiana_atrybutow' wylistowującą, które konkretnie atrybuty i jak się zmieniły."""
    wiersze = []
    for i_stara, i_nowa in pary:
        wiersz_stara, wiersz_nowa = stara.iloc[i_stara], nowa.iloc[i_nowa]
        zmienione_kolumny = [
            kolumna for kolumna in kolumny if _tekst(wiersz_stara[kolumna]) != _tekst(wiersz_nowa[kolumna])
        ]
        wpis = wiersz_nowa.drop(labels="geometry").to_dict()
        wpis["zmiana_atrybutow"] = "; ".join(
            f"{kolumna}: {_czytelnie(wiersz_stara[kolumna])} -> {_czytelnie(wiersz_nowa[kolumna])}"
            for kolumna in zmienione_kolumny
        )
        wiersze.append(wpis)
    return pd.DataFrame(wiersze)


def porownaj(stara, nowa):
    """Porównuje obiekty starej i nowej wersji warstwy. stara=None oznacza pierwsze pobranie.

    Dopasowanie odbywa się po skrócie (geometria + atrybuty), żeby zmiana kolejności obiektów nie dawała
    fałszywych zmian. Obiekty, które nie znalazły pary po pełnym skrócie, ale mają identyczną geometrię co
    jakiś niesparowany obiekt z drugiej wersji, są traktowane jako ten sam obiekt ze zmienionymi atrybutami
    ("zmienione"), a nie jako przypadkowa para dodanie+usunięcie tej samej lokalizacji.

    Zwraca słownik z liczbami oraz obiektami zmienionymi, dodanymi i usuniętymi (GeoDataFrame).
    """
    if stara is None:
        return {"przed": None, "po": len(nowa), "bez_zmian": 0, "zmienione": None, "dodane": None, "usuniete": None}
    kolumny = sorted(
        k for k in nowa.columns if k in stara.columns and k.lower() not in POMIJANE_KOLUMNY
    )
    sig_stare = _sygnatury(stara, kolumny)
    sig_nowe = _sygnatury(nowa, kolumny)

    pozostale = collections.Counter(sig_stare)
    nowe_bez_pary = []
    for i, sygnatura in enumerate(sig_nowe):
        if pozostale[sygnatura] > 0:
            pozostale[sygnatura] -= 1
        else:
            nowe_bez_pary.append(i)

    pozostale = collections.Counter(sig_nowe)
    stare_bez_pary = []
    for i, sygnatura in enumerate(sig_stare):
        if pozostale[sygnatura] > 0:
            pozostale[sygnatura] -= 1
        else:
            stare_bez_pary.append(i)

    # spośród obiektów bez pary po pełnym skrócie: dopasowanie po samej geometrii (bez atrybutów)
    geom_stare = _sygnatury(stara, [])
    geom_nowe = _sygnatury(nowa, [])
    wedlug_geometrii = collections.defaultdict(list)
    for i in stare_bez_pary:
        wedlug_geometrii[geom_stare[i]].append(i)

    dodane, pary_zmienione = [], []
    for i in nowe_bez_pary:
        kandydaci = wedlug_geometrii.get(geom_nowe[i])
        if kandydaci:
            pary_zmienione.append((kandydaci.pop(0), i))
        else:
            dodane.append(i)
    usuniete = [i for indeksy in wedlug_geometrii.values() for i in indeksy]

    dodane_gdf = nowa.iloc[dodane].assign(
        diagnoza=_diagnoza_braku_pary(nowa.geometry.to_numpy()[dodane], stara.geometry.to_numpy()[usuniete], "usunięty")
    )
    usuniete_gdf = stara.iloc[usuniete].assign(
        diagnoza=_diagnoza_braku_pary(stara.geometry.to_numpy()[usuniete], nowa.geometry.to_numpy()[dodane], "dodany")
    )

    return {
        "przed": len(stara),
        "po": len(nowa),
        "bez_zmian": len(sig_nowe) - len(nowe_bez_pary),
        "zmienione": _opisz_zmiany(stara, nowa, kolumny, pary_zmienione),
        "dodane": dodane_gdf,
        "usuniete": usuniete_gdf,
    }
