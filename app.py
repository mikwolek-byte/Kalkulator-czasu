import streamlit as st
import pandas as pd
import numpy as np
import io
import re

st.set_page_config(page_title="Analizator BOM - Konstrukcje Stalowe", layout="wide", page_icon="🏗️")

# Definicja słowników słów kluczowych do automatycznego mapowania kolumn (PL, EN, DE)
KEYWORDS = {
    'assembly': ['pozycja', 'assembly', 'mark', 'baugruppe', 'nr', 'numer', 'pos', 'podzespół'],
    'name': ['nazwa', 'name', 'teil', 'opis', 'description', 'bezeichnung', 'element', 'part'],
    'profile': ['profil', 'type', 'typ', 'querschnitt', 'kształtownik', 'przekrój', 'wymiar'],
    'qty': ['szt', 'ilość', 'qty', 'quantity', 'menge', 'stk', 'anzahl', 'sztuka', 'sztuk'],
    'length': ['długość', 'length', 'länge', 'dlugosc', 'dl', 'dł'],
    'mass_total': ['masa całkowita', 'waga całkowita', 'total mass', 'total weight', 'gesamtgewicht', 'ciężar całkowity', 'masa', 'waga', 'mass', 'gewicht']
}

def clean_numeric(val):
    """
    Czyści i formatuje wartości liczbowe z Excela.
    Zamienia przecinki na kropki, usuwa białe znaki i konwertuje do float.
    """
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip().replace(',', '.')
    # Ekstrakcja samej liczby, jeśli są jakieś znaki (np. "12 kg")
    match = re.search(r'[-+]?\d*\.\d+|\d+', val)
    return float(match.group()) if match else 0.0

def categorize_element(row, name_col, profile_col):
    """
    Kategoryzuje element na podstawie nazwy i profilu.
    Główny podział: Blacha (Plate) vs Profil (Profile).
    """
    text_to_check = f"{str(row.get(name_col, '')).lower()} {str(row.get(profile_col, '')).lower()}"
    plate_keywords = ['blacha', 'pl', 'blech', 'plate', 'sheet', 'flach', 'bl']
    
    # Sprawdzanie czy jakiekolwiek słowo kluczowe blachy występuje w tekście
    if any(kw in text_to_check.split() or kw in text_to_check for kw in plate_keywords):
        return 'Blacha'
    
    # Jeżeli nie rozpoznamy blachy, traktujemy jako Profil kształtowy
    return 'Profil'

def auto_detect_columns(df_columns):
    """
    Przeszukuje nagłówki Excela i proponuje mapowanie do wymaganych kolumn logiki biznesowej.
    """
    mapped = {k: None for k in KEYWORDS.keys()}
    for k, keywords in KEYWORDS.items():
        for col in df_columns:
            # Porównanie bez uwzględniania wielkości liter i zbędnych spacji
            col_lower = col.lower().strip()
            if any(kw in col_lower for kw in keywords) and mapped[k] is None:
                mapped[k] = col
                break
    return mapped

def process_bom_data(df, mapped_cols):
    """
    Wykonuje główną logikę algorytmów obliczeniowych zgodnie z podanymi regułami.
    """
    # 1. Tworzymy kopię i wczytujemy zabezpieczone kolumny
    processed_df = df.copy()
    
    c_asm = mapped_cols['assembly']
    c_name = mapped_cols['name']
    c_prof = mapped_cols['profile']
    c_qty = mapped_cols['qty']
    c_len = mapped_cols['length']
    c_mass = mapped_cols['mass_total']

    # 2. Czyszczenie i konwersja danych numerycznych
    processed_df['Qty_Clean'] = processed_df[c_qty].apply(clean_numeric)
    processed_df['Len_Clean'] = processed_df[c_len].apply(clean_numeric)
    processed_df['Mass_Clean'] = processed_df[c_mass].apply(clean_numeric)

    # 3. Rozpoznanie typu elementu
    processed_df['Kategoria'] = processed_df.apply(lambda r: categorize_element(r, c_name, c_prof), axis=1)

    # 4. Detekcja Profilu Głównego (Największa waga i długość w zespole)
    processed_df['Main_Profile'] = False
    
    # Grupowanie po numerze pozycji/podzespołu (obsługa NaN poprzez wypełnienie 'BRAK_ZESPOLU')
    processed_df[c_asm] = processed_df[c_asm].fillna('BRAK_ZESPOLU').astype(str)
    
    for asm_name, group in processed_df.groupby(c_asm):
        # Wyodrębnij tylko profile
        profiles = group[group['Kategoria'] == 'Profil']
        if not profiles.empty:
            # Sortuj malejąco po masie, następnie po długości
            sorted_profiles = profiles.sort_values(by=['Mass_Clean', 'Len_Clean'], ascending=[False, False])
            # Indeks największego profilu zyskuje status True
            main_idx = sorted_profiles.index[0]
            processed_df.at[main_idx, 'Main_Profile'] = True

    # Inicjalizacja kolumn z czasami [w minutach, a potem przeliczenie na R-g (Roboczogodziny)]
    
    # Zmienne pomocnicze
    def calc_assembly(row):
        qty = row['Qty_Clean']
        if row['Kategoria'] == 'Blacha':
            return 14.0 * qty
        elif row['Main_Profile']:
            return 40.0 * qty
        else: # Pozostałe profile
            return 24.0 * qty

    def calc_prep(row):
        # 5 Rg/tonę dla profili, 50 Rg/tonę dla blach.
        mass_tons = row['Mass_Clean'] / 1000.0
        if row['Kategoria'] == 'Blacha':
            return 50.0 * mass_tons # To zwraca od razu R-g
        else:
            return 5.0 * mass_tons # To zwraca od razu R-g

    # Aplikacja logiki
    # Składanie [minuty] -> konwersja do R-g
    processed_df['Składanie [min]'] = processed_df.apply(calc_assembly, axis=1)
    processed_df['Składanie [R-g]'] = processed_df['Składanie [min]'] / 60.0
    
    # Spawanie (Składanie x 2) -> bezpośrednio w R-g
    processed_df['Spawanie [R-g]'] = processed_df['Składanie [R-g]'] * 2.0
    
    # Przygotowanie materiału -> wzór bezpośrednio zwraca R-g
    processed_df['Przygotowanie [R-g]'] = processed_df.apply(calc_prep, axis=1)
    
    # Transport wewnętrzny (30 min/szt bazując na liczbie sztuk) -> konwersja na R-g
    processed_df['Transport [min]'] = processed_df['Qty_Clean'] * 30.0
    processed_df['Transport [R-g]'] = processed_df['Transport [min]'] / 60.0

    # Suma całkowita dla pozycji (Roboczogodziny)
    processed_df['Suma [R-g]'] = (
        processed_df['Składanie [R-g]'] + 
        processed_df['Spawanie [R-g]'] + 
        processed_df['Przygotowanie [R-g]'] + 
        processed_df['Transport [R-g]']
    )

    # Zaokrąglanie wyników dla czytelności (2 miejsca po przecinku)
    rg_cols = ['Składanie [R-g]', 'Spawanie [R-g]', 'Przygotowanie [R-g]', 'Transport [R-g]', 'Suma [R-g]']
    processed_df[rg_cols] = processed_df[rg_cols].round(2)

    return processed_df

def main():
    st.title("🏭 Analizator List Strukturalnych (BOM) Konstrukcji Stalowych")
    st.markdown("""
    Aplikacja przetwarza pliki Excel (BOM) i estymuje czasy roboczogodzin (R-g) dla poszczególnych procesów produkcji.
    Obsługiwane języki kolumn: Polski, Angielski, Niemiecki. 
    """)

    # 1. Wczytanie pliku
    uploaded_file = st.file_uploader("Wgraj plik Excel (Lista materiałowa/BOM)", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            # Wczytywanie bez ustalania konkretnych indeksów - płaska tabela
            df = pd.read_excel(uploaded_file)
            st.success(f"Pomyślnie wczytano plik. Liczba wierszy: {len(df)}")
            
            # Usunięcie całkowicie pustych wierszy i kolumn
            df = df.dropna(how='all', axis=1).dropna(how='all', axis=0)
            
            st.subheader("1. Mapowanie Kolumn")
            st.info("System spróbuje automatycznie dopasować kolumny z Twojego pliku Excel. Sprawdź, czy przypisania są prawidłowe, lub zmień je ręcznie.")
            
            columns = df.columns.tolist()
            detected = auto_detect_columns(columns)
            
            # Zbuduj układ kolumn w interfejsie
            col1, col2, col3 = st.columns(3)
            with col1:
                asm_col = st.selectbox("Pozycja / Podzespół (Assembly/Mark)", ["<Brak>"] + columns, index=columns.index(detected['assembly'])+1 if detected['assembly'] else 0)
                name_col = st.selectbox("Nazwa Elementu (Name/Description)", ["<Brak>"] + columns, index=columns.index(detected['name'])+1 if detected['name'] else 0)
            with col2:
                prof_col = st.selectbox("Profil / Typ (Profile/Type)", ["<Brak>"] + columns, index=columns.index(detected['profile'])+1 if detected['profile'] else 0)
                qty_col = st.selectbox("Ilość (Quantity)", ["<Brak>"] + columns, index=columns.index(detected['qty'])+1 if detected['qty'] else 0)
            with col3:
                len_col = st.selectbox("Długość w mm (Length)", ["<Brak>"] + columns, index=columns.index(detected['length'])+1 if detected['length'] else 0)
                mass_col = st.selectbox("Masa Całkowita w kg (Total Mass)", ["<Brak>"] + columns, index=columns.index(detected['mass_total'])+1 if detected['mass_total'] else 0)

            # Przycisk uruchamiający analizę
            if st.button("🚀 Uruchom Analizę", type="primary", use_container_width=True):
                # Weryfikacja czy użytkownik wskazał najważniejsze kolumny
                required_cols = [asm_col, name_col, prof_col, qty_col, len_col, mass_col]
                if "<Brak>" in required_cols:
                    st.error("Proszę przypisać wszystkie wymagane kolumny powyżej (żadna nie może mieć wartości <Brak>).")
                else:
                    mapped_cols = {
                        'assembly': asm_col, 'name': name_col, 'profile': prof_col, 
                        'qty': qty_col, 'length': len_col, 'mass_total': mass_col
                    }
                    
                    with st.spinner("Przetwarzanie algorytmów i kalkulacja czasów..."):
                        result_df = process_bom_data(df, mapped_cols)
                        
                        st.subheader("2. Wyniki Analizy")
                        
                        # Sekcja wskaźników KPI (Metrics)
                        total_rg = result_df['Suma [R-g]'].sum()
                        total_mass_ton = result_df['Mass_Clean'].sum() / 1000.0
                        total_qty = result_df['Qty_Clean'].sum()
                        
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Łączne Roboczogodziny", f"{total_rg:,.2f} R-g")
                        m2.metric("Łączna Masa", f"{total_mass_ton:,.2f} Ton")
                        m3.metric("Liczba Elementów", f"{total_qty:,.0f} Szt.")
                        m4.metric("Średni czas na Tonę", f"{total_rg/total_mass_ton if total_mass_ton else 0:,.2f} R-g / T")

                        # Podgląd danych (Tabela)
                        st.dataframe(
                            result_df, 
                            use_container_width=True,
                            height=400
                        )

                        # Przygotowanie przycisku do pobrania przetworzonego Excela
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            result_df.to_excel(writer, index=False, sheet_name='Analiza_R-g')
                        buffer.seek(0)

                        st.download_button(
                            label="📥 Pobierz Przetworzony Raport (Excel)",
                            data=buffer,
                            file_name="BOM_Kalkulacja_Rg.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary"
                        )
                        
        except Exception as e:
            st.error(f"Wystąpił błąd podczas analizy pliku. Upewnij się, że przypisane kolumny mają poprawny format. Szczegóły błędu: {e}")

# Punkt wejścia aplikacji
if __name__ == "__main__":
    main()
