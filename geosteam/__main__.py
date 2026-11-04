"""Start aplikacji: bez argumentów otwiera okno, z opcją --aktualizuj aktualizuje wszystkie źródła w konsoli."""
import sys

from . import aktualizacja, magazyn, raport


def main():
    if "--aktualizuj" in sys.argv:
        konfiguracja = magazyn.wczytaj_konfiguracje()
        ustawienia = magazyn.wczytaj_ustawienia()
        formaty = raport.FORMATY[ustawienia["format_raportu"]]
        aktualizacja.aktualizuj(
            konfiguracja, konfiguracja["zrodla"], lambda linia: print(linia, flush=True), formaty, ustawienia
        )
    else:
        from . import gui

        gui.uruchom()


if __name__ == "__main__":
    main()
