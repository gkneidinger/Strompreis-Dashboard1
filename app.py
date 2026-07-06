import streamlit as st
import requests
import pandas as pd
import datetime
import altair as alt

# Konfiguration der Seite
st.set_page_config(
    page_title="Strompreis Optimierer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("⚡ Dynamischer Strompreis-Optimierer (EPEX Spot)")
st.markdown("Visualisierung der aktuellen Börsenstrompreise inklusive konfigurierbarer Aufschläge.")

# --- SIDEBAR: PREIS-KONFIGURATION ---
st.sidebar.header("🔧 Tarif-Konfiguration")
st.sidebar.markdown("Passe hier die Aufschläge gemäß deiner Stromrechnung/Netzbetreiber an:")

aufschlag_kwh = st.sidebar.number_input("Energie-Aufschlag (€/kWh)", value=0.015, format="%.4f", step=0.001)
netz_kwh = st.sidebar.number_input("Netzgebühr Arbeitspreis (€/kWh)", value=0.065, format="%.4f", step=0.001)
abgaben_kwh = st.sidebar.number_input("Steuern & Abgaben (€/kWh)", value=0.020, format="%.4f", step=0.001)
ust_satz = st.sidebar.slider("Umsatzsteuer (%)", min_value=0, max_value=25, value=20)

# --- SIDEBAR: E-AUTO LADE-PLANER ---
st.sidebar.markdown("---")
st.sidebar.header("🚗 E-Auto Lade-Planer")
st.sidebar.markdown("Berechne die optimalen Ladezeiten ab der aktuellen Uhrzeit:")
ziel_kwh = st.sidebar.number_input("Gewünschte Lademenge (kWh)", value=60.0, step=5.0)
ladeleistung_kw = st.sidebar.number_input("Ladeleistung Wallbox (kW)", value=11.0, step=1.0)

# --- DATA FETCHING (aWATTar API Österreich) ---
@st.cache_data(ttl=1800)
def fetch_electricity_prices():
    url = "https://api.awattar.at/v1/marketdata"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data['data']
    except Exception as e:
        st.error(f"Fehler beim Laden der API-Daten: {e}")
        return []

raw_data = fetch_electricity_prices()

if raw_data:
    df = pd.DataFrame(raw_data)
    
    # Zeitstempel umrechnen (Europe/Vienna)
    df['Startzeit'] = pd.to_datetime(df['start_timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Europe/Vienna')
    df['Stunde'] = df['Startzeit'].dt.strftime('%H:00')
    df['Datum'] = df['Startzeit'].dt.date
    df['Anzeigezeit'] = df['Startzeit'].dt.strftime('%a %H:%00') # Formatierte Achse z.B. "Mo 22:00"
    
    # Börsenpreis von Eur/MWh in Cent/kWh
    df['Börsenpreis (netto cent/kWh)'] = (df['marketprice'] / 10).round(2)
    
    # Bruttogesamtpreis berechnen
    basis_eur = (df['marketprice'] / 1000)
    netto_gesamt_eur = basis_eur + aufschlag_kwh + netz_kwh + abgaben_kwh
    brutto_gesamt_cent = netto_gesamt_eur * (1 + ust_satz / 100) * 100
    df['Bruttopreis (cent/kWh)'] = brutto_gesamt_cent.round(2)
    
    # --- ZEITFENSTER-FILTER (Heute 00:00 bis Morgen 14:00) ---
    heute_mitternacht = pd.Timestamp.now(tz='Europe/Vienna').normalize()
    morgen_14uhr = heute_mitternacht + pd.Timedelta(days=1, hours=14)
    
    df_anzeige = df[(df['Startzeit'] >= heute_mitternacht) & (df['Startzeit'] <= morgen_14uhr)].sort_values('Startzeit')
    
    # Aktuelle Stunde für Live-Metrik
    jetzt_lokal = pd.Timestamp.now(tz='Europe/Vienna')
    aktuelle_stunde_str = jetzt_lokal.strftime('%H:00')
    row_jetzt = df_anzeige[(df_anzeige['Datum'] == jetzt_lokal.date()) & (df_anzeige['Stunde'] == aktuelle_stunde_str)]
    
    # --- METRIKEN ANZEIGEN ---
    col1, col2, col3 = st.columns(3)
    if not row_jetzt.empty:
        aktueller_preis = row_jetzt['Bruttopreis (cent/kWh)'].values[0]
        col1.metric(label="Aktueller Bruttopreis", value=f"{aktueller_preis} ct/kWh")
    else:
        col1.metric(label="Aktueller Bruttopreis", value="N/A")
        
    if not df_anzeige.empty:
        min_preis = df_anzeige['Bruttopreis (cent/kWh)'].min()
        max_preis = df_anzeige['Bruttopreis (cent/kWh)'].max()
        col2.metric(label="Günstigste Stunde im Zeitraum", value=f"{min_preis} ct/kWh")
        col3.metric(label="Teuerste Stunde im Zeitraum", value=f"{max_preis} ct/kWh")
        
    st.markdown("---")
    
    # --- CHART GENERIEREN (Bis morgen 14:00) ---
    st.subheader("📊 Preisverlauf (Heute 00:00 bis Morgen 14:00)")
    
    chart = alt.Chart(df_anzeige).mark_area(
        line={'color':'#1f77b4'},
        color=alt.Gradient(
            gradient='linear',
            stops=[alt.GradientStop(color='#1f77b4', offset=0),
                   alt.GradientStop(color='transparent', offset=1)],
            x1=1, y1=1, x2=1, y2=0
        )
    ).encode(
        x=alt.X('Anzeigezeit:O', title='Zeitpunkt (Tag & Uhrzeit)', sort=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y('Bruttopreis (cent/kWh):Q', title='Bruttopreis (ct/kWh)'),
        tooltip=['Datum', 'Stunde', 'Börsenpreis (netto cent/kWh)', 'Bruttopreis (cent/kWh)']
    ).properties(height=400)
    
    st.altair_chart(chart, use_container_width=True)
    
    # --- AUTOMATISCHE LADEBERECHNUNG ---
    st.markdown("---")
    st.subheader("🚗 Automatischer Ladefahrplan")
    
    # Nur Stunden ab der aktuellen Uhrzeit für die Ladung berücksichtigen
    df_ab_jetzt = df[df['Startzeit'] >= jetzt_lokal.floor('h')].copy()
    
    if not df_ab_jetzt.empty and ladeleistung_kw > 0:
        # Sortieren nach den günstigsten Preisen zuerst
        df_lade_vorteil = df_ab_jetzt.sort_values('Bruttopreis (cent/kWh)')
        
        geladene_energie = 0.0
        gesamt_kosten_euro = 0.0
        lade_slots = []
        
        for idx, row in df_lade_vorteil.iterrows():
            if geladene_energie >= ziel_kwh:
                break
                
            noch_zu_laden = ziel_kwh - geladene_energie
            # In einer Stunde kann maximal die kW-Leistung als kWh geladen werden
            energie_in_dieser_stunde = min(ladeleistung_kw, noch_zu_laden)
            
            geladene_energie += energie_in_dieser_stunde
            # Kosten berechnen: kWh * cent/kWh / 100 = Euro
            kosten_stunde = (energie_in_dieser_stunde * row['Bruttopreis (cent/kWh)']) / 100
            gesamt_kosten_euro += kosten_stunde
            
            start_zeit = row['Startzeit']
            end_zeit = start_zeit + pd.Timedelta(hours=1)
            
            lade_slots.append({
                "Datum": start_zeit.strftime('%d.%m.%Y'),
                "Von": start_zeit.strftime('%H:00'),
                "Bis": end_zeit.strftime('%H:00'),
                "Geladene Energie (kWh)": round(energie_in_dieser_stunde, 1),
                "Bruttopreis (ct/kWh)": row['Bruttopreis (cent/kWh)'],
                "Kosten in dieser Stunde": f"{kosten_stunde:.2f} €",
                "Timestamp": start_zeit # Für die chronologische Sortierung am Ende
            })
            
        # Ergebnisse anzeigen
        col_res1, col_res2, col_res3 = st.columns(3)
        col_res1.metric("Geplante Lademenge", f"{geladene_energie:.1f} / {ziel_kwh} kWh")
        col_res2.metric("Gesamtkosten der Ladung", f"{gesamt_kosten_euro:.2f} €")
        
        if geladene_energie > 0:
            effektiver_schnitt = (gesamt_kosten_euro * 100) / geladene_energie
            col_res3.metric("Effektiver Ladepreis", f"{effektiver_schnitt:.2f} ct/kWh")
            
        if geladene_energie < ziel_kwh:
            st.warning("⚠️ Nicht genügend zukünftige Preisdaten vorhanden, um die vollen kWh zu planen. Sobald die neuen Spot-Preise (ca. 13-14 Uhr) da sind, verlängert sich der Plan automatisch!")

        # Tabelle chronologisch sortieren, damit man sieht wann man an-/abstecken muss
        df_plan = pd.DataFrame(lade_slots).sort_values("Timestamp")
        df_plan = df_plan.drop(columns=["Timestamp"])
        
        st.markdown("**Empfohlene Ladefenster (chronologisch sortiert):**")
        st.dataframe(df_plan, use_container_width=True, hide_index=True)
        
    else:
        st.info("Ladeplaner inaktiv oder keine zukünftigen Daten verfügbar.")

else:
    st.warning("Es konnten keine aktuellen Preisdaten abgerufen werden.")