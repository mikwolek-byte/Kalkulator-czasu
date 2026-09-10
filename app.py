import streamlit as st
import json
from pydantic import BaseModel, Field, ValidationError

# Konfiguracja strony Streamlit musi być pierwszym wywołaniem
st.set_page_config(
    page_title="Kalkulator Pracochłonności Produkcji",
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
    """Model danych wejściowych z wbudowaną walidacją (brak ujemnych wartości)."""
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
    """Silnik wykonujący obliczenia logiki biznesowej."""
    
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
        
        # Zabezpieczenie przed dzieleniem przez zero
        rbg_per_ton = round(total_rbg / total_tons, 2) if total_tons > 0 else 0.0

        return CalculationResult(
            t_prep=t_prep,
            t_fit=t_fit,
            t_weld=t_weld,
            t_log_internal=round(t_log_internal, 2),
            t_log_loading=round(t_log_loading, 2),
            t_log_total=t_log_total,
            total_rbg=total_rbg,
            total_tons=total_tons,
            rbg_per_ton=rbg_per_ton
        )

def main():
    st.title("🏭 Kalkulator Pracochłonności Produkcji")
    st.markdown("Narzędzie ofertowe dla Działu Handlowego.")

    # Pasek boczny na zmienne konfiguracyjne ("Panel Administratora")
    with st.sidebar:
        st.header("⚙️ Panel Administratora")
        st.markdown("Stałe technologiczne (zmienne globalne).")
        
        conf_prep_profil = st.number_input("Wydajność cięcia/wiercenia [rbg/t]", value=5.0, step=0.5)
        conf_prep_blacha = st.number_input("Wydajność wypalania blach [rbg/t]", value=50.0, step=1.0)
        st.divider()
        conf_fit_profil = st.number_input("Czas pasowania profilu [min/szt]", value=20.0, step=1.0)
        conf_fit_blacha = st.number_input("Czas pasowania blachy [min/szt]", value=7.0, step=0.5)
        conf_multiplier = st.number_input("Współczynnik trudności (mnożnik)", value=2.0, step=0.1)
        st.divider()
        conf_weld_min_mb = st.number_input("Czas spawania do a=5mm [min/mb]", value=20.0, step=1.0)
        st.divider()
        conf_log_internal = st.number_input("Transport wewnętrzny [min/szt]", value=30.0, step=1.0)
        conf_log_loading = st.number_input("Załadunek na naczepę [min/szt]", value=10.0, step=1.0)

        # Inicjalizacja konfiguracji na podstawie wejść z paska bocznego
        config = AppConfig(
            conf_prep_profil=conf_prep_profil,
            conf_prep_blacha=conf_prep_blacha,
            conf_fit_profil=conf_fit_profil,
            conf_fit_blacha=conf_fit_blacha,
            conf_multiplier=conf_multiplier,
            conf_weld_min_mb=conf_weld_min_mb,
            conf_log_internal=conf_log_internal,
            conf_log_loading=conf_log_loading
        )

    st.header("📝 Dane wejściowe zapytania (RFQ)")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Masy [tony]")
        total_w_profil = st.number_input("Łączna masa profilów (TOTAL_W_PROFIL)", value=60.792, format="%.3f")
        total_w_blacha = st.number_input("Łączna masa blach (TOTAL_W_BLACHA)", value=11.342, format="%.3f")
        
        st.subheader("Ilości sztuk")
        qty_profil_pcs = st.number_input("Liczba sztuk profilów (QTY_PROFIL_PCS)", value=746, step=1)
        qty_blacha_pcs = st.number_input("Liczba sztuk blach (QTY_BLACHA_PCS)", value=2612, step=1)

    with col2:
        st.subheader("Spawanie i Wysyłka")
        total_weld_mb = st.number_input("Długość spoin w [mb] (TOTAL_WELD_MB)", value=1464.0, format="%.1f")
        total_ass_pcs = st.number_input("Liczba el. wysyłkowych (TOTAL_ASS_PCS)", value=708, step=1)

    st.markdown("---")
    if st.button("🚀 Oblicz pracochłonność", type="primary", use_container_width=True):
        try:
            # Walidacja danych
            input_data = ProductionData(
                total_w_profil=total_w_profil,
                total_w_blacha=total_w_blacha,
                qty_profil_pcs=qty_profil_pcs,
                qty_blacha_pcs=qty_blacha_pcs,
                total_weld_mb=total_weld_mb,
                total_ass_pcs=total_ass_pcs
            )
            
            # Uruchomienie obliczeń
            calculator = ProductionCalculator(config)
            result = calculator.calculate(input_data)

            # Wyświetlanie wyników w ładnych kontenerach
            st.header("📊 Wyniki Globalne")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("CAŁKOWITY BUDŻET", f"{result.total_rbg:.2f} rbg", help="Suma wszystkich czasów cząstkowych")
            m2.metric("ŁĄCZNY TONAŻ", f"{result.total_tons:.2f} ton", help="Masa profili i blach")
            m3.metric("WSKAŹNIK OFERTOWY", f"{result.rbg_per_ton:.2f} rbg/tonę", help="Stosunek budżetu do tonażu")

            st.subheader("Szczegółowe rozbicie czasu")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Czas przygotowania", f"{result.t_prep:.2f} rbg")
            r2.metric("Czas składania", f"{result.t_fit:.2f} rbg")
            r3.metric("Czas spawania", f"{result.t_weld:.2f} rbg")
            r4.metric("Czas logistyki", f"{result.t_log_total:.2f} rbg", 
                      delta=f"Wewn: {result.t_log_internal:.2f}, Zał: {result.t_log_loading:.2f}", delta_color="off")
            
            # Przycisk do pobrania JSONa (eksport dla innych systemów)
            st.markdown("---")
            result_json = result.model_dump_json(indent=4)
            st.download_button(
                label="💾 Pobierz raport (JSON)",
                data=result_json,
                file_name="wynik_kalkulacji.json",
                mime="application/json"
            )

        except ValidationError as e:
            st.error("Wystąpił błąd walidacji danych. Sprawdź, czy nie wprowadzono wartości ujemnych.")
            st.exception(e)

if __name__ == "__main__":
    main()