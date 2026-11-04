# GeoSteam

[![CI](https://github.com/sweco-pl/GeoSteam/actions/workflows/ci.yml/badge.svg)](https://github.com/sweco-pl/GeoSteam/actions/workflows/ci.yml)
[![Build Windows exe](https://github.com/sweco-pl/GeoSteam/actions/workflows/build-windows-exe.yml/badge.svg)](https://github.com/sweco-pl/GeoSteam/actions/workflows/build-windows-exe.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

**GeoSteam** to desktopowa aplikacja (GUI + tryb konsolowy) do automatycznej aktualizacji warstw danych przestrzennych pobieranych z usług WFS wskazanych w ewidencji zbiorów i usług danych przestrzennych (EZiUDP, GUGiK).

## Opis projektu

Aplikacja pozwala:
- wyszukiwać zbiory danych i usługi WFS w katalogu EZiUDP,
- pobierać i aktualizować wybrane warstwy do lokalnych plików GeoPackage,
- porównywać nowe dane z wcześniej pobranymi i generować raport zmian,
- tworzyć scenariusze, czyli listy źródeł i warstw, które można aktualizować,
- uruchamiać aktualizacje cyklicznie według harmonogramu,
- działać zarówno z poziomu GUI (Tkinter), jak i w trybie konsolowym (`--aktualizuj`), np. z zaplanowanego zadania Windows.

Projekt jest rozwijany jako open source na licencji GPLv3.

## Wymagania

- Python 3.11+
- Zależności z `requirements.txt` (m.in. `geopandas`, `pyogrio`, `requests`, `openpyxl`)

## Pobierz gotową wersję (Windows)

Najprościej pobrać gotowy build z zakładki **[Releases](https://github.com/sweco-pl/GeoSteam/releases)**:
- `GeoSteam-windows.zip` — rozpakuj i uruchom `GeoSteam.exe`, nie wymaga instalacji Pythona,
- `GeoSteam-Setup-*.msi` — instalator Windows (WiX),
- `GeoSteam-zrodla-bat.zip` — kod źródłowy + skrypty `uruchom.bat`/`aktualizuj.bat`, jeśli wolisz uruchamiać z Pythona.

## Instalacja i uruchomienie (źródła)

```bash
git clone https://github.com/sweco-pl/GeoSteam.git
cd GeoSteam
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m geosteam              # uruchamia GUI
python -m geosteam --aktualizuj # aktualizuje wszystkie skonfigurowane źródła w konsoli
```

Konfiguracja źródeł znajduje się w pliku `zrodla.json` (tworzonym/edytowanym też z poziomu GUI).

## Windows: gotowe skrypty i build .exe/.msi

- `uruchom.bat` — tworzy lokalne `.venv` i instaluje zależności.
- `aktualizuj.bat` — uruchamia aktualizację w konsoli (do Harmonogramu zadań Windows).
- `build_exe.bat` / `GeoSteam.spec` — budują samodzielny `GeoSteam.exe` (PyInstaller).
- `installer/` — definicja instalatora MSI (WiX Toolset).

Workflow `.github/workflows/build-windows-exe.yml` automatycznie buduje `.exe` i `.msi` na GitHub Actions, a po wypchnięciu tagu `v*` (np. `v1.0.0`) publikuje je automatycznie jako GitHub Release.

## Dokumentacja

Pełna dokumentacja (instalacja, konfiguracja źródeł, opis GUI, harmonogram, format raportów, budowanie `.exe`/`.msi`, FAQ) znajduje się w **[Wiki projektu](https://github.com/sweco-pl/GeoSteam/wiki)**.

## Licencja

Projekt jest udostępniony na licencji [GNU General Public License v3.0](LICENSE).

## Współpraca

Zgłoszenia błędów i propozycje zmian są mile widziane poprzez [Issues](https://github.com/sweco-pl/GeoSteam/issues) i Pull Requesty.
