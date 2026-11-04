"""Okno GeoSteam. Tkinter jest w standardowym instalatorze Pythona dla Windows, więc nie trzeba go dokładać."""
import datetime
import os
import queue
import re
import threading
import tkinter as tk
import webbrowser
from urllib.parse import urlsplit
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

from . import aktualizacja, eziudp, harmonogram, magazyn, raport, wfs

RODZAJE = ["wszystkie", "centralne", "wojewodztwa", "powiaty", "gminy"]
WSZYSTKIE_TEMATY = "wszystkie"
ETYKIETY_TEMATOW = {f"{kod} {nazwa}": kod for kod, nazwa in eziudp.TEMATY}
CO_MINUTE_SPRAWDZAJ_HARMONOGRAM = 60_000


def _format_czasu(iso):
    return datetime.datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M") if iso else "-"


class Aplikacja:
    def __init__(self, okno):
        self.okno = okno
        self.konfiguracja = magazyn.wczytaj_konfiguracje()
        self.ustawienia = magazyn.wczytaj_ustawienia()
        self.kolejka = queue.Queue()
        self.zajete = False
        self.zatrzymaj_aktualizacje = threading.Event()
        self.zbiory = []  # wyniki wyszukiwania w EZiUDP
        self.wybrany_zbior = None
        self.uslugi = []  # usługi WFS z warstwami wybranego zbioru (wynik wfs.dostepne_uslugi)
        self.warstwy_wfs = []  # (nazwa, tytuł) warstw wybranej usługi
        self.adres_wfs = None  # adres wybranej usługi WFS

        okno.title("GeoSteam")
        ikona = os.path.join(magazyn.KATALOG_ZASOBOW, "ikona.ico")
        if os.path.exists(ikona):
            okno.iconbitmap(ikona)
        okno.geometry("1000x920")
        self._zbuduj()
        self._odswiez_zrodla()
        self._odswiez_ustawienia()
        self._przetwarzaj_kolejke()
        self.okno.after(CO_MINUTE_SPRAWDZAJ_HARMONOGRAM, self._sprawdz_harmonogram)

    # --- budowa okna ---

    def _zbuduj(self):
        # cały panel w przewijanym płótnie, żeby na małym ekranie (np. w VM) było widać dół okna
        plotno = tk.Canvas(self.okno, highlightthickness=0)
        suwak = ttk.Scrollbar(self.okno, orient="vertical", command=plotno.yview)
        plotno.configure(yscrollcommand=suwak.set)
        suwak.pack(side="right", fill="y")
        plotno.pack(side="left", fill="both", expand=True)
        glowna = ttk.Frame(plotno, padding=8)
        okno_w_plotnie = plotno.create_window((0, 0), window=glowna, anchor="nw")
        self.plotno = plotno
        self.glowna = glowna
        self.okno_w_plotnie = okno_w_plotnie
        # treść ma wypełniać całą wysokość płótna, inaczej pod panelami zostaje puste miejsce,
        # w które suwak pozwala "zjechać" i przyciski zdają się oddalać w dół
        glowna.bind("<Configure>", self._dopasuj_plotno)
        plotno.bind("<Configure>", self._dopasuj_plotno)
        self.okno.bind_all("<MouseWheel>", self._przewin_kolkiem)
        self.okno.bind_all("<Button-4>", self._przewin_kolkiem)
        self.okno.bind_all("<Button-5>", self._przewin_kolkiem)
        karty = ttk.Notebook(glowna)
        karty.pack(fill="both", expand=True)
        pobieranie = ttk.Frame(karty, padding=6)
        ustawienia = ttk.Frame(karty, padding=6)
        karty.add(pobieranie, text="Pobieranie")
        karty.add(ustawienia, text="Ustawienia")
        self._sekcja_wlasnego(pobieranie)
        self._sekcja_szukania(pobieranie)
        self._sekcja_uslug(pobieranie)
        self._sekcja_zrodel(pobieranie)
        self._karta_ustawien(ustawienia)
        self._sekcja_dziennika(pobieranie)

    def _dopasuj_plotno(self, _zdarzenie=None):
        szerokosc = self.plotno.winfo_width()
        wysokosc = max(self.plotno.winfo_height(), self.glowna.winfo_reqheight())
        self.plotno.itemconfigure(self.okno_w_plotnie, width=szerokosc, height=wysokosc)
        self.plotno.configure(scrollregion=(0, 0, szerokosc, wysokosc))

    def _przewin_kolkiem(self, zdarzenie):
        # listy i tabele przewijają się same, więc kółko przewija cały panel tylko poza nimi
        pod_kursorem = self.okno.winfo_containing(zdarzenie.x_root, zdarzenie.y_root)
        if isinstance(pod_kursorem, (ttk.Treeview, tk.Listbox, tk.Text)):
            return
        if zdarzenie.num == 4:
            kierunek = -1
        elif zdarzenie.num == 5:
            kierunek = 1
        else:
            kierunek = -1 if zdarzenie.delta > 0 else 1
        self.plotno.yview_scroll(kierunek, "units")

    def _sekcja_szukania(self, rodzic):
        ramka = ttk.LabelFrame(rodzic, text="1. Wyszukaj zbiór w katalogu EZiUDP", padding=6)
        ramka.pack(fill="both", expand=True, pady=(0, 6))
        wiersz = ttk.Frame(ramka)
        wiersz.pack(fill="x")
        self.rodzaj = tk.StringVar(value="wszystkie")
        self.temat = tk.StringVar(value=WSZYSTKIE_TEMATY)
        self.teryt = tk.StringVar()
        self.nazwa_zbioru = tk.StringVar()
        ttk.Label(wiersz, text="Rodzaj:").pack(side="left")
        ttk.Combobox(wiersz, textvariable=self.rodzaj, values=RODZAJE, state="readonly", width=12).pack(side="left", padx=(4, 12))
        ttk.Label(wiersz, text="Temat:").pack(side="left")
        ttk.Combobox(
            wiersz, textvariable=self.temat, values=[WSZYSTKIE_TEMATY, *ETYKIETY_TEMATOW], state="readonly", width=28
        ).pack(side="left", padx=(4, 12))
        ttk.Label(wiersz, text="TERYT:").pack(side="left")
        ttk.Entry(wiersz, textvariable=self.teryt, width=10).pack(side="left", padx=(4, 12))
        ttk.Label(wiersz, text="Nazwa zbioru:").pack(side="left")
        ttk.Entry(wiersz, textvariable=self.nazwa_zbioru, width=32).pack(side="left", padx=(4, 12))
        ttk.Button(wiersz, text="Szukaj", command=self._szukaj).pack(side="left")
        self.tabela_zbiorow = self._tabela(
            ramka, [("idiip", "Identyfikator", 130), ("zbior", "Zbiór", 430), ("organ", "Organ", 320)], wysokosc=6
        )
        self.tabela_zbiorow.bind("<<TreeviewSelect>>", self._wybrano_zbior)

    def _sekcja_uslug(self, rodzic):
        ramka = ttk.LabelFrame(rodzic, text="2. Usługi WFS zbioru z warstwami do pobrania", padding=6)
        ramka.pack(fill="both", expand=True, pady=(0, 6))
        lewa = ttk.Frame(ramka)
        lewa.pack(side="left", fill="both", expand=True, padx=(0, 6))
        prawa = ttk.Frame(ramka)
        prawa.pack(side="left", fill="both", expand=True)
        ttk.Label(lewa, text="Usługi (tylko z dostępnymi warstwami):").pack(anchor="w")
        self.lista_uslug = self._lista(lewa, wysokosc=5, tryb="browse")
        self.lista_uslug.bind("<<ListboxSelect>>", self._wybrano_usluge)
        ttk.Label(prawa, text="Warstwy usługi (bez zaznaczenia - wszystkie):").pack(anchor="w")
        self.lista_warstw = self._lista(prawa, wysokosc=5, tryb="extended")
        ttk.Button(prawa, text="Dodaj do listy źródeł", command=self._dodaj_zrodlo).pack(anchor="w", pady=4)
        wiersz_scenariusza = ttk.Frame(prawa)
        wiersz_scenariusza.pack(anchor="w")
        ttk.Label(wiersz_scenariusza, text="Scenariusz:").pack(side="left")
        self.wybor_scen_dodaj = ttk.Combobox(wiersz_scenariusza, state="readonly", width=24)
        self.wybor_scen_dodaj.pack(side="left", padx=4)
        ttk.Button(wiersz_scenariusza, text="Dodaj do scenariusza", command=self._dodaj_do_scenariusza).pack(side="left")

    def _sekcja_wlasnego(self, rodzic):
        ramka = ttk.LabelFrame(rodzic, text="0. Własny WFS - adres usługi spoza katalogu EZiUDP", padding=6)
        ramka.pack(fill="x", pady=(0, 6))
        self.adres_wlasny = tk.StringVar()
        self.nazwa_wlasna = tk.StringVar()
        wiersz = ttk.Frame(ramka)
        wiersz.pack(fill="x")
        ttk.Label(wiersz, text="Adres WFS:").pack(side="left")
        ttk.Entry(wiersz, textvariable=self.adres_wlasny, width=70).pack(side="left", padx=4)
        ttk.Button(wiersz, text="Sprawdź usługę", command=self._sprawdz_wlasny_wfs).pack(side="left")
        wiersz_nazwy = ttk.Frame(ramka)
        wiersz_nazwy.pack(fill="x", pady=(4, 0))
        ttk.Label(wiersz_nazwy, text="Nazwa źródła:").pack(side="left")
        ttk.Entry(wiersz_nazwy, textvariable=self.nazwa_wlasna, width=50).pack(side="left", padx=4)
        ttk.Label(wiersz_nazwy, text="(po sprawdzeniu usługi warstwy pojawią się w sekcji 2)").pack(side="left")

    def _sekcja_zrodel(self, rodzic):
        ramka = ttk.LabelFrame(rodzic, text="3. Źródła i aktualizacja", padding=6)
        ramka.pack(fill="both", expand=True, pady=(0, 6))
        self.tabela_zrodel = self._tabela(
            ramka,
            [("nazwa", "Źródło", 380), ("plik", "Plik GeoPackage", 170), ("warstwy", "Warstwy", 80),
             ("aktualizacja", "Ostatnia aktualizacja", 150)],
            wysokosc=6,
            tryb="extended",
        )
        self.tabela_zrodel.bind("<Double-1>", self._zmien_nazwe_pliku)
        przyciski = ttk.Frame(ramka)
        przyciski.pack(fill="x", pady=4)
        ttk.Button(przyciski, text="Aktualizuj zaznaczone", command=self._aktualizuj_zaznaczone).pack(side="left")
        ttk.Button(przyciski, text="Aktualizuj wszystkie", command=self._aktualizuj_wszystkie).pack(side="left", padx=4)
        ttk.Button(przyciski, text="Usuń z listy", command=self._usun_zrodlo).pack(side="left")
        ttk.Button(przyciski, text="Zatrzymaj aktualizator", command=self._zatrzymaj_aktualizator).pack(side="left", padx=4)
        ttk.Button(przyciski, text="Otwórz folder danych", command=self._otworz_folder).pack(side="right")
        ttk.Label(ramka, text="Kliknij dwukrotnie nazwę pliku GeoPackage, aby ją zmienić.").pack(anchor="w")
        self.etykieta_folderu = ttk.Label(ramka, text="")
        self.etykieta_folderu.pack(anchor="w")

    def _karta_ustawien(self, rodzic):
        scenariusze = ttk.LabelFrame(rodzic, text="Scenariusze - jakie usługi pobierać i gdzie zapisywać", padding=6)
        scenariusze.pack(fill="x", pady=(0, 8))
        wiersz = ttk.Frame(scenariusze)
        wiersz.pack(fill="x")
        self.wybor_scenariusza = ttk.Combobox(wiersz, state="readonly", width=40)
        self.wybor_scenariusza.pack(side="left")
        ttk.Button(wiersz, text="Wczytaj wybrany", command=self._wczytaj_wybrany).pack(side="left", padx=4)
        ttk.Button(wiersz, text="Wczytaj z pliku...", command=self._wczytaj_z_pliku).pack(side="left")
        ttk.Button(wiersz, text="Zapisz bieżący jako scenariusz...", command=self._zapisz_scenariusz).pack(side="left", padx=4)
        ttk.Button(
            wiersz, text="Zapisz bieżący jako domyślny scenariusz", command=self._zapisz_jako_domyslny
        ).pack(side="left", padx=4)
        self.etykieta_scenariusza = ttk.Label(scenariusze, text="")
        self.etykieta_scenariusza.pack(anchor="w", pady=(6, 0))
        ttk.Button(scenariusze, text="Zmień folder danych...", command=self._zmien_folder).pack(anchor="w", pady=(6, 0))

        self.wersjonowanie = tk.BooleanVar()
        ttk.Checkbutton(
            scenariusze, text="Wersjonuj dane: zachowuj poprzednią wersję warstwy przy zmianach (domyślnie nadpisywanie)",
            variable=self.wersjonowanie, command=self._zapisz_wersjonowanie,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            scenariusze,
            text="Poprzednia wersja trafia do tego samego GeoPackage jako warstwa <nazwa>__<data>_<godzina pobrania>.",
        ).pack(anchor="w")

        raporty = ttk.LabelFrame(rodzic, text="Raporty z pobierania", padding=6)
        raporty.pack(fill="x", pady=(0, 8))
        wiersz_raportow = ttk.Frame(raporty)
        wiersz_raportow.pack(fill="x")
        ttk.Label(wiersz_raportow, text="Format:").pack(side="left")
        self.wybor_formatu = ttk.Combobox(wiersz_raportow, values=list(raport.FORMATY), state="readonly", width=14)
        self.wybor_formatu.pack(side="left", padx=4)
        self.wybor_formatu.bind("<<ComboboxSelected>>", self._zapisz_format_raportu)
        ttk.Button(wiersz_raportow, text="Otwórz folder raportów", command=self._otworz_raporty).pack(side="left", padx=8)
        ttk.Button(
            wiersz_raportow, text="Zmień folder zapisów raportów...", command=self._zmien_folder_raportow
        ).pack(side="left")
        self.etykieta_folderu_raportow = ttk.Label(raporty, text="")
        self.etykieta_folderu_raportow.pack(anchor="w", pady=(4, 0))
        ttk.Label(
            raporty,
            text="Raport: obiekty bez zmian, dodane i usunięte w każdej warstwie. W xlsx arkusz Zmiany ma "
                 "szczegóły, a kolumna Diagnoza tłumaczy dodane/usunięte (np. przesunięta geometria).",
        ).pack(anchor="w", pady=(4, 0))

        harm = ttk.LabelFrame(rodzic, text="Cykliczne pobieranie i aktualizacja", padding=6)
        harm.pack(fill="x")
        self.harm_wlaczony = tk.BooleanVar()
        self.harm_czeste = tk.BooleanVar()
        self.harm_wartosc = tk.StringVar()
        ttk.Checkbutton(
            harm, text="Aktualizuj automatycznie (działa, gdy program jest uruchomiony)", variable=self.harm_wlaczony,
        ).pack(anchor="w")
        ttk.Checkbutton(
            harm, text="Zezwól na aktualizację częstszą niż co godzinę (w minutach)",
            variable=self.harm_czeste, command=self._zmien_tryb_interwalu,
        ).pack(anchor="w")
        wiersz_interwalu = ttk.Frame(harm)
        wiersz_interwalu.pack(fill="x", pady=4)
        ttk.Label(wiersz_interwalu, text="Co:").pack(side="left")
        self.spinbox_interwalu = ttk.Spinbox(wiersz_interwalu, textvariable=self.harm_wartosc, width=6)
        self.spinbox_interwalu.pack(side="left", padx=4)
        self.etykieta_jednostki = ttk.Label(wiersz_interwalu, text="godzin")
        self.etykieta_jednostki.pack(side="left")
        ttk.Button(wiersz_interwalu, text="Zapisz ustawienia", command=self._zapisz_harmonogram).pack(side="left", padx=8)
        self.etykieta_harmonogramu = ttk.Label(harm, text="")
        self.etykieta_harmonogramu.pack(anchor="w")
        ttk.Label(
            harm, text="Uwaga: częste aktualizacje obciążają serwery usług. Ustaw interwał rzędu kilku godzin, jeśli to możliwe."
        ).pack(anchor="w")
        ttk.Label(
            harm, text="Bez okna: Harmonogram zadań Windows z poleceniem GeoSteam.exe --aktualizuj (w folderze programu)."
        ).pack(anchor="w", pady=(6, 0))

        info = ttk.LabelFrame(rodzic, text="Informacje o programie", padding=6)
        info.pack(fill="x", pady=(8, 0))
        ttk.Label(info, text="GeoSteam to narzędzie do automatycznej aktualizacji danych GIS wykorzystywanych w projektach na obszarze Polski z wykorzystaniem danych udostępnionych przez Główny Urząd Geodezji i Kartografii.").pack(anchor="w")
        self._wiersz_z_linkiem(info, "Źródło danych: Główny Urząd Geodezji i Kartografii - ", "Ewidencja Zbiorów Usług i Danych Przestrzennych", "https://integracja.gugik.gov.pl/eziudp/index.php?")
        ttk.Label(info, text="Wersja: 1.0.0").pack(anchor="w")
        ttk.Label(info, text="Autor: Łukasz Maćkiewicz, SWECO").pack(anchor="w")
        self._wiersz_z_linkiem(info, "Kontakt: ", "lukasz.mackiewicz@sweco.pl", "mailto:lukasz.mackiewicz@sweco.pl")
        self._wiersz_z_linkiem(info, "Repozytorium: ", "https://github.com/sweco-pl/GeoSteam", "https://github.com/sweco-pl/GeoSteam")
        self._wiersz_z_linkiem(info, "Zgłoś błąd: ", "https://github.com/sweco-pl/GeoSteam/issues", "https://github.com/sweco-pl/GeoSteam/issues")
        ttk.Label(info, text="Licencja: GPL-3.0").pack(anchor="w")
        
        faq = ttk.LabelFrame(rodzic, text="FAQ", padding=6)
        faq.pack(fill="x", pady=(8, 0))
        ttk.Label(faq, text="Najczęściej zadawane pytania dotyczące programu GeoSteam.").pack(anchor="w")
        ttk.Label(faq, text="1. Jak często aktualizować dane?").pack(anchor="w", pady=(4, 0))
        ttk.Label(faq, text="   Zaleca się ustawienie interwału rzędu kilku godzin, aby nie obciążać serwerów usług.").pack(anchor="w")
        ttk.Label(faq, text="2. Jak uruchomić aktualizację bez okna programu?").pack(anchor="w", pady=(4, 0))
        ttk.Label(faq, text="   Użyj Harmonogramu zadań Windows z poleceniem GeoSteam.exe --aktualizuj w folderze programu.").pack(anchor="w")
        ttk.Label(faq, text="3. Jak zgłosić błąd w programie?").pack(anchor="w", pady=(4, 0))
        ttk.Label(faq, text="   Użyj sekcji 'Zgłoś błąd' w repozytorium GitHub programu GeoSteam.").pack(anchor="w")

    def _wiersz_z_linkiem(self, rodzic, etykieta, tekst_linku, url=None):
        wiersz = ttk.Frame(rodzic)
        wiersz.pack(anchor="w")
        ttk.Label(wiersz, text=etykieta).pack(side="left")
        link = tk.Label(wiersz, text=tekst_linku, fg="blue", cursor="hand2")
        czcionka = tkfont.Font(link, link.cget("font"))
        czcionka.configure(underline=True)
        link.configure(font=czcionka)
        link.pack(side="left")
        link.bind("<Button-1>", lambda _zdarzenie: webbrowser.open(url or tekst_linku))

    def _sekcja_dziennika(self, rodzic):
        ramka = ttk.LabelFrame(rodzic, text="Dziennik", padding=6)
        ramka.pack(fill="both", expand=True)
        obszar = ttk.Frame(ramka)
        obszar.pack(fill="both", expand=True)
        self.dziennik = tk.Text(obszar, height=10, wrap="word", state="disabled")
        przewijanie = ttk.Scrollbar(obszar, orient="vertical", command=self.dziennik.yview)
        self.dziennik.configure(yscrollcommand=przewijanie.set)
        self.dziennik.pack(side="left", fill="both", expand=True)
        przewijanie.pack(side="right", fill="y")

    def _tabela(self, rodzic, kolumny, wysokosc, tryb="browse"):
        ramka = ttk.Frame(rodzic)
        ramka.pack(fill="both", expand=True, pady=4)
        tabela = ttk.Treeview(
            ramka, columns=[id_ for id_, _, _ in kolumny], show="headings", height=wysokosc, selectmode=tryb
        )
        for id_, naglowek, szerokosc in kolumny:
            tabela.heading(id_, text=naglowek)
            tabela.column(id_, width=szerokosc)
        przewijanie = ttk.Scrollbar(ramka, orient="vertical", command=tabela.yview)
        tabela.configure(yscrollcommand=przewijanie.set)
        tabela.pack(side="left", fill="both", expand=True)
        przewijanie.pack(side="right", fill="y")
        return tabela

    def _lista(self, rodzic, wysokosc, tryb):
        ramka = ttk.Frame(rodzic)
        ramka.pack(fill="both", expand=True)
        lista = tk.Listbox(ramka, height=wysokosc, selectmode=tryb, exportselection=False)
        przewijanie = ttk.Scrollbar(ramka, orient="vertical", command=lista.yview)
        lista.configure(yscrollcommand=przewijanie.set)
        lista.pack(side="left", fill="both", expand=True)
        przewijanie.pack(side="right", fill="y")
        return lista

    # --- praca w tle i dziennik ---

    def _dopisz(self, linia):
        self.dziennik.configure(state="normal")
        self.dziennik.insert("end", linia + "\n")
        self.dziennik.see("end")
        self.dziennik.configure(state="disabled")

    def _log_z_watku(self, linia):
        self.kolejka.put(lambda: self._dopisz(linia))

    def _przetwarzaj_kolejke(self):
        # Tkinter nie jest bezpieczny wątkowo, więc wątki tylko wkładają funkcje do kolejki
        try:
            while True:
                self.kolejka.get_nowait()()
        except queue.Empty:
            pass
        self.okno.after(100, self._przetwarzaj_kolejke)

    def _uruchom(self, praca, po_zakonczeniu=None):
        if not self._czy_wolne():
            return
        self.zajete = True

        def watek():
            try:
                wynik = praca()
            except Exception as blad:
                wynik = blad
            self.kolejka.put(lambda: self._zakoncz(wynik, po_zakonczeniu))

        threading.Thread(target=watek, daemon=True).start()

    def _czy_wolne(self):
        if self.zajete:
            messagebox.showinfo("GeoSteam", "Trwa inna operacja, poczekaj na jej zakończenie.")
            return False
        return True

    def _zakoncz(self, wynik, po_zakonczeniu):
        self.zajete = False
        if isinstance(wynik, Exception):
            self._dopisz(f"[BŁĄD] {wynik}")
            messagebox.showerror("Błąd", str(wynik))
        elif po_zakonczeniu:
            po_zakonczeniu(wynik)

    # --- wyszukiwanie w EZiUDP ---

    def _szukaj(self):
        rodzaj = "" if self.rodzaj.get() == "wszystkie" else self.rodzaj.get()
        temat = ETYKIETY_TEMATOW.get(self.temat.get(), "")
        teryt, nazwa = self.teryt.get().strip(), self.nazwa_zbioru.get().strip()
        self._uruchom(lambda: eziudp.szukaj_zbiorow(rodzaj, teryt, nazwa, temat), self._pokaz_zbiory)

    def _pokaz_zbiory(self, zbiory):
        self.zbiory = zbiory
        self.tabela_zbiorow.delete(*self.tabela_zbiorow.get_children())
        for i, zbior in enumerate(zbiory):
            self.tabela_zbiorow.insert("", "end", iid=str(i), values=(zbior["idiip"], zbior["zbior"], zbior["organ"]))
        self._dopisz(f"Znaleziono zbiorów z usługą pobierania: {len(zbiory)}")

    def _wybrano_zbior(self, _zdarzenie):
        zaznaczone = self.tabela_zbiorow.selection()
        if not zaznaczone:
            return
        self.wybrany_zbior = self.zbiory[int(zaznaczone[0])]
        self.uslugi = []
        self.warstwy_wfs = []
        self.adres_wfs = None
        self.lista_uslug.delete(0, "end")
        self.lista_warstw.delete(0, "end")
        adresy = [eziudp.oczysc_adres(a) for a in self.wybrany_zbior["uslugi"]["pobierania"]]
        self._dopisz(f"Sprawdzam usługi zbioru ({len(adresy)})...")
        self._uruchom(lambda: wfs.dostepne_uslugi(adresy, self._log_z_watku), self._pokaz_uslugi)

    def _pokaz_uslugi(self, uslugi):
        self.uslugi = uslugi
        self.lista_uslug.delete(0, "end")
        for usluga in uslugi:
            self.lista_uslug.insert("end", f"{usluga['adres']}  [{len(usluga['warstwy'])} warstw, WFS {usluga['wersja']}]")
        if not uslugi:
            self._dopisz("Ten zbiór nie ma usług WFS z warstwami do pobrania.")

    def _wybrano_usluge(self, _zdarzenie):
        wybrane = self.lista_uslug.curselection()
        if not wybrane:
            return
        usluga = self.uslugi[wybrane[0]]
        self.adres_wfs = usluga["adres"]
        self.warstwy_wfs = usluga["warstwy"]
        self.lista_warstw.delete(0, "end")
        for nazwa, tytul in self.warstwy_wfs:
            self.lista_warstw.insert("end", f"{nazwa}  ({tytul})")

    def _sprawdz_wlasny_wfs(self):
        adres = eziudp.oczysc_adres(self.adres_wlasny.get().strip())
        if not adres:
            messagebox.showinfo("Własny WFS", "Wpisz adres usługi WFS.")
            return
        self._uruchom(
            lambda: wfs.pobierz_capabilities(adres, self._log_z_watku),
            lambda wynik: self._pokaz_wlasny_wfs(adres, wynik),
        )

    def _pokaz_wlasny_wfs(self, adres, wynik):
        wersja, warstwy = wynik
        if not warstwy:
            messagebox.showinfo("Własny WFS", "Usługa odpowiada, ale nie zgłasza żadnych warstw.")
            return
        self.wybrany_zbior = None  # źródło pochodzi z adresu, nie z katalogu EZiUDP
        self.uslugi = [{"adres": adres, "wersja": wersja, "warstwy": warstwy}]
        self.lista_uslug.delete(0, "end")
        self.lista_uslug.insert("end", f"{adres}  [{len(warstwy)} warstw, WFS {wersja}]")
        self.lista_uslug.selection_set(0)
        self._wybrano_usluge(None)
        if not self.nazwa_wlasna.get().strip():
            self.nazwa_wlasna.set(urlsplit(adres).netloc)
        self._dopisz(f"Własny WFS: {adres} ({len(warstwy)} warstw, WFS {wersja})")

    def _zbuduj_zrodlo(self):
        if self.adres_wfs is None:
            messagebox.showinfo("Dodawanie", "Wybierz usługę WFS z listy albo sprawdź własny adres.")
            return None
        warstwy = [self.warstwy_wfs[i][0] for i in self.lista_warstw.curselection()]
        if not warstwy and not messagebox.askyesno("Dodawanie", "Nie zaznaczono warstw. Dodać wszystkie warstwy usługi?"):
            return None
        if self.wybrany_zbior is not None:
            nazwa = self.wybrany_zbior["zbior"]
            plik = self.wybrany_zbior["idiip"].replace(".", "_") + ".gpkg"
        else:
            nazwa = self.nazwa_wlasna.get().strip() or self.adres_wfs
            plik = re.sub(r"[^\w\-]+", "_", nazwa).strip("_")[:80] + ".gpkg"
        return {
            "nazwa": nazwa,
            "wfs_url": self.adres_wfs,
            "plik": plik,
            "warstwy": warstwy,
            "ostatnia_aktualizacja": None,
        }

    def _dodaj_zrodlo(self):
        zrodlo = self._zbuduj_zrodlo()
        if zrodlo is None:
            return
        if any(z["wfs_url"] == zrodlo["wfs_url"] and z["warstwy"] == zrodlo["warstwy"] for z in self.konfiguracja["zrodla"]):
            messagebox.showinfo("Dodawanie", "To samo źródło jest już na liście.")
            return
        self.konfiguracja["zrodla"].append(zrodlo)
        magazyn.zapisz_konfiguracje(self.konfiguracja)
        self._odswiez_zrodla()
        self._dopisz(f"Dodano źródło: {zrodlo['nazwa']} ({len(zrodlo['warstwy']) or 'wszystkie'} warstw)")

    def _dodaj_do_scenariusza(self):
        nazwa_scenariusza = self.wybor_scen_dodaj.get()
        if not nazwa_scenariusza:
            messagebox.showinfo("Dodawanie", "Wybierz scenariusz z listy (zakładka Ustawienia).")
            return
        zrodlo = self._zbuduj_zrodlo()
        if zrodlo is None:
            return
        try:
            magazyn.dodaj_zrodlo_do_scenariusza(nazwa_scenariusza, zrodlo)
        except (OSError, ValueError) as blad:
            messagebox.showerror("Dodawanie", str(blad))
            return
        self._dopisz(f"Dodano źródło {zrodlo['nazwa']} do scenariusza {nazwa_scenariusza}")

    # --- źródła i aktualizacja ---

    def _odswiez_zrodla(self):
        self.tabela_zrodel.delete(*self.tabela_zrodel.get_children())
        for i, zrodlo in enumerate(self.konfiguracja["zrodla"]):
            self.tabela_zrodel.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    zrodlo["nazwa"],
                    zrodlo["plik"],
                    len(zrodlo["warstwy"]) or "wszystkie",
                    zrodlo["ostatnia_aktualizacja"] or "-",
                ),
            )
        self.etykieta_folderu.configure(text=f"Folder danych: {magazyn.folder_danych(self.konfiguracja)}")

    def _aktualizuj_zaznaczone(self):
        zaznaczone = self.tabela_zrodel.selection()
        if not zaznaczone:
            messagebox.showinfo("Aktualizacja", "Zaznacz źródła na liście.")
            return
        self._aktualizuj([self.konfiguracja["zrodla"][int(i)] for i in zaznaczone])

    def _aktualizuj_wszystkie(self):
        self._aktualizuj(self.konfiguracja["zrodla"])

    def _aktualizuj(self, zrodla):
        if not zrodla:
            messagebox.showinfo("Aktualizacja", "Lista źródeł jest pusta.")
            return
        formaty = raport.FORMATY[self.ustawienia["format_raportu"]]
        self.zatrzymaj_aktualizacje.clear()
        self._uruchom(
            lambda: aktualizacja.aktualizuj(
                self.konfiguracja, zrodla, self._log_z_watku, formaty, self.ustawienia,
                self.zatrzymaj_aktualizacje.is_set,
            ),
            lambda _sciezki: self._zakoncz_aktualizacje(),
        )

    def _zatrzymaj_aktualizator(self):
        if not self.zajete:
            messagebox.showinfo("Aktualizacja", "Aktualizator nie jest obecnie uruchomiony.")
            return
        self.zatrzymaj_aktualizacje.set()
        self._dopisz("Zatrzymywanie aktualizatora...")

    def _zakoncz_aktualizacje(self):
        self.zatrzymaj_aktualizacje.clear()
        self._odswiez_zrodla()
        self._odswiez_harmonogram_etykiete()
        self._dopisz("Gotowe.")

    def _zapisz_format_raportu(self, _zdarzenie):
        self.ustawienia["format_raportu"] = self.wybor_formatu.get()
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._dopisz(f"Format raportów: {self.ustawienia['format_raportu']}")

    def _otworz_raporty(self):
        folder = magazyn.folder_raportow(self.ustawienia)
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)  # aplikacja jest przeznaczona dla Windows

    def _zmien_folder_raportow(self):
        wybrany = filedialog.askdirectory(initialdir=magazyn.folder_raportow(self.ustawienia))
        if wybrany:
            self.ustawienia["folder_raportow"] = os.path.normpath(wybrany)
            magazyn.zapisz_ustawienia(self.ustawienia)
            self._odswiez_folder_raportow()
            self._dopisz(f"Folder raportów: {self.ustawienia['folder_raportow']}")

    def _odswiez_folder_raportow(self):
        self.etykieta_folderu_raportow.configure(text=f"Raporty zapisywane w: {magazyn.folder_raportow(self.ustawienia)}")

    def _zapisz_wersjonowanie(self):
        self.ustawienia["wersjonowanie_danych"] = self.wersjonowanie.get()
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._dopisz("Wersjonowanie danych: " + ("włączone" if self.wersjonowanie.get() else "wyłączone (nadpisywanie)"))

    def _usun_zrodlo(self):
        zaznaczone = self.tabela_zrodel.selection()
        if not zaznaczone:
            return
        if not messagebox.askyesno("Usuwanie", "Usunąć zaznaczone źródła z listy?\nPliki GeoPackage zostaną na dysku."):
            return
        for i in sorted((int(i) for i in zaznaczone), reverse=True):
            del self.konfiguracja["zrodla"][i]
        magazyn.zapisz_konfiguracje(self.konfiguracja)
        self._odswiez_zrodla()

    def _zmien_nazwe_pliku(self, zdarzenie):
        if self.tabela_zrodel.identify_region(zdarzenie.x, zdarzenie.y) != "cell":
            return
        if self.tabela_zrodel.identify_column(zdarzenie.x) != "#2":
            return
        iid = self.tabela_zrodel.identify_row(zdarzenie.y)
        if not iid:
            return
        zrodlo = self.konfiguracja["zrodla"][int(iid)]
        nowa_nazwa = simpledialog.askstring(
            "Zmiana nazwy pliku GeoPackage", "Nowa nazwa pliku:", initialvalue=zrodlo["plik"], parent=self.okno,
        )
        if nowa_nazwa is None:
            return
        nowa_nazwa = nowa_nazwa.strip()
        if not nowa_nazwa:
            return
        if not nowa_nazwa.lower().endswith(".gpkg"):
            nowa_nazwa += ".gpkg"
        if nowa_nazwa == zrodlo["plik"]:
            return
        if any(z is not zrodlo and z["plik"] == nowa_nazwa for z in self.konfiguracja["zrodla"]):
            messagebox.showerror("Zmiana nazwy", "Taka nazwa pliku jest już używana przez inne źródło.")
            return
        folder = magazyn.folder_danych(self.konfiguracja)
        stara_sciezka = os.path.join(folder, zrodlo["plik"])
        nowa_sciezka = os.path.join(folder, nowa_nazwa)
        if os.path.exists(stara_sciezka):
            if os.path.exists(nowa_sciezka):
                messagebox.showerror("Zmiana nazwy", "Plik o takiej nazwie już istnieje w folderze danych.")
                return
            try:
                os.rename(stara_sciezka, nowa_sciezka)
            except OSError as blad:
                messagebox.showerror("Zmiana nazwy", f"Nie udało się zmienić nazwy pliku: {blad}")
                return
        zrodlo["plik"] = nowa_nazwa
        magazyn.zapisz_konfiguracje(self.konfiguracja)
        self._odswiez_zrodla()
        self._dopisz(f"Zmieniono nazwę pliku GeoPackage źródła {zrodlo['nazwa']} na {nowa_nazwa}")

    def _zmien_folder(self):
        if not self._czy_wolne():
            return
        wybrany = filedialog.askdirectory(initialdir=magazyn.folder_danych(self.konfiguracja))
        if wybrany:
            self.konfiguracja["folder_danych"] = wybrany
            magazyn.zapisz_konfiguracje(self.konfiguracja)
            self._odswiez_zrodla()

    def _otworz_folder(self):
        folder = magazyn.folder_danych(self.konfiguracja)
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)  # aplikacja jest przeznaczona dla Windows

    # --- ustawienia: scenariusze ---

    def _odswiez_ustawienia(self):
        nazwy = magazyn.lista_scenariuszy()
        self.wybor_scenariusza.configure(values=nazwy)
        self.wybor_scen_dodaj.configure(values=nazwy)
        aktywny = self.ustawienia["aktywny_scenariusz"]
        if aktywny in nazwy:
            self.wybor_scenariusza.set(aktywny)
        self.etykieta_scenariusza.configure(text=f"Aktywny scenariusz: {aktywny or 'brak (lista z zrodla.json)'}")
        self.wybor_formatu.set(self.ustawienia["format_raportu"])
        self.wersjonowanie.set(self.ustawienia["wersjonowanie_danych"])
        self._odswiez_folder_raportow()
        h = self.ustawienia["harmonogram"]
        self.harm_wlaczony.set(h["wlaczony"])
        czeste = h["co_minut"] < 60
        self.harm_czeste.set(czeste)
        self._ustaw_tryb_interwalu(czeste)
        self.harm_wartosc.set(str(h["co_minut"] if czeste else h["co_minut"] // 60))
        self._odswiez_harmonogram_etykiete()

    def _wczytaj_wybrany(self):
        nazwa = self.wybor_scenariusza.get()
        if not nazwa:
            messagebox.showinfo("Scenariusze", "Wybierz scenariusz z listy.")
            return
        self._wczytaj_scenariusz(magazyn.sciezka_scenariusza(nazwa), nazwa)

    def _wczytaj_z_pliku(self):
        sciezka = filedialog.askopenfilename(title="Wczytaj scenariusz", filetypes=[("Scenariusz GeoSteam", "*.json")])
        if sciezka:
            self._wczytaj_scenariusz(sciezka, os.path.splitext(os.path.basename(sciezka))[0])

    def _wczytaj_scenariusz(self, sciezka, nazwa):
        if not self._czy_wolne():
            return
        if not messagebox.askyesno(
            "Scenariusze", f"Wczytać scenariusz „{nazwa}”?\nZastąpi on bieżącą listę źródeł i folder danych."
        ):
            return
        try:
            self.konfiguracja = magazyn.wczytaj_scenariusz(sciezka)
        except (OSError, ValueError) as blad:
            messagebox.showerror("Scenariusze", f"Nie udało się wczytać scenariusza: {blad}")
            return
        self.ustawienia["aktywny_scenariusz"] = nazwa
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._odswiez_zrodla()
        self._odswiez_ustawienia()
        self._dopisz(
            f"Wczytano scenariusz: {nazwa} (źródeł: {len(self.konfiguracja['zrodla'])}, "
            f"folder: {self.konfiguracja['folder_danych']})"
        )

    def _zapisz_scenariusz(self):
        if not self._czy_wolne():
            return
        nazwa = simpledialog.askstring("Scenariusze", "Nazwa scenariusza:", parent=self.okno)
        if not nazwa:
            return
        try:
            try:
                nazwa = magazyn.zapisz_scenariusz(nazwa, self.konfiguracja)
            except FileExistsError:
                if not messagebox.askyesno("Scenariusze", f"Scenariusz „{nazwa}” już istnieje. Nadpisać?"):
                    return
                nazwa = magazyn.zapisz_scenariusz(nazwa, self.konfiguracja, nadpisz=True)
        except ValueError as blad:
            messagebox.showerror("Scenariusze", str(blad))
            return
        self.ustawienia["aktywny_scenariusz"] = nazwa
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._odswiez_ustawienia()
        self._dopisz(f"Zapisano scenariusz: {nazwa}")

    def _zapisz_jako_domyslny(self):
        if not self._czy_wolne():
            return
        if not messagebox.askyesno(
            "Scenariusze", "Zapisać bieżącą listę źródeł i folder danych jako scenariusz „domyslny”?\n"
            "Nadpisze on istniejący scenariusz domyślny."
        ):
            return
        try:
            nazwa = magazyn.zapisz_scenariusz("domyslny", self.konfiguracja, nadpisz=True)
        except ValueError as blad:
            messagebox.showerror("Scenariusze", str(blad))
            return
        self.ustawienia["aktywny_scenariusz"] = nazwa
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._odswiez_ustawienia()
        self._dopisz(f"Zapisano scenariusz: {nazwa} (domyślny)")

    # --- ustawienia: harmonogram ---

    def _odswiez_harmonogram_etykiete(self):
        h = self.ustawienia["harmonogram"]
        if not h["wlaczony"]:
            tekst = "Cykliczna aktualizacja wyłączona."
        else:
            nastepne = harmonogram.nastepne_uruchomienie(h)
            nastepne_tekst = nastepne.strftime("%Y-%m-%d %H:%M") if nastepne else "przy najbliższym sprawdzeniu"
            tekst = f"Ostatnia automatyczna aktualizacja: {_format_czasu(h['ostatnie_uruchomienie'])} | następna: {nastepne_tekst}"
        self.etykieta_harmonogramu.configure(text=tekst)

    def _ustaw_tryb_interwalu(self, czeste):
        if czeste:
            self.spinbox_interwalu.configure(from_=1, to=59)
            self.etykieta_jednostki.configure(text="minut")
        else:
            self.spinbox_interwalu.configure(from_=1, to=720)
            self.etykieta_jednostki.configure(text="godzin")

    def _zmien_tryb_interwalu(self):
        czeste = self.harm_czeste.get()
        self._ustaw_tryb_interwalu(czeste)
        self.harm_wartosc.set("15" if czeste else "24")

    def _zapisz_harmonogram(self):
        czeste = self.harm_czeste.get()
        najwieksza = 59 if czeste else 720
        try:
            wartosc = int(self.harm_wartosc.get())
        except ValueError:
            wartosc = 0
        if not 1 <= wartosc <= najwieksza:
            messagebox.showerror("Ustawienia", f"Podaj liczbę od 1 do {najwieksza} {'minut' if czeste else 'godzin'}.")
            return
        h = self.ustawienia["harmonogram"]
        wlaczony = self.harm_wlaczony.get()
        if wlaczony and not h["wlaczony"]:
            # po włączeniu pierwsza automatyczna aktualizacja dopiero po pełnym odstępie
            h["ostatnie_uruchomienie"] = datetime.datetime.now().isoformat(timespec="minutes")
        h["wlaczony"] = wlaczony
        h["co_minut"] = wartosc if czeste else wartosc * 60
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._odswiez_harmonogram_etykiete()
        stan = f"włączony, co {wartosc} {'min' if czeste else 'h'}" if wlaczony else "wyłączony"
        self._dopisz(f"Zapisano harmonogram: {stan}")

    def _sprawdz_harmonogram(self):
        try:
            if not self.zajete and self.konfiguracja["zrodla"] and harmonogram.czy_pora(
                self.ustawienia["harmonogram"], datetime.datetime.now()
            ):
                self._uruchom_harmonogram()
        finally:
            self.okno.after(CO_MINUTE_SPRAWDZAJ_HARMONOGRAM, self._sprawdz_harmonogram)

    def _uruchom_harmonogram(self):
        h = self.ustawienia["harmonogram"]
        h["ostatnie_uruchomienie"] = datetime.datetime.now().isoformat(timespec="minutes")
        magazyn.zapisz_ustawienia(self.ustawienia)
        self._dopisz("Harmonogram: automatyczna aktualizacja wszystkich źródeł")
        self._aktualizuj(self.konfiguracja["zrodla"])
        self._odswiez_harmonogram_etykiete()


def uruchom():
    okno = tk.Tk()
    Aplikacja(okno)
    okno.mainloop()
