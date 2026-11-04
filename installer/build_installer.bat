@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

set "WIX_VERSION=5.0.2"
set "VERSION=%~1"
if "%VERSION%"=="" set "VERSION=1.0.0"

set "PATH=%USERPROFILE%\.dotnet\tools;%PATH%"

echo === 1/3: Budowanie GeoSteam.exe (PyInstaller) ===
call build_exe.bat
if errorlevel 1 (
    echo Budowanie GeoSteam.exe nie powiodlo sie, przerywam.
    exit /b 1
)
if not exist "dist\GeoSteam\GeoSteam.exe" (
    echo Brak dist\GeoSteam\GeoSteam.exe po budowaniu - przerywam.
    exit /b 1
)

REM Usuwa z paczki ewentualne slady wczesniejszego recznego uruchomienia GeoSteam.exe w tym folderze
REM (dane, raporty, scenariusze, ustawienia.json) - to sa pliki tworzone dopiero przy starcie programu
REM i nie powinny trafiac do instalatora.
for %%F in (dane raporty scenariusze) do (
    if exist "dist\GeoSteam\%%F" rd /s /q "dist\GeoSteam\%%F"
)
if exist "dist\GeoSteam\ustawienia.json" del /q "dist\GeoSteam\ustawienia.json"
if exist "dist\GeoSteam\blad.txt" del /q "dist\GeoSteam\blad.txt"

REM === Opcjonalne podpisywanie kodu (ogranicza ostrzezenia SmartScreen) ===
REM SmartScreen ostrzega przed niepodpisanymi plikami bez reputacji. Zeby podpisywac,
REM ustaw przed uruchomieniem zmienna GEOSTEAM_CERT_THUMBPRINT na odcisk (thumbprint)
REM certyfikatu code signing zainstalowanego w magazynie certyfikatow Windows, np.:
REM   set GEOSTEAM_CERT_THUMBPRINT=a1b2c3d4...
REM   installer\build_installer.bat 1.2.0
REM Wymaga signtool.exe (Windows SDK) dostepnego w PATH.
if defined GEOSTEAM_CERT_THUMBPRINT (
    echo.
    echo === Podpisywanie GeoSteam.exe ===
    call :podpisz "dist\GeoSteam\GeoSteam.exe"
    if errorlevel 1 exit /b 1
)

echo.
echo === 2/3: Sprawdzanie WiX Toolset (wymaga .NET SDK) ===
where dotnet >nul 2>nul
if errorlevel 1 (
    echo Brak .NET SDK. Zainstaluj .NET SDK 8 ze strony https://dotnet.microsoft.com/download
    echo albo polecenia: winget install Microsoft.DotNet.SDK.8
    pause
    exit /b 1
)

where wix >nul 2>nul
if errorlevel 1 (
    echo Instaluje narzedzie wix w wersji %WIX_VERSION% ^(dotnet tool, raz^) ...
    REM Przypieta wersja 5.x - WiX w wersji 7+ wymaga oplaty "Open Source Maintenance Fee"
    REM ^(https://wixtoolset.org/osmf/^) dla firm o rocznym przychodzie powyzej 10 000 USD.
    dotnet tool install --global wix --version %WIX_VERSION%
    if errorlevel 1 (
        echo Instalacja narzedzia wix nie powiodla sie.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('wix --version') do set "WIX_INSTALLED_VERSION=%%v"
echo Wersja wix: %WIX_INSTALLED_VERSION%

wix extension list -g | findstr /c:"WixToolset.UI.wixext" >nul
if errorlevel 1 wix extension add -g WixToolset.UI.wixext/%WIX_VERSION%
wix extension list -g | findstr /c:"WixToolset.Util.wixext" >nul
if errorlevel 1 wix extension add -g WixToolset.Util.wixext/%WIX_VERSION%

echo.
echo === 3/3: Budowanie instalatora MSI ===
if not exist "dist" mkdir "dist"
wix build "installer\Package.wxs" ^
    -arch x64 ^
    -ext WixToolset.UI.wixext ^
    -ext WixToolset.Util.wixext ^
    -d DistDir="%cd%\dist\GeoSteam" ^
    -d SourceDir="%cd%" ^
    -d GeoSteamVersion=%VERSION% ^
    -o "dist\GeoSteam-Setup-%VERSION%.msi"
if errorlevel 1 (
    echo Budowanie instalatora nie powiodlo sie. Sprawdz komunikaty powyzej.
    pause
    exit /b 1
)

if defined GEOSTEAM_CERT_THUMBPRINT (
    echo.
    echo === Podpisywanie instalatora MSI ===
    call :podpisz "dist\GeoSteam-Setup-%VERSION%.msi"
    if errorlevel 1 exit /b 1
)

echo.
echo Gotowe: dist\GeoSteam-Setup-%VERSION%.msi
pause
exit /b 0

:podpisz
where signtool >nul 2>nul
if errorlevel 1 (
    echo Brak signtool.exe w PATH. Zainstaluj Windows SDK ^(winget install Microsoft.WindowsSDK.10.0.26100^)
    echo albo uruchom skrypt z wiersza polecen "Developer Command Prompt for VS".
    pause
    exit /b 1
)
signtool sign /sha1 %GEOSTEAM_CERT_THUMBPRINT% /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 %1
if errorlevel 1 (
    echo Podpisywanie %1 nie powiodlo sie. Sprawdz komunikaty powyzej.
    pause
    exit /b 1
)
exit /b 0
