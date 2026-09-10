import streamlit as st
import pandas as pd
import pdfplumber
import re
from pydantic import BaseModel, Field

# ==========================================
# 1. KONFIGURACJA STAŁYCH (PANEL ADMINA)
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
# 4. PARSER PDF Z OBLICZANIEM OBWODÓW
# ==========================================
def parse_tekla_pdf(file) -> pd.DataFrame:
    extracted_data = []
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            
            # Ulepszone wyszukiwanie Ilości Zespołów po fazie 540
            qty_part = 1 
            if text:
                qty_match = re.search(r'Quantity[\s\S]*?540\s+(\d+)', text, re.IGNORECASE)
                if qty_match:
                    qty_part = int(qty_match.group(1))

            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                header = [str(col).upper().strip() for col in table[0] if col]
                if 'DESCRIPTION' in header and 'LENGTH' in header:
                    try:
                        desc_idx = header.index('DESCRIPTION')
                        len_idx = header.index('LENGTH')
                        qty_idx = header.index('QUANT') if 'QUANT' in header else -1
                        weight_idx = header.index('LIFT UP LOAD') if 'LIFT UP LOAD' in header else -1

                        for row in table[1:]:
                            if len(row) <= max(desc_idx, len_idx): continue
                            if row[desc_idx] is None: continue
                            
                            desc = str(row[desc_idx]).strip()
                            if not desc: continue
                            
                            is_plate = desc.startswith("PL")
                            
                            length_val = 0.0
                            if str(row[len_idx]).replace('.','',1).isdigit():
                                length_val = float(row[len_idx])
                                
                            part_qty = 1
                            if qty_idx != -1 and row[qty_idx] and str(row[qty_idx]).isdigit():
                                part_qty = int(row[qty_idx])
                                
                            weight_val = 0.0
                            if weight_idx != -1 and row[weight_idx]:
                                w_str = str(row[weight_idx]).replace(',', '.')
                                if w_str.replace('.','',1).isdigit():
                                    weight_val = float(w_str)

                            weld_m = 0.0
                            if is_plate:
                                width_match = re.search(r'PL\d+[\s\-\*]+(\d+)', desc)
                                if width_match:
                                    width_val = float(width_match.group(1))
                                    perimeter_m = 2 * (width_val + length_val) / 1000
                                    weld_m = perimeter_m * part_qty * qty_part

                            extracted_data.append({
                                "Element (Typ)": "Blacha" if is_plate else "Profil",
                                "Opis": desc,
                                "Sztuk w zespole": part_qty,
                                "Ilość zespołów": qty_part,
                                "Sztuk całkowitych": part_qty * qty_part,
                                "Waga całk. [T]": round((weight_val * qty_part) / 1000.0, 4),
                                "Spoina z obwodu [mb]": round(weld_m, 2)
                            })
                    except Exception:
                        continue

    return pd.DataFrame(extracted_data)

# ==========================================
# 5. APLIKACJA FRONTEND (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Kalkulator Pracochłonności Zekon", layout="wide")

if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = pd.DataFrame()

st.title("⚙️ Kalkulator Produkcyjny - Zekon")
st.markdown("---")

st.sidebar.header("📂 Wczytaj plik Tekla (PDF)")
uploaded_pdf = st.sidebar.file_uploader("Przeciągnij listę materiałową", type=["pdf"])

if uploaded_pdf:
    if st.sidebar.button("Skanuj rysunki i przelicz obwody"):
        with st.spinner("Skanowanie i liczenie spoin z obwodów blach..."):
            df = parse_tekla_pdf(uploaded_pdf)
            st.session_state.pdf_data = df
        st.sidebar.success("PDF załadowany i spoiny obliczone!")

if not st.session_state.pdf_data.empty:
    st.subheader("📊 Rozpoznane detale i wyliczone spoiny (Tabela edytowalna)")
    
    edited_df = st.data_editor(st.session_state.pdf_data, num_rows="dynamic", use_container_width=True)
    
    blachy_df = edited_df[edited_df["Element (Typ)"] == "Blacha"]
    profile_df = edited_df[edited_df["Element (Typ)"] == "Profil"]
    
    calc_w_profil = profile_df["Waga całk. [T]"].sum()
    calc_w_blacha = blachy_df["Waga całk. [T]"].sum()
    calc_qty_profil = profile_df["Sztuk całkowitych"].sum()
    calc_qty_blacha = blachy_df["Sztuk całkowitych"].sum()
    calc_weld_mb = blachy_df["Spoina z obwodu [mb]"].sum()
    calc_ass_pcs = edited_df["Ilość zespołów"].max() if not edited_df.empty else 0
else:
    calc_w_profil = 0.0
    calc_w_blacha = 0.0
    calc_qty_profil = 0
    calc_qty_blacha = 0
    calc_weld_mb = 0.0
    calc_ass_pcs = 0

st.markdown("### 📝 Dane zbiorcze do wyceny")
col1, col2 = st.columns(2)

with col1:
    total_w_profil = st.number_input("Tonaż profili [T]", value=float(calc_w_profil), format="%.3f")
    total_w_blacha = st.number_input("Tonaż blach [T]", value=float(calc_w_blacha), format="%.3f")
    qty_profil_pcs = st.number_input("Ilość sztuk profili", value=int(calc_qty_profil))
with col2:
    qty_blacha_pcs = st.number_input("Ilość sztuk blach", value=int(calc_qty_blacha))
    total_weld_mb = st.number_input("Długość spoin z obwodów blach [mb]", value=float(calc_weld_mb), format="%.2f")
    total_ass_pcs = st.number_input("Liczba el. wysyłkowych (Zespołów)", value=int(calc_ass_pcs))

if st.button("🧮 Oblicz pracochłonność", type="primary", use_container_width=True):
    try:
        data = ProductionData(
            total_w_profil=total_w_profil,
            total_w_blacha=total_w_blacha,
            qty_profil_pcs=qty_profil_pcs,
            qty_blacha_pcs=qty_blacha_pcs,
            total_weld_mb=total_weld_mb,
            total_ass_pcs=total_ass_pcs
        )
        
        result = calculate_production(data)
        
        st.markdown("---")
        st.subheader("📋 Wyniki Kalkulacji")
        
        mcol1, mcol2, mcol3 = st.columns(3)
        mcol1.metric("CAŁKOWITY CZAS (TOTAL_RBG)", f"{result['total_rbg']} rbg")
        mcol2.metric("ŁĄCZNY TONAŻ (TOTAL_TONS)", f"{result['total_tons']} T")
        mcol3.metric("WSKAŹNIK OFERTOWY", f"{result['rbg_per_ton']} rbg/T")
        
        st.write("**Czasy cząstkowe:**")
        st.code(f"""
1. Czas przygotowania (T_prep): {result['t_prep']} rbg
2. Czas składania (T_fit):      {result['t_fit']} rbg
3. Czas spawania (T_weld):      {result['t_weld']} rbg
4. Czas logistyki (T_log):      {result['t_log']} rbg
        """)
        
    except ValueError:
        st.error("Błąd walidacji danych: Sprawdź czy wprowadzone wartości są poprawne (nie mogą być ujemne).")
