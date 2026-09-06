import flet as ft
import base64
import json
import os
import socket
import asyncio
import re
import io
import httpx
from datetime import datetime
from PIL import Image

# Katalog trwałego przechowywania danych aplikacji na pliki EDI (Android/iOS)
KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
os.makedirs(KATALOG_DANYCH, exist_ok=True)

CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")

DOMYSLNA_KONFIGURACJA = {
    "wol_mac": "2C:F0:5D:E4:8E:85",
    "serwer_ip": "192.168.1.154",
    "serwer_port": "1234",
    "api_key": "sk-lm-local",
    "model_name": "google/gemma-3-4b",
    "use_custom_url": False,
    "custom_base_url": "https://api.openai.com/v1"
}

def wczytaj_konfiguracje() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                dane = json.load(f)
                konf = DOMYSLNA_KONFIGURACJA.copy()
                konf.update(dane)
                return konf
        except Exception:
            return DOMYSLNA_KONFIGURACJA.copy()
    return DOMYSLNA_KONFIGURACJA.copy()

def zapisz_konfiguracje(konf: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(konf, f, indent=2)
    except Exception as e:
        print(f"Błąd zapisu konfiguracji: {e}")

def wyslij_wol(mac_address: str):
    czysty_mac = mac_address.replace(":", "").replace("-", "").replace(".", "")
    if len(czysty_mac) != 12:
        raise ValueError("Nieprawidłowy format adresu MAC (wymagane 12 znaków hex).")

    dane_mac = bytes.fromhex(czysty_mac)
    magic_packet = b"\xff" * 6 + dane_mac * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic_packet, ("<broadcast>", 9))

def generuj_tekst_edi(dane: dict) -> str:
    pozycje = dane.get("pozycje", [])
    wyst = dane.get("wystawca", {})
    odb = dane.get("odbiorca", {})
    stawki = dane.get("stawki", [])

    linie = [
        "TypPolskichLiter:LA",
        "TypDok:FW",
        f"NrDok:{dane.get('nr_dok', '')}",
        f"Data:{dane.get('data', datetime.now().strftime('%d.%m.%Y'))}",
        f"SposobPlatn:{dane.get('sposob_platnosci', 'PRZEL')}",
        f"TerminPlatn:{dane.get('termin_platnosci_dni', '14')}",
        "IndeksCentralny:SWW",
        f"NazwaWystawcy:{wyst.get('nazwa', '')}",
        f"AdresWystawcy:{wyst.get('adres', '')}",
        f"KodWystawcy:{wyst.get('kod', '')}",
        f"MiastoWystawcy:{wyst.get('miasto', '')}",
        f"UlicaWystawcy:{wyst.get('ulica', '')}",
        f"NIPWystawcy:{wyst.get('nip', '')}",
        f"BankWystawcy:{wyst.get('bank', '')}",
        f"KontoWystawcy:{wyst.get('konto', '')}",
        "TelefonWystawcy:",
        "NrWystawcyWSieciSklepow:0",
        f"NazwaOdbiorcy:{odb.get('nazwa', '')}",
        f"AdresOdbiorcy:{odb.get('adres', '')}",
        f"KodOdbiorcy:{odb.get('kod', '')}",
        f"MiastoOdbiorcy:{odb.get('miasto', '')}",
        f"UlicaOdbiorcy:{odb.get('ulica', '')}",
        f"NIPOdbiorcy:{odb.get('nip', '')}",
        "BankOdbiorcy:",
        "KontoOdbiorcy:",
        "TelefonOdbiorcy:",
        "NrOdbiorcyWSieciSklepow:0",
        f"IloscLinii:{len(pozycje)}"
    ]

    for poz in pozycje:
        nazwa = poz.get("nazwa", "")
        kod = poz.get("kod", "")
        vat = poz.get("vat", "23")
        jm = poz.get("jm", "szt")
        asort = poz.get("asortyment", "")
        pkwiu = poz.get("pkwiu", "")
        ilosc = poz.get("ilosc", "1")
        cena = str(poz.get("cena_netto", "0.00")).replace(",", ".")
        wartosc = str(poz.get("wartosc_netto", "0.00")).replace(",", ".")

        if not cena.startswith("n"):
            cena = f"n{cena}"
        if not wartosc.startswith("n"):
            wartosc = f"n{wartosc}"

        linia = (
            f"Linia:Nazwa{{{nazwa}}}Kod{{{kod}}}Vat{{{vat}}}Jm{{{jm}}}"
            f"Asortyment{{{asort}}}Sww{{        }}PKWiU{{{pkwiu}}}"
            f"Ilosc{{{ilosc}}}Cena{{{cena}}}Wartosc{{{wartosc}}}CenaSp{{}}Kod1{{}}"
        )
        linie.append(linia)

    for st in stawki:
        vat = st.get("vat", "23")
        s_netto = str(st.get("suma_netto", "0.00")).replace(",", ".")
        s_vat = str(st.get("suma_vat", "0.00")).replace(",", ".")
        linie.append(f"Stawka:Vat{{{vat}}}SumaNet{{{s_netto}}}SumaVat{{{s_vat}}}")

    linie.append(f"DoZaplaty:{str(dane.get('do_zaplaty', '0.00')).replace(',', '.')}")
    return "\n".join(linie) + "\n"

def kompresuj_do_base64(sciezka_pliku: str) -> str:
    with Image.open(sciezka_pliku) as img:
        img.thumbnail((1600, 1600))
        if img.mode != "RGB":
            img = img.convert("RGB")
        bufor = io.BytesIO()
        img.save(bufor, format="JPEG", quality=85)
        return base64.b64encode(bufor.getvalue()).decode("utf-8")

async def main(page: ft.Page):
    page.title = "ocrLmm Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    konfig = wczytaj_konfiguracje()

    ostatnia_sciezka_edi = {"sciezka": None}
    aktualne_zdjecie = {"sciezka": None}

    txt_mac = ft.TextField(label="Adres MAC (Wake-on-LAN)", value=konfig["wol_mac"], dense=True)
    txt_ip = ft.TextField(label="IP Serwera LM Studio", value=konfig["serwer_ip"], dense=True)
    txt_port = ft.TextField(label="Port LM Studio", value=konfig["serwer_port"], dense=True)
    txt_model = ft.TextField(label="Identyfikator modelu", value=konfig["model_name"], dense=True)
    txt_api_key = ft.TextField(
        label="Klucz API",
        value=konfig["api_key"],
        password=True,
        can_reveal_password=True,
        dense=True
    )

    chk_custom = ft.Checkbox(value=konfig["use_custom_url"])
    wiersz_chmura = ft.Row([
        chk_custom,
        ft.Text("Użyj niestandardowego URL", expand=True)
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    txt_custom_url = ft.TextField(
        label="Niestandardowy Base URL",
        value=konfig["custom_base_url"],
        visible=konfig["use_custom_url"],
        dense=True
    )

    def zmien_chk_custom(e):
        txt_custom_url.visible = chk_custom.value
        page.update()

    chk_custom.on_change = zmien_chk_custom

    status_text = ft.Text(
        "Gotowy do wybrania zdjęcia faktury.",
        size=13,
        color=ft.Colors.GREEN_ACCENT,
        text_align=ft.TextAlign.CENTER
    )
    pasek_postepu = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_ACCENT)
    podglad_obrazu = ft.Image(src="", visible=False, fit="contain", height=240)

    def usun_wybrane_zdjecie(e):
        aktualne_zdjecie["sciezka"] = None
        podglad_obrazu.src = ""
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        btn_udostepnij.visible = False
        btn_ponow.visible = False
        wiersz_obrotu.visible = False
        status_text.value = "Zdjęcie usunięte. Wybierz nowe zdjęcie faktury."
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    btn_usun_zdjecie = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE), ft.Text("Usuń wybrane zdjęcie")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False,
        style=ft.ButtonStyle(color=ft.Colors.RED_300),
        on_click=usun_wybrane_zdjecie
    )

    def obroc_zdjecie(kat):
        sciezka = aktualne_zdjecie["sciezka"]
        if not sciezka or not os.path.exists(sciezka):
            return
        try:
            with Image.open(sciezka) as im:
                obrocony = im.rotate(kat, expand=True)
                obrocony.save(sciezka)
            
            podglad_obrazu.src = f"{sciezka}?t={datetime.now().timestamp()}"
            status_text.value = f"Obrócono zdjęcie o {abs(kat)}°. Kliknij 'Wyślij ponownie do analizy'."
            status_text.color = ft.Colors.CYAN_ACCENT
            btn_ponow.visible = True
            page.update()
        except Exception as err_rot:
            status_text.value = f"Błąd obracania: {err_rot}"
            page.update()

    btn_obroc_lewo = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_LEFT), ft.Text("W lewo")], alignment=ft.MainAxisAlignment.CENTER),
        expand=True,
        on_click=lambda e: obroc_zdjecie(90)
    )

    btn_obroc_prawo = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_RIGHT), ft.Text("W prawo")], alignment=ft.MainAxisAlignment.CENTER),
        expand=True,
        on_click=lambda e: obroc_zdjecie(-90)
    )

    wiersz_obrotu = ft.Row([btn_obroc_lewo, btn_obroc_prawo], visible=False, spacing=10)

    def zamknij_dialog(e):
        dlg_ustawienia.open = False
        page.update()

    def zapisz_i_zamknij_dialog(e):
        konfig["wol_mac"] = txt_mac.value.strip()
        konfig["serwer_ip"] = txt_ip.value.strip()
        konfig["serwer_port"] = txt_port.value.strip()
        konfig["api_key"] = txt_api_key.value.strip()
        konfig["model_name"] = txt_model.value.strip()
        konfig["use_custom_url"] = chk_custom.value
        konfig["custom_base_url"] = txt_custom_url.value.strip()
        
        zapisz_konfiguracje(konfig)
        dlg_ustawienia.open = False
        status_text.value = "Ustawienia zostały zapisane."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    dlg_ustawienia = ft.AlertDialog(
        title=ft.Text("⚙️ Ustawienia połączenia"),
        content=ft.Column(
            [
                txt_mac, txt_ip, txt_port, txt_model, txt_api_key, wiersz_chmura, txt_custom_url
            ],
            tight=True, scroll=ft.ScrollMode.AUTO, spacing=10
        ),
        actions=[
            ft.Button(content=ft.Text("Anuluj"), on_click=zamknij_dialog),
            ft.Button(
                content=ft.Text("Zapisz"),
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE),
                on_click=zapisz_i_zamknij_dialog
            )
        ]
    )
    page.overlay.append(dlg_ustawienia)

    def otworz_ustawienia(e):
        dlg_ustawienia.open = True
        page.update()

    async def klik_budzenie_wol(e):
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: wyslij_wol(txt_mac.value.strip()))
            status_text.value = "Pakiet Wake-on-LAN wysłany. Poczekaj 15-20 sek. na start serwera."
            status_text.color = ft.Colors.CYAN_ACCENT
        except Exception as err_wol:
            status_text.value = f"Błąd WoL: {err_wol}"
            status_text.color = ft.Colors.RED_ACCENT
        page.update()

    # Rejestracja serwisów systemowych
    picker = ft.FilePicker()
    serwis_udostepniania = ft.Share()

    if hasattr(page, "services"):
        page.services.append(picker)
        page.services.append(serwis_udostepniania)
    else:
        page.overlay.extend([picker, serwis_udostepniania])

    async def udostepnij_plik(sciezka):
        if not sciezka or not os.path.exists(sciezka):
            status_text.value = "Brak pliku EDI do udostępnienia (wybierz i przetwórz zdjęcie)."
            status_text.color = ft.Colors.RED_ACCENT
            page.update()
            return

        try:
            # 1. Próba natywnego menu udostępniania (Android / iOS)
            if hasattr(serwis_udostepniania, "share_files"):
                try:
                    await serwis_udostepniania.share_files(
                        [ft.ShareFile.from_path(sciezka)],
                        text="Plik EDI wygenerowany przez ocrLmm"
                    )
                    return
                except Exception:
                    await serwis_udostepniania.share_files([sciezka])
                    return

            # 2. Fallback na komputerze z Windows
            os.system(f'explorer /select,"{os.path.abspath(sciezka)}"')
            status_text.value = "Otwarto folder z plikiem EDI na komputerze."
            status_text.color = ft.Colors.CYAN_ACCENT
            page.update()

        except Exception as e_share:
            status_text.value = f"Błąd udostępniania: {e_share}"
            status_text.color = ft.Colors.RED_ACCENT
            page.update()

    async def przetworz_plik(sciezka_obrazu):
        if not sciezka_obrazu or not os.path.exists(sciezka_obrazu):
            return

        try:
            status_text.value = "Kompresja i analiza faktury..."
            status_text.color = ft.Colors.ORANGE_ACCENT
            pasek_postepu.visible = True
            btn_foto.disabled = True
            btn_ponow.visible = False
            btn_usun_zdjecie.visible = False
            btn_udostepnij.visible = False
            wiersz_obrotu.visible = False
            page.update()

            loop = asyncio.get_running_loop()
            base64_image = await loop.run_in_executor(None, kompresuj_do_base64, sciezka_obrazu)

            if konfig["use_custom_url"]:
                b_url = konfig["custom_base_url"].strip()
            else:
                b_url = f"http://{konfig['serwer_ip'].strip()}:{konfig['serwer_port'].strip()}/v1"

            prompt = (
                "Przeanalizuj to zdjęcie. Jeśli na obrazie NIE MA faktury, dokumentu handlowego "
                "lub brak jest tabeli z pozycjami towarowymi, lub horyzont/układ jest całkowicie niewłaściwy, "
                "zwróć DOKŁADNIE: {\"error\": \"brak_faktury\"}.\n\n"
                "Jeśli obraz JEST fakturą, wyodrębnij dane do JSON o strukturze:\n"
                "{\n"
                "  \"nr_dok\": \"numer faktury\",\n"
                "  \"data\": \"DD.MM.RRRR\",\n"
                "  \"termin_platnosci_dni\": \"ilość dni lub data\",\n"
                "  \"sposob_platnosci\": \"PRZEL/GOT/itp\",\n"
                "  \"wystawca\": {\"nazwa\": \"...\", \"adres\": \"...\", \"kod\": \"...\", \"miasto\": \"...\", \"ulica\": \"...\", \"nip\": \"...\", \"bank\": \"...\", \"konto\": \"...\"},\n"
                "  \"odbiorca\": {\"nazwa\": \"...\", \"adres\": \"...\", \"kod\": \"...\", \"miasto\": \"...\", \"ulica\": \"...\", \"nip\": \"...\"},\n"
                "  \"pozycje\": [{\"nazwa\": \"...\", \"kod\": \"...\", \"vat\": \"23\", \"jm\": \"szt\", \"asortyment\": \"\", \"pkwiu\": \"\", \"ilosc\": \"1\", \"cena_netto\": \"0.00\", \"wartosc_netto\": \"0.00\"}],\n"
                "  \"stawki\": [{\"vat\": \"23\", \"suma_netto\": \"0.00\", \"suma_vat\": \"0.00\"}],\n"
                "  \"do_zaplaty\": \"0.00\"\n"
                "}\n"
                "Zwróć TYLKO czysty JSON, bez znaczników ```json."
            )

            naglowki = {"Authorization": f"Bearer {konfig['api_key'].strip() or 'sk-lm-local'}"}
            cialo_zapytania = {
                "model": konfig["model_name"].strip() or "google/gemma-3-4b",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }],
                "temperature": 0.1
            }

            async with httpx.AsyncClient(timeout=45.0) as client:
                odpowiedz = await client.post(
                    f"{b_url}/chat/completions",
                    headers=naglowki,
                    json=cialo_zapytania
                )
                odpowiedz.raise_for_status()
                dane_odp = odpowiedz.json()
                odp_tekst = dane_odp["choices"][0]["message"]["content"].strip()

            dopasowanie = re.search(r'\{.*\}', odp_tekst, re.DOTALL)
            if not dopasowanie:
                raise ValueError("Model AI nie zwrócił poprawnego formatu strukturalnego. Spróbuj obrócić zdjęcie.")

            czysty_json = dopasowanie.group(0)

            try:
                dane = json.loads(czysty_json)
            except json.JSONDecodeError:
                raise ValueError("Wewnętrzny błąd parsowania JSON. Zdjęcie może być nieczytelne.")

            if "error" in dane:
                raise ValueError("AI nie wykryło tabeli faktury. Jeśli dokument jest w poziomie, obróć go przyciskami poniżej i spróbuj ponownie.")

            tresc_edi = generuj_tekst_edi(dane)

            nr_dok = "".join(c for c in dane.get("nr_dok", "faktura") if c.isalnum() or c in ("-", "_"))
            nazwa_pliku = f"edi_{nr_dok}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            sciezka_edi = os.path.join(KATALOG_DANYCH, nazwa_pliku)

            with open(sciezka_edi, "w", encoding="windows-1250", errors="replace") as f:
                f.write(tresc_edi)

            ostatnia_sciezka_edi["sciezka"] = sciezka_edi
            status_text.value = f"✅ Gotowe! Utworzono: {nazwa_pliku}"
            status_text.color = ft.Colors.GREEN_ACCENT
            
            btn_udostepnij.visible = True
            await udostepnij_plik(sciezka_edi)

        except Exception as err:
            komunikat = str(err)
            if "timeout" in komunikat.lower() or "timed out" in komunikat.lower():
                status_text.value = "Błąd: Serwer nie odpowiada (Timeout). Upewnij się, że komputer jest włączony i sprawdź IP."
            elif "connect" in komunikat.lower() or "refused" in komunikat.lower():
                status_text.value = "Błąd połączenia: Serwer LM Studio jest wyłączony lub podano złe IP."
            else:
                status_text.value = f"Błąd: {komunikat}"
            
            status_text.color = ft.Colors.RED_ACCENT
            btn_ponow.visible = True
        finally:
            pasek_postepu.visible = False
            btn_foto.disabled = False
            btn_usun_zdjecie.visible = True
            wiersz_obrotu.visible = True
            page.update()

    async def wybierz_zdjecie(e):
        try:
            wynik = picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            pliki = await wynik if asyncio.iscoroutine(wynik) else wynik

            if pliki and len(pliki) > 0:
                wybrany = pliki[0].path
                aktualne_zdjecie["sciezka"] = wybrany
                podglad_obrazu.src = wybrany
                podglad_obrazu.visible = True
                btn_usun_zdjecie.visible = True
                wiersz_obrotu.visible = True
                page.update()
                await przetworz_plik(wybrany)
        except Exception as e_pick:
            status_text.value = f"Błąd wyboru pliku: {e_pick}"
            page.update()

    btn_foto = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.PHOTO_LIBRARY), ft.Text("Wybierz zdjęcie faktury")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        height=55,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.GREEN_800,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=wybierz_zdjecie
    )

    async def klik_ponow(e):
        if aktualne_zdjecie["sciezka"]:
            await przetworz_plik(aktualne_zdjecie["sciezka"])

    btn_ponow = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.REFRESH), ft.Text("Wyślij ponownie do analizy")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        visible=False,
        height=48,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.AMBER_900,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=klik_ponow
    )

    async def klik_udostepnij(e):
        await udostepnij_plik(ostatnia_sciezka_edi["sciezka"])

    btn_udostepnij = ft.Button(
        content=ft.Row(
            [ft.Icon(ft.Icons.SHARE), ft.Text("Udostępnij plik EDI")],
            alignment=ft.MainAxisAlignment.CENTER
        ),
        visible=False,
        height=48,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE_GREY_800,
            color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=8)
        ),
        on_click=klik_udostepnij
    )

    btn_wol = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.POWER_SETTINGS_NEW), ft.Text("Obudź serwer (WoL)")]),
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_900, color=ft.Colors.BLUE_200),
        on_click=klik_budzenie_wol
    )

    btn_settings = ft.IconButton(
        icon=ft.Icons.SETTINGS,
        tooltip="Ustawienia połączenia",
        on_click=otworz_ustawienia
    )

    pasek_tytulu = ft.Row(
        [
            ft.Column(
                [
                    ft.Text("ocrLmm Mobile", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                    ft.Text("Skaner PZ do EDI", size=12, color=ft.Colors.GREY_400)
                ],
                spacing=2
            ),
            btn_settings
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )

    page.add(
        ft.Column(
            [
                pasek_tytulu,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                btn_foto,
                btn_wol,
                pasek_postepu,
                status_text,
                btn_ponow,
                btn_udostepnij,
                podglad_obrazu,
                wiersz_obrotu,
                btn_usun_zdjecie,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=10
        )
    )

if __name__ == "__main__":
    ft.run(main)
