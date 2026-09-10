import streamlit as st
import json
import pandas as pd
import pdfplumber
import io
import re
from pydantic import BaseModel, Field, ValidationError

st.set_page_config(
    page_title="Kalkulator Produkcji + AI Reader",
    page_icon="🏭",
    layout="wide"
)

class AppConfig(BaseModel):
    """Model konfiguracji przechowujący stałe technologiczne."""
    conf_prep_profil: float = 5.0
    conf_prep_blacha: float = 50.0
    conf_fit_profil: float = 20.0
    conf_fit_blacha: float = 7.0
    conf_multiplier: float = 2.0
    conf_weld_min_mb: float = 20.0
    conf_log_internal: float = 30.0
    conf_log_loading: float = 10.0

class ProductionData(BaseModel):
    """Model danych wejściowych z wbudowaną walidacją."""
    total_w_profil: float = Field(..., ge=0)
    total_w_blacha: float = Field(..., ge=0)
    qty_profil_pcs: int = Field(..., ge=0)
    qty_blacha_pcs: int = Field(..., ge=0)
    total_weld_mb: float = Field(..., ge=0)
    total_ass_pcs: int = Field(..., ge=0)

class CalculationResult(BaseModel):
    """Model reprezentujący wyniki obliczeń."""
    t_prep: float
    t_fit: float
    t_weld: float
    t_log_internal: float
    t_log_loading: float
    t_log_total: float
    total_rbg: float
    total_tons: float
    rbg_per_ton: float

class ProductionCalculator:
    def __init__(self, config: AppConfig):
        self.config = config

    def calculate(self, data: ProductionData) -> CalculationResult:
        # KROK 1: Przygotowanie Detali
        t_prep_profil = data.total_w_profil * self.config.conf_prep_profil
        t_prep_blacha = data.total_w_blacha * self.config.conf_prep_blacha
        t_prep = round(t_prep_profil + t_prep_blacha, 2)

        # KROK 2: Składanie i Szczepianie
        minuty_montazu = (data.qty_profil_pcs * self.config.conf_fit_profil) + \
                         (data.qty_blacha_pcs * self.config.conf_fit_blacha)
        t_fit = round((minuty_montazu * self.config.conf_multiplier) / 60.0, 2)

        # KROK 3: Spawanie na gotowo
        t_weld = round((data.total_weld_mb * self.config.conf_weld_min_mb) / 60.0, 2)

        # KROK 4: Logistyka i Pakowanie
        t_log_internal = (data.total_ass_pcs * self.config.conf_log_internal) / 60.0
        t_log_loading = (data.total_ass_pcs * self.config.conf_log_loading) / 60.0
        t_log_total = round(t_log_internal + t_log_loading, 2)

        # KROK 5: Wyniki Globalne
        total_rbg = round(t_prep + t_fit + t_weld + t_log_total, 2)
        total_tons = round(data.total_w_profil + data.total_w_blacha, 2)
        
        rbg_per_ton = round(total_rbg / total_tons, 2) if total_tons > 0 else 0.0

        return CalculationResult(
            t_prep=t_prep, t_fit=t_fit, t_weld=t_weld,
            t_log_internal=round(t_log_internal, 2),
            t_log_loading=round(t_log_loading, 2),
            t_log_total=t_log_total, total_rbg=total_rbg,
            total_tons=total_tons, rbg_per_ton=rbg_per_ton
        )

def init_session_state():
    """Inicjalizuje stan sesji dla wszystkich zmiennych formularza i wyników."""
    defaults = {
        'total_w_profil': 0.0,
        'total_w_blacha': 0.0,
        'qty_profil_pcs': 0,
        'qty_blacha_pcs': 0,
        'total_weld_mb': 0.0,
        'total_ass_pcs': 0,
        'calculation_result': None,
        'parsed_df': None # Przechowuje wyciągniętą tablicę z PDF
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def reset_calculator():
    """Oczyszcza cały formularz i wgrywane dane."""
    for key in ['total_w_profil', 'total_w_blacha', 'total_weld_mb']:
        st.session_state[key] = 0.0
    for key in ['qty_profil_pcs', 'qty_blacha_pcs', 'total_ass_pcs']:
        st.session_state[key] = 0
    st.session_state.calculation_result = None
    st.session_state.parsed_df = None

def parse_tekla_pdf(uploaded_file):
    """
    Czyta plik PDF z Tekla Structures, wyciąga tabele BOM, 
    rozpoznaje profile i blachy oraz agreguje ilości i wagi.
    """
    parsed_items = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text: continue
            
            # 1. Próba znalezienia Ilości Głównej (Zespołów Wysyłkowych) na stronie
            # Rysunki Tekli mają "Quantity of part", a pod spodem "Quantity [liczba]"
            ass_qty = 1
            qty_match = re.search(r'Quantity\s*[\r\n]+\s*(\d+)', text, re.IGNORECASE)
            if not qty_match:
                qty_match = re.search(r'(?i)quantity\s+(\d+)', text)
            if qty_match:
                ass_qty = int(qty_match.group(1))
                
            # 2. Nazwa Zespołu
            ass_name = f"Strona_{page_num}"
            name_match = re.search(r'(?i)Assembly-Nr.:\s*(\S+)', text)
            if name_match:
                ass_name = name_match.group(1)

            # 3. Wyciąganie tabel
            tables = page.extract_tables()
            bom_table = None
            
            # Szukamy tabeli zawierającej charakterystyczne nagłówki
            for table in tables:
                header_row_text = " ".join([str(cell).upper() for cell in table[0] if cell])
                if "PARTNR" in header_row_text or "DESCRIPTION" in header_row_text:
                    bom_table = table
                    break
                    
            if bom_table:
                headers = [str(h).upper().strip() if h else "" for h in bom_table[0]]
                
                try:
                    idx_desc = headers.index("DESCRIPTION")
                    idx_qty = headers.index("QUANT")
                    idx_weight = headers.index("LIFT UP LOAD")
                except ValueError:
                    # Fallback jeśli kolumny mają inne nazwy, zakładamy standardowy układ
                    idx_desc, idx_qty, idx_weight = 1, 3, -1
                    
                for row in bom_table[1:]:
                    if not row or not any(row): continue
                    if "TOTAL" in str(row[0]).upper(): break # Zakończ czytanie na wierszu podsumowania
                    
                    desc = str(row[idx_desc]).strip() if len(row) > idx_desc else ""
                    if not desc: continue
                    
                    # Logika biznesowa - rozróżnianie Blach od Profili
                    is_blacha = desc.upper().startswith("PL")
                    part_type = "Blacha" if is_blacha else "Profil"
                    
                    try:
                        qty = int(str(row[idx_qty]).strip())
                    except:
                        qty = 1
                        
                    try:
                        # Waga wymaga usunięcia przecinków, spacji itp.
                        weight_str = str(row[idx_weight]).replace(',', '.').replace(' ', '').strip()
                        weight_kg = float(weight_str)
                    except:
                        weight_kg = 0.0
                        
                    parsed_items.append({
                        "Zestaw": ass_name,
                        "Ilosc_Zestawow": ass_qty,
                        "Czesc": desc,
                        "Typ": part_type,
                        "Sztuki_w_Zestawie": qty,
                        "Lacznie_Sztuk": qty * ass_qty,
                        "Waga_Calkowita_kg": weight_kg * ass_qty
                    })

    if not parsed_items:
        return None
        
    return pd.DataFrame(parsed_items)

def apply_df_to_inputs(df: pd.DataFrame):
    """Przelicza tabelę DataFrame na 6 głównych zmiennych i zapisuje w sesji."""
    # Suma sztuk wysyłkowych = unikalne wartości dla każdego Zestawu
    # (Zakładamy, że każda strona/zestaw ma swoją ilość, unikamy duplikatów przy zliczaniu)
    unique_assemblies = df.drop_duplicates(subset=['Zestaw'])
    st.session_state.total_ass_pcs = int(unique_assemblies['Ilosc_Zestawow'].sum())
    
    # Filtrowanie Blach i Profili
    df_blachy = df[df['Typ'] == 'Blacha']
    df_profile = df[df['Typ'] == 'Profil']
    
    # Ilości sztuk i masy (przeliczenie kg na tony)
    st.session_state.qty_blacha_pcs = int(df_blachy['Lacznie_Sztuk'].sum())
    st.session_state.total_w_blacha = round(df_blachy['Waga_Calkowita_kg'].sum() / 1000.0, 3)
    
    st.session_state.qty_profil_pcs = int(df_profile['Lacznie_Sztuk'].sum())
    st.session_state.total_w_profil = round(df_profile['Waga_Calkowita_kg'].sum() / 1000.0, 3)

def main():
    init_session_state()
    
    st.title("🏭 Kalkulator Pracochłonności Produkcji")
    st.markdown("Narzędzie ofertowe dla Działu Handlowego z automatycznym czytnikiem rysunków PDF (Tekla).")

    with st.sidebar:
        st.header("⚙️ Panel Administratora")
        st.markdown("Stałe technologiczne (zmienne globalne).")
        conf_prep_profil = st.number_input("Cięcie/wiercenie [rbg/t]", value=5.0, step=0.5)
        conf_prep_blacha = st.number_input("Wypalanie blach [rbg/t]", value=50.0, step=1.0)
        st.divider()
        conf_fit_profil = st.number_input("Pasowanie profilu [min/szt]", value=20.0, step=1.0)
        conf_fit_blacha = st.number_input("Pasowanie blachy [min/szt]", value=7.0, step=0.5)
        conf_multiplier = st.number_input("Współczynnik trudności (mnożnik)", value=2.0, step=0.1)
        st.divider()
        conf_weld_min_mb = st.number_input("Spawanie do a=5mm [min/mb]", value=20.0, step=1.0)
        st.divider()
        conf_log_internal = st.number_input("Transport wewnętrzny [min/szt]", value=30.0, step=1.0)
        conf_log_loading = st.number_input("Załadunek na naczepę [min/szt]", value=10.0, step=1.0)

        config = AppConfig(
            conf_prep_profil=conf_prep_profil, conf_prep_blacha=conf_prep_blacha,
            conf_fit_profil=conf_fit_profil, conf_fit_blacha=conf_fit_blacha,
            conf_multiplier=conf_multiplier, conf_weld_min_mb=conf_weld_min_mb,
            conf_log_internal=conf_log_internal, conf_log_loading=conf_log_loading
        )

    # Sekcja 1: Wgrywanie PDF
    st.header("📂 1. Rozpoznawanie dokumentacji (BOM)")
    st.info("Wgraj plik PDF wygenerowany z Tekla Structures. System automatycznie zliczy masę i liczbę sztuk, oddzielając profile od blach (prefix 'PL').")
    
    col_upload, col_reset = st.columns([4, 1])
    with col_upload:
        uploaded_file = st.file_uploader("Wybierz plik PDF", type=['pdf'])
    with col_reset:
        st.button("🔄 Resetuj Wszystko", on_click=reset_calculator, type="secondary", use_container_width=True)

    if uploaded_file is not None:
        if st.button("🔍 Skanuj Rysunki i Wyciągnij Dane", type="primary"):
            with st.spinner("Czytanie dokumentacji PDF... To może potrwać kilkanaście sekund."):
                df = parse_tekla_pdf(uploaded_file)
                if df is not None:
                    st.session_state.parsed_df = df
                    apply_df_to_inputs(df)
                    st.success("Sukces! Dane zostały odczytane.")
                else:
                    st.error("Nie udało się odczytać ustrukturyzowanych tabel BOM z tego pliku PDF. Upewnij się, że zawiera on zestawienia materiałowe i wektory tekstu.")

    # Edytor danych z PDF, aby Handlowiec mógł ręcznie poprawić ew. błędy czytnika
    if st.session_state.parsed_df is not None:
        st.subheader("Edytor wykrytych detali")
        st.markdown("*Możesz ręcznie zmienić wartości w tabeli poniżej. Zmiany nie wpłyną na PDF, ale zaktualizują formularz poniżej!*")
        
        # Pozwalamy użytkownikowi edytować odczytaną tabelę
        edited_df = st.data_editor(st.session_state.parsed_df, num_rows="dynamic", use_container_width=True)
        
        # Jeśli użytkownik kliknie przycisk, przeliczymy wejścia na podstawie jego edycji
        if st.button("Aktualizuj formularz na podstawie tabeli"):
            apply_df_to_inputs(edited_df)
            st.session_state.parsed_df = edited_df
            st.rerun()
            
    st.divider()

    # Sekcja 2: Formularz Danych
    st.header("📝 2. Dane wejściowe do wyceny (RFQ)")
    st.markdown("Pola zostały wypełnione automatycznie. **Uwaga: Długość spoin nie występuje w tabelach BOM, należy ją oszacować ręcznie.**")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Masy [tony]")
        total_w_profil = st.number_input("Łączna masa profilów", value=float(st.session_state.total_w_profil), format="%.3f")
        total_w_blacha = st.number_input("Łączna masa blach", value=float(st.session_state.total_w_blacha), format="%.3f")
        
        st.subheader("Ilości sztuk [elementy składowe]")
        qty_profil_pcs = st.number_input("Liczba sztuk profilów", value=int(st.session_state.qty_profil_pcs), step=1)
        qty_blacha_pcs = st.number_input("Liczba sztuk blach", value=int(st.session_state.qty_blacha_pcs), step=1)

    with col2:
        st.subheader("Gotowe wyroby i Spawanie")
        total_ass_pcs = st.number_input("Liczba el. wysyłkowych (Sztuk Zespołów)", value=int(st.session_state.total_ass_pcs), step=1)
        
        st.warning("👇 Wprowadź szacunkową ilość metrów spoin", icon="⚠️")
        total_weld_mb = st.number_input("Długość spoin w [mb] (TOTAL_WELD_MB)", value=float(st.session_state.total_weld_mb), format="%.1f")

    st.markdown("---")
    
    if st.button("🚀 Oblicz pracochłonność", type="primary", use_container_width=True):
        try:
            input_data = ProductionData(
                total_w_profil=total_w_profil,
                total_w_blacha=total_w_blacha,
                qty_profil_pcs=qty_profil_pcs,
                qty_blacha_pcs=qty_blacha_pcs,
                total_weld_mb=total_weld_mb,
                total_ass_pcs=total_ass_pcs
            )
            
            calculator = ProductionCalculator(config)
            st.session_state.calculation_result = calculator.calculate(input_data)
        except ValidationError as e:
            st.error("Błąd wprowadzania danych. Sprawdź czy nie użyto wartości ujemnych.")

    # Wyświetlanie wyników
    if st.session_state.calculation_result:
        result = st.session_state.calculation_result
        st.header("📊 Wyniki Globalne")
        
        m1, m2, m3 = st.columns(3)
        m1.metric("CAŁKOWITY BUDŻET", f"{result.total_rbg:.2f} rbg")
        m2.metric("ŁĄCZNY TONAŻ", f"{result.total_tons:.2f} ton")
        m3.metric("WSKAŹNIK OFERTOWY", f"{result.rbg_per_ton:.2f} rbg/ton")

        st.subheader("Szczegółowe rozbicie czasu")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Przygotowanie", f"{result.t_prep:.2f} rbg")
        r2.metric("Składanie", f"{result.t_fit:.2f} rbg")
        r3.metric("Spawanie", f"{result.t_weld:.2f} rbg")
        r4.metric("Logistyka", f"{result.t_log_total:.2f} rbg", delta=f"Wewn: {result.t_log_internal:.2f}, Zał: {result.t_log_loading:.2f}", delta_color="off")

if __name__ == "__main__":
    main()
