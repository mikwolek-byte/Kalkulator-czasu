import streamlit as st
import pandas as pd
import pdfplumber
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
# 2. SILNIK MATEMATYCZNY
# ==========================================
class ProductionData(BaseModel):
    total_w_profil: float = Field(default=0.0, ge=0.0)
    total_w_blacha: float = Field(default=0.0, ge=0.0)
    qty_profil_pcs: int = Field(default=0, ge=0)
    qty_blacha_pcs: int = Field(default=0, ge=0)
    total_weld_mb: float = Field(default=0.0, ge=0.0)
    total_ass_pcs: int = Field(default=0, ge=0)

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
# 3. ROZPOZNAWANIE DANYCH Z TEKSTU RYSUNKU CAD
# ==========================================
def parse_tekla_pdf(file) -> pd.DataFrame:
    rows = []
    
    with pdfplumber.open(file) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text(layout=False)
            if not text:
                continue

            # 1. Wykrywanie ilości zespołów dla danego rysunku
            qty_part = 1
            q_match = re.search(r'Quantity\s*(?:of\s*part)?[\s\S]*?(?:540\s+)?(\d{1,4})', text, re.IGNORECASE)
            if q_match:
                try:
                    parsed_q = int(q_match.group(1))
                    if parsed_q > 0 and parsed_q != 540:
                        qty_part = parsed_q
                except ValueError:
                    pass

            # 2. Parsowanie linii materiałowych (LIST OF PARTS)
            # Przykłady: FIL1 PL30 300 S235JR 1 310 0.22 21.81
            #            FIL2 IPE270 S235JR 1 4250 4.42 153.89
            for line in text.split("\n"):
                line = line.strip()
                match = re.match(
                    r'^(FIL\w+)\s+([A-Z0-9\/\*\.\-]+(?:\s+\d+)?)\s+([A-Z0-9]+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:[\.,]\d+)?)',
                    line
                )
                if match:
                    part_no = match.group(1)
                    desc = match.group(2).strip()
                    steel = match.group(3)
                    part_qty = int(match.group(4))
                    length_val = float(match.group(5))
                    weight_val = float(match.group(7).replace(',', '.'))

                    is_plate = desc.upper().startswith("PL")
                    
                    weld_m = 0.0
                    if is_plate:
                        # Wyciąganie szerokości: PL30 300 -> 300; PL10-47 -> 47; PL10*280 -> 280
                        w_match = re.search(r'PL\d+[\s\-\*]+(\d+)', desc, re.IGNORECASE)
                        width_val = float(w_match.group(1)) if w_match else 100.0
                        perimeter_m = 2.0 * (width_val + length_val) / 1000.0
                        weld_m = perimeter_m * part_qty * qty_part

                    rows.append({
                        "Rysunek / Pozycja": f"Str.{p_idx+1} / {part_no}",
                        "Typ": "Blacha" if is_plate else "Profil",
                        "Profil / Wymiar": desc,
                        "Szt. w zespole": part_qty,
                        "Ilość zespołów": qty_part,
                        "Sztuk łącznie": part_qty * qty_part,
                        "Waga całk. [T]": round((weight_val * qty_part) / 1000.0, 4),
                        "Spoina [mb]": round(weld_m, 2)
                    })
                    
    return pd.DataFrame(rows)

# ==========================================
# 4. INTERFEJS UŻYTKOWNIKA (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Kalkulator Pracochłonności Zekon", layout="wide")

if "form_w_profil" not in st.session_state:
    st.session_state.form_w_profil = 0.0
    st.session_state.form_w_blacha = 0.0
    st.session_state.form_qty_profil = 0
    st.session_state.form_qty_blacha = 0
    st.session_state.form_weld_mb = 0.0
    st.session_state.form_ass_pcs = 0
    st.session_state.raw_df = pd.DataFrame()

st.title("⚙️ Kalkulator Produkcyjny - Zekon")
st.markdown("---")

st.sidebar.header("📂 Wczytaj plik Tekla (PDF)")
uploaded_pdf = st.sidebar.file_uploader("Wybierz plik PDF z rysunkami", type=["pdf"])

if uploaded_pdf and st.sidebar.button("Przetwórz dokument PDF"):
    with st.spinner("Parsowanie zestawień materiałowych i obwodów blach..."):
        df = parse_tekla_pdf(uploaded_pdf)
        st.session_state.raw_df = df
        
        if not df.empty:
            blachy = df[df["Typ"] == "Blacha"]
            profile = df[df["Typ"] == "Profil"]
            
            st.session_state.form_w_profil = float(profile["Waga całk. [T]"].sum())
            st.session_state.form_w_blacha = float(blachy["Waga całk. [T]"].sum())
            st.session_state.form_qty_profil = int(profile["Sztuk łącznie"].sum())
            st.session_state.form_qty_blacha = int(blachy["Sztuk łącznie"].sum())
            st.session_state.form_weld_mb = float(blachy["Spoina [mb]"].sum())
            st.session_state.form_ass_pcs = int(df["Ilość zespołów"].max())
            st.sidebar.success(f"Odczytano pozycji: {len(df)}")
        else:
            st.sidebar.error("Nie znaleziono pozycji materiałowych w warstwie tekstowej PDF.")

if not st.session_state.raw_df.empty:
    st.subheader("📋 Rozpoznane elementy z rysunków Tekla")
    st.dataframe(st.session_state.raw_df, use_container_width=True)

st.markdown("### 📝 Dane zbiorcze do wyceny")
col1, col2 = st.columns(2)

with col1:
    total_w_profil = st.number_input("Tonaż profili [T]", value=st.session_state.form_w_profil, format="%.3f")
    total_w_blacha = st.number_input("Tonaż blach [T]", value=st.session_state.form_w_blacha, format="%.3f")
    qty_profil_pcs = st.number_input("Ilość sztuk profili", value=st.session_state.form_qty_profil)
with col2:
    qty_blacha_pcs = st.number_input("Ilość sztuk blach", value=st.session_state.form_qty_blacha)
    total_weld_mb = st.number_input("Długość spoin z obwodów blach [mb]", value=st.session_state.form_weld_mb, format="%.2f")
    total_ass_pcs = st.number_input("Liczba el. wysyłkowych (Zespołów)", value=st.session_state.form_ass_pcs)

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
