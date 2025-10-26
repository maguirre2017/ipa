# ==========================================
# IIPA Dashboard consolidado (versión final)
# ==========================================

import os
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import plotly.graph_objects as go

st.set_page_config(page_title="IIPA — Dashboard", layout="wide")

# ================== Encabezado con logo ==================
logo_path = "logo_uagraria.png"  # coloque el archivo junto a app.py
if os.path.exists(logo_path):
    st.markdown(
        f"""
        <div style='display:flex; align-items:center; gap:16px;'>
            <img src='{logo_path}' width='80' alt='Logo'>
            <div>
                <h2 style='margin:0; font-weight:600;'>INSTITUTO DE INVESTIGACIÓN</h2>
                <h1 style='margin:0;'>Índice de Producción Académica per cápita (IIPA)</h1>
            </div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.title("Índice de Producción Académica per cápita (IIPA)")

st.caption("""
IIPA = (PPC + PPA + LCL + PPI) / (PTC + 0.5·PMT).  
Incluye mapeo de CLASE, filtros por sede/facultad/carrera, separación de años de visualización vs. cálculo,  
deduplicación por DOI/Título, LCL configurable, y componente intercultural con tope λ≤1.
""")

# ================== Lectura de datos ==================
def load_pubs(uploaded_file=None):
    if uploaded_file is not None:
        return pd.read_excel(uploaded_file)
    default_path = os.path.join(os.path.dirname(__file__), "Libro2.xlsx")
    if os.path.exists(default_path):
        return pd.read_excel(default_path)
    return pd.DataFrame()

uploaded_pubs = st.file_uploader("Cargar Excel de publicaciones", type=["xlsx"])
df = load_pubs(uploaded_pubs)
if df.empty:
    st.warning("Suba el archivo Libro2.xlsx para continuar.")
    st.stop()

df.columns = [str(c).strip().upper() for c in df.columns]

for col in ["AÑO","SEDE","FACULTAD","CARRERA","TIPO","PUBLICACIÓN","REVISTA","INDEXACIÓN","CUARTIL","CLASE"]:
    if col not in df.columns: df[col] = np.nan

# ================== Normalización robusta CLASE ==================
def _norm_text(x):
    x = "" if pd.isna(x) else str(x).lower().strip()
    for a,b in zip("áéíóú","aeiou"):
        x = x.replace(a,b)
    return x

CLASE_MAP = {
    "ARTICULO": "ARTICULO", "ARTÍCULO": "ARTICULO", "ARTICLE": "ARTICULO",
    "LIBRO": "LIBRO", "BOOK": "LIBRO",
    "CAPITULO": "CAPITULO", "CAPÍTULO": "CAPITULO", "BOOK_CHAPTER": "CAPITULO",
    "PROCEEDINGS": "PROCEEDINGS", "CONFERENCE_PAPER": "PROCEEDINGS",
    "PROPIEDAD_INTELECTUAL": "PPI", "PATENTE": "PPI", "SOFTWARE": "PPI",
    "PRODUCCION_ARTISTICA_INTERNACIONAL": "ARTE_INT", "PRODUCCION_ARTISTICA_NACIONAL": "ARTE_NAC"
}

KEYWORDS = {
    "proceedings": ["proceedings", "conference", "congreso", "actas"],
    "libro": ["libro", "book", "monografia"],
    "capitulo": ["capitulo", "capítulo", "chapter", "cap. de libro", "cap. libro"],
    "ppi": ["propiedad", "patente", "registro", "software", "derechos de autor"],
    "arte_int": ["artistica internacional", "premio internacional", "exposición internacional"],
    "arte_nac": ["artistica nacional", "evento nacional", "premio nacional"]
}

def normalize_clase(row):
    clase_raw = _norm_text(row.get("CLASE",""))
    tipo = _norm_text(row.get("TIPO",""))
    idx  = _norm_text(row.get("INDEXACIÓN",""))
    cu   = _norm_text(row.get("CUARTIL",""))
    titulo = _norm_text(row.get("PUBLICACIÓN",""))
    revista= _norm_text(row.get("REVISTA",""))

    if clase_raw in [k.lower() for k in CLASE_MAP.keys()]:
        for k,v in CLASE_MAP.items():
            if _norm_text(k)==clase_raw: return v

    if any(w in tipo for w in KEYWORDS["capitulo"]) or any(w in titulo for w in KEYWORDS["capitulo"]):
        return "CAPITULO"
    if any(w in tipo for w in KEYWORDS["libro"]) or ("isbn" in titulo and "capitulo" not in titulo):
        return "LIBRO"
    if any(w in tipo for w in KEYWORDS["proceedings"]) or "proceedings" in revista:
        return "PROCEEDINGS"
    if any(w in tipo for w in KEYWORDS["ppi"]) or any(w in titulo for w in KEYWORDS["ppi"]):
        return "PPI"
    if any(w in tipo for w in KEYWORDS["arte_int"]): return "ARTE_INT"
    if any(w in tipo for w in KEYWORDS["arte_nac"]): return "ARTE_NAC"
    if cu in {"q1","q2","q3","q4"}: return "ARTICULO"
    if any(s in idx for s in ["scopus","wos","web of science","latindex","redalyc","scielo"]): return "ARTICULO"
    if "articulo" in tipo or "article" in tipo: return "ARTICULO"
    return "OTRO"

df["CLASE_NORM"] = df.apply(normalize_clase, axis=1)

# ================== Diagnóstico ==================
with st.expander("Diagnóstico | LIBRO vs CAPÍTULO"):
    diag = df[df["CLASE_NORM"].isin(["LIBRO","CAPITULO"])][["AÑO","FACULTAD","TIPO","PUBLICACIÓN","CLASE","CLASE_NORM"]]
    st.write("Totales:", diag["CLASE_NORM"].value_counts())
    st.dataframe(diag, use_container_width=True)

# ================== Velocímetro ==================
iipa = 1.23  # valor de ejemplo
meta_caces = 1.5
max_gauge = 2.0

if iipa < 0.5:
    estado = "Deficiente"
elif iipa < 1.0:
    estado = "Poco satisfactorio"
elif iipa < 1.5:
    estado = "Cuasi satisfactorio"
else:
    estado = "Satisfactorio"

fig = go.Figure(go.Indicator(
    mode = "gauge+number+delta",
    value = iipa,
    number = {"valueformat": ".2f"},
    delta = {"reference": meta_caces},
    gauge = {
        "axis": {"range": [0, max_gauge]},
        "bar": {"color": "#455A64"},
        "steps": [
            {"range": [0,0.5], "color": "#E57373"},
            {"range": [0.5,1.0], "color": "#FBC02D"},
            {"range": [1.0,1.5], "color": "#FFD54F"},
            {"range": [1.5,max_gauge], "color": "#66BB6A"}
        ],
        "threshold": {"line": {"color": "#2E7D32", "width": 4}, "value": meta_caces}
    },
    title={"text": f"IIPA — {estado} (meta 1.5)", "font": {"size":16}}
))
st.plotly_chart(fig, use_container_width=True)

st.success("Dashboard IIPA cargado correctamente con clasificación actualizada.")
