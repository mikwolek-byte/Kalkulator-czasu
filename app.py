import streamlit as st
import pandas as pd
import re
from pydantic import BaseModel, Field

# ==========================================
# 1. STAŁE TECHNOLOGICZNE (PANEL ADMINA)
# ==========================================
CONF_PREP_PROFIL = 5.0
CONF_PREP_BLACHA = 50.0
CONF_FIT_PROFIL = 20.0
CONF_FIT_BLACHA = 7.0
CONF_MULTIPLIER = 2.0
CONF_WELD_MIN_MB = 20.0
CONF_LOG_INTERNAL = 30.0
CONF_LOG_LOADING = 10.0

# ==========================================
# 2. WALIDACJA DANYCH (PYDANTIC)
# ==========================================
class ProductionData(BaseModel):
    total_w_profil: float = Field(default=0.0, ge=0.0)
    total_w_blacha: float = Field(default=0.0, ge=0.0)
    qty_profil_pcs: int = Field(default=0, ge=0)
    qty_blacha_pcs: int = Field(default=0, ge=0)
    total_weld_mb: float = Field(default=0.0, ge=0.0)
    total_ass_pcs: int = Field(default=0, ge=0)

# ==========================================
# 3. SILNIK MATEMATYCZNY
# ==========================================
def calculate_production(data: ProductionData) -> dict:
    t_prep_profil = data.total_w_profil * CONF_PREP_PROFIL
    t_prep_blacha = data.total_w_blacha * CONF_PREP_BLACHA
    t_prep = t_prep_profil + t_prep_blacha

    minuty_montazu = (data.qty_profil_pcs * CONF_FIT_PROFIL) + (data.qty_blacha_pcs * CONF_FIT_BLACHA)
    t_fit = (minuty_montazu * CONF_MULTIPLIER) / 60.0
    t_weld = (data.total_weld_mb * CONF_WELD_MIN_MB) / 60.0
    t_log = (data.total_ass_pcs * (CONF_LOG_INTERNAL + CONF_LOG_LOADING)) / 60.0

    total_rbg = t_prep + t_fit + t_weld + t_log
    total_tons = data.total_w_profil + data.total_w_blacha
    rbg_per_ton = total_rbg / total_tons if total_tons > 0 else 0.0

    return {
        "t_prep": round(t_prep, 2),
        "t_fit": round(t_fit, 2),
        "t_weld": round(t_weld, 2),
        "t_log": round(t_log, 2),
        "total_rbg": round(total_rbg, 2),
        "total_tons": round(total_tons, 2),
        "rbg_per_ton": round(rbg_per_ton, 2)
    }

# ==========================================
# 4. INTELIGENTNY PARSER EXCEL Z FUZZY MATCHING
# ==========================================
def extract_number(val) -> float:
    """Ekstrahuje pierwszą liczbę z dowolnego ciągu znaków (np. '14.5 kg' -> 14.5)"""
    if pd.isna(val):
        return 0.0
    val_str = str(val).replace(',', '.')
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", val_str)
    if numbers:
        return float(numbers[0])
    return 0.0

def parse_excel_bom(file):
    try:
        # 1. Wczytanie próbne bez nagłówków, aby odnaleźć początek tabeli
        temp_df = pd.read_excel(file, header=None)
        header_idx = -1
        
        # Skanowanie pierwszych 30 wierszy w poszukiwaniu słów kluczowych
        for i, row in temp_df.head(30).iterrows():
            row_str = " ".join([str(x).lower() for x in row.values if pd.notna(x)])
            # Sprawdzamy, czy wiersz zawiera typowe nazwy kolumn
            has_profile = any(k in row_str for k in ['profil', 'description', 'opis', 'nazwa', 'name', 'part'])
            has_weight = any(k in row_str for k in ['waga', 'weight', 'masa', 'ciężar', 'ciezar'])
            
            if has_profile and has_weight:
                header_idx = i
                break
                
        if header_idx == -1:
            return temp_df, "Nie znaleziono wiersza z nagłówkami. Upewnij się, że tabela ma kolumny z Profilem i Wagą."

        # 2. Właściwe wczytanie z odpowiednim nagłówkiem
        df = pd.read_excel(file, header=header_idx)
        df.columns = [str(c).lower().strip() for c in df.columns]

        # 3. Fuzzy matching - przypisywanie elastyczne kolumn
        col_profile = next((c for c in df.columns if any(k in c for k in ['profile', 'profil', 'description', 'opis', 'name', 'nazwa', 'kształtownik', 'part'])), None)
        col_qty = next((c for c in df.columns if any(k in c for k in ['qty', 'quantity', 'ilość', 'ilosc', 'szt', 'liczba', 'count'])), None)
        col_weight = next((c for c in df.columns if any(k in c for k in ['weight', 'waga', 'ciężar', 'ciezar', 'masa', 'wgt'])), None)
        col_length = next((c for c in df.columns if any(k in c for k in ['length', 'długość', 'dlugosc', 'dł', 'len'])), None)
        col_assembly = next((c for c in df.columns if any(k in c for k in ['assembly', 'mark', 'zespół', 'pozycja', 'nr', 'pos', 'element'])), None)

        if not col_profile or not col_weight:
            return df, f"Znalazłem tabelę, ale brakuje kluczowych kolumn. Znalezione nagłówki: {', '.join(df.columns)}"

        # 4. Przeliczanie danych
        calc_w_profil, calc_w_blacha = 0.0, 0.0
        calc_qty_profil, calc_qty_blacha = 0, 0
        calc_weld_mb = 0.0
        unique_assemblies = set()

        for _, row in df.iterrows():
            if pd.isna(row[col_profile]) or "total" in str(row[col_profile]).lower():
                continue
                
            desc = str(row[col_profile]).strip().upper()
            
            # Bezpieczne pobieranie liczb
            qty = int(extract_number(row[col_qty])) if col_qty else 1
            if qty == 0: qty = 1
            
            weight_kg = extract_number(row[col_weight])
            length_mm = extract_number(row[col_length]) if col_length else 0.0

            if col_assembly and pd.notna(row[col_assembly]):
                unique_assemblies.add(str(row[col_assembly]).strip())

            # Logika rozdziału (Blachy i Profile)
            is_plate = desc.startswith(("PL", "BL", "FL", "BLACHA"))
            weight_ton = weight_kg / 1000.0

            if is_plate:
                calc_w_blacha += weight_ton
                calc_qty_blacha += qty
                
                # Próba wyciągnięcia szerokości z blachy np. PL20*150 -> 150
                w_match = re.search(r'(?:PL|BL|FL)\d+[\s\-\*xX]+(\d+(?:[\.,]\d+)?)', desc)
                width_mm = float(w_match.group(1).replace(',', '.')) if w_match else 100.0
                
                # Obwód w metrach bieżących x ilość
                perimeter_m = 2.0 * (width_mm + length_mm) / 1000.0
                calc_weld_mb += (perimeter_m * qty)
            else:
                calc_w_profil += weight_ton
                calc_qty_profil += qty

        results = {
            "w_profil": calc_w_profil,
            "w_blacha": calc_w_blacha,
            "qty_profil": calc_qty_profil,
            "qty_blacha": calc_qty_blacha,
            "weld_mb": calc_weld_mb,
            "ass_pcs": len(unique_assemblies) if unique_assemblies else 1
        }
        
        return df, results
    except Exception as e:
        return pd.DataFrame(), f"Krytyczny błąd podczas analizy pliku Excel: {str(e)}"

# ==========================================
# 5. INTERFEJS UŻYTKOWNIKA (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Kalkulator Pracochłonności Zekon", layout="wide")

if "form_data" not in st.session_state:
    st.session_state.form_data = {
        "w_profil": 0.0, "w_blacha": 0.0,
        "qty_profil": 0, "qty_blacha": 0,
        "weld_mb": 0.0,  "ass_pcs": 0
    }
    st.session_state.raw_df = pd.DataFrame()
    st.session_state.debug_msg = ""

st.title("⚙️ Kalkulator Produkcyjny - Zekon (Excel BOM)")
st.markdown("Wersja zoptymalizowana do odczytu list materiałowych w formacie `.xlsx` / `.xls` z Tekla Structures.")
st.markdown("---")

st.sidebar.header("📂 Wczytaj plik Tekla (Excel)")
uploaded_excel = st.sidebar.file_uploader("Przeciągnij listę materiałową", type=["xlsx", "xls"])

if uploaded_excel and st.sidebar.button("Przetwórz plik Excel"):
    with st.spinner("Inteligentne wyszukiwanie tabeli i wyliczanie obwodów blach..."):
        df, results = parse_excel_bom(uploaded_excel)
        st.session_state.raw_df = df
        
        if isinstance(results, dict):
            st.session_state.form_data = results
            st.session_state.debug_msg = ""
            st.sidebar.success("Dane odczytane poprawnie!")
        else:
            st.session_state.debug_msg = results
            st.sidebar.error("Napotkano problem z rozpoznaniem kolumn.")

# Pokazywanie surowej tabeli Excel w razie błędu, by użytkownik mógł zgłosić nam nazwy kolumn
if st.session_state.debug_msg:
    st.error(f"⚠️ {st.session_state.debug_msg}")
    with st.expander("👁️ Zobacz jak aplikacja widzi Twój plik (Tryb Debugowania)", expanded=True):
        st.dataframe(st.session_state.raw_df, use_container_width=True)
elif not st.session_state.raw_df.empty:
    with st.expander("👁️ Podgląd wczytanych danych z pliku Excel (Sukces)"):
        st.dataframe(st.session_state.raw_df, use_container_width=True)

st.markdown("### 📝 Dane zbiorcze do wyceny")
col1, col2 = st.columns(2)

fd = st.session_state.form_data

with col1:
    total_w_profil = st.number_input("Tonaż profili [T]", value=float(fd["w_profil"]), format="%.3f")
    total_w_blacha = st.number_input("Tonaż blach [T]", value=float(fd["w_blacha"]), format="%.3f")
    qty_profil_pcs = st.number_input("Ilość sztuk profili", value=int(fd["qty_profil"]))
with col2:
    qty_blacha_pcs = st.number_input("Ilość sztuk blach", value=int(fd["qty_blacha"]))
    total_weld_mb = st.number_input("Długość spoin z obwodów blach [mb]", value=float(fd["weld_mb"]), format="%.2f")
    total_ass_pcs = st.number_input("Liczba el. wysyłkowych (Zespołów)", value=int(fd["ass_pcs"]))

if st.button("🧮 Oblicz pracochłonność", type="primary", use_container_width=True):
    data = ProductionData(
        total_w_profil=total_w_profil,
        total_w_blacha=total_w_blacha,
        qty_profil_pcs=qty_profil_pcs,
        qty_blacha_pcs=qty_blacha_pcs,
        total_weld_mb=total_weld_mb,
        total_ass_pcs=total_ass_pcs
    )
    res = calculate_production(data)
    
    st.markdown("---")
    st.subheader("📊 Wyniki Kalkulacji")
    m1, m2, m3 = st.columns(3)
    m1.metric("CAŁKOWITY CZAS (TOTAL_RBG)", f"{res['total_rbg']} rbg")
    m2.metric("ŁĄCZNY TONAŻ (TOTAL_TONS)", f"{res['total_tons']} T")
    m3.metric("WSKAŹNIK OFERTOWY", f"{res['rbg_per_ton']} rbg/T")
    
    st.code(f"""
1. Czas przygotowania (T_prep): {res['t_prep']} rbg
2. Czas składania (T_fit):      {res['t_fit']} rbg
3. Czas spawania (T_weld):      {res['t_weld']} rbg
4. Czas logistyki (T_log):      {res['t_log']} rbg
    """)
