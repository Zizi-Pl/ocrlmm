import flet as ft
import base64
import json
import os
import socket
import asyncio
from datetime import datetime
from PIL import Image as PILImage  # Do obracania obrazu
from openai import OpenAI

KATALOG_DANYCH = os.getenv("FLET_APP_STORAGE_DATA", os.getcwd())
KATALOG_TYMCZASOWY = os.getenv("FLET_APP_STORAGE_TEMP", os.getcwd())

os.makedirs(KATALOG_DANYCH, exist_ok=True)
os.makedirs(KATALOG_TYMCZASOWY, exist_ok=True)

CONFIG_FILE = os.path.join(KATALOG_DANYCH, "ocrlmm_mobile_config.json")

DOMYSLNA_KONFIGURACJA = {
    "wol_mac": "2C:F0:5D:E4:8E:85",
    "serwer_ip": "192.168.1.154",
    "serwer_port": "1234",
    "api_key": "",
    "model_name": "google/gemma-3-4b",
    "use_custom_url": False,
    "custom_base_url": "https://api.openai.com/v1"
}

def wczytaj_konfiguracje():
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

def zapisz_konfiguracje(konf):
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

def obroc_obraz(sciezka_pliku, kat=90):
    """Obraca plik graficzny o zadany kąt (domyślnie 90 stopni w prawo) i nadpisuje go."""
    try:
        with PILImage.open(sciezka_pliku) as img:
            # Obrót w lewo/prawo (PIL obraca w lewo, więc -kat daje w prawo)
            obrocony = img.rotate(-kat, expand=True)
            obrocony.save(sciezka_pliku)
    except Exception as e:
        print(f"Błąd obracania obrazu: {e}")

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

async def main(page: ft.Page):
    page.title = "ocrLmm Mobilny"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.AUTO

    konfig = wczytaj_konfiguracje()
    aktualny_plik_obrazu = {"sciezka": None}
    ostatnia_sciezka_edi = {"sciezka": None}

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
        ft.Text("Użyj niestandardowego URL (np. API w chmurze)", expand=True)
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
    podglad_obrazu = ft.Image(src="", visible=False, fit=ft.BoxFit.CONTAIN, height=220)

    # Deklaracje przycisków pomocniczych
    btn_usun_zdjecie = ft.ElevatedButton(
        content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE), ft.Text("Usuń wybrane zdjęcie")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False,
        style=ft.ButtonStyle(color=ft.Colors.RED_300),
    )

    btn_obroc = ft.ElevatedButton(
        content=ft.Row([ft.Icon(ft.Icons.ROTATE_90_DEGREES_CW), ft.Text("Obróć 90°")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False,
        style=ft.ButtonStyle(color=ft.Colors.AMBER_300),
    )

    btn_udostepnij = ft.ElevatedButton(
        content=ft.Row([ft.Icon(ft.Icons.SHARE), ft.Text("Udostępnij plik EDI")], alignment=ft.MainAxisAlignment.CENTER),
        visible=False,
        height=48,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_GREY_800, color=ft.Colors.WHITE)
    )

    def usun_wybrane_zdjecie(e):
        aktualny_plik_obrazu["sciezka"] = None
        podglad_obrazu.src = ""
        podglad_obrazu.visible = False
        btn_usun_zdjecie.visible = False
        btn_obroc.visible = False
        btn_udostepnij.visible = False
        status_text.value = "Zdjęcie usunięte. Wybierz nowe."
        status_text.color = ft.Colors.GREEN_ACCENT
        page.update()

    btn_usun_zdjecie.on_click = usun_wybrane_zdjecie

    async def obroc_i_odswiez(e):
        p = aktualny_plik_obrazu["sciezka"]
        if p and os.path.exists(p):
            obroc_obraz(p, 90)
            # Odświeżenie widoku obrazka w Flet (wymuszenie przeładowania cache ścieżki)
            podglad_obrazu.src = f"{p}?t={datetime.now().timestamp()}"
            page.update()
            await przetworz_plik(p)

    btn_obroc.on_click = obroc_i_odswiez

    def zamknij_dialog(e):
        page.pop_dialog()

    def zapisz_i_zamknij_dialog(e):
        konfig["wol_mac"] = txt_mac.value.strip()
        konfig["serwer_ip"] = txt_ip.value.strip()
        konfig["serwer_port"] = txt_port.value.strip()
        konfig["api_key"] = txt_api_key.value.strip()
        konfig["model_name"] = txt_model.value.strip()
        konfig["use_custom_url"] = chk_custom.value
        konfig["custom_base_url"] = txt_custom_url.value.strip()
        zapisz_konfiguracje(konfig)
        page.pop_dialog()
        status_text.value = "Ustawienia zostały zapisane."
        status_text.color = ft.Colors.CYAN_ACCENT
        page.update()

    dlg_ustawienia = ft.AlertDialog(
        title=ft.Text("⚙️ Ustawienia połączenia"),
        content=ft.Column(
            [txt_mac, txt_ip, txt_port, txt_model, txt_api_key, wiersz_chmura, txt_custom_url],
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

    def otworz_ustawienia(e):
        page.show_dialog(dlg_ustawienia)

    async def klik_budzenie_wol(e):
        try:
            mac = txt_mac.value.strip()
            wyslij_wol(mac)
            status_text.value = f"Pakiet Wake-on-LAN wysłany do: {mac}"
            status_text.color = ft.Colors.CYAN_ACCENT
        except Exception as err_wol:
            status_text.value = f"Błąd WoL: {err_wol}"
            status_text.color = ft.Colors.RED_ACCENT
        page.update()

    serwis_udostepniania = ft.Share()
    page.services.append(serwis_udostepniania)

    async def udostepnij_plik(sciezka):
        if not sciezka or not os.path.exists(sciezka):
            return
        try:
            await serwis_udostepniania.share_files(
                [ft.ShareFile.from_path(sciezka)],
                text="Plik EDI wygenerowany przez ocrLmm",
            )
        except Exception as e_share:
            status_text.value = f"Plik zapisany, błąd menu udostępniania: {e_share}"
            page.update()

    async def przetworz_plik(sciezka_obrazu):
        try:
            status_text.value = "Wysyłanie i analiza faktury przez model..."
            status_text.color = ft.Colors.ORANGE_ACCENT
            pasek_postepu.visible = True
            btn_foto.disabled = True
            btn_usun_zdjecie.visible = False
            btn_obroc.visible = False
            btn_udostepnij.visible = False
            page.update()

            with open(sciezka_obrazu, "rb") as img_file:
                base64_image = base64.b64encode(img_file.read()).decode("utf-8")

            if konfig["use_custom_url"]:
                b_url = konfig["custom_base_url"].strip()
            else:
                b_url = f"http://{konfig['serwer_ip'].strip()}:{konfig['serwer_port'].strip()}/v1"

            client = OpenAI(
                base_url=b_url,
                api_key=konfig["api_key"].strip() or "lm-studio",
                timeout=45.0  # Dodany timeout na wypadek wolnej sieci / zawieszenia serwera
            )

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

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=konfig["model_name"].strip() or "google/gemma-3-4b",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }],
                    temperature=0.1
                )
            )

            odp_tekst = response.choices[0].message.content.strip()
            if odp_tekst.startswith("```json"):
                odp_tekst = odp_tekst[7:]
            if odp_tekst.endswith("```"):
                odp_tekst = odp_tekst[:-3]
            odp_tekst = odp_tekst.strip()

            try:
                dane = json.loads(odp_tekst)
            except
