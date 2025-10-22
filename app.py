import os
import streamlit as st

# ============ Configuración de OpenAI ============
USE_SDK_V1 = True
client = None
openai = None

api_key = os.getenv("OPENAI_API_KEY")

try:
    from openai import OpenAI  # SDK >= 1.0
    if api_key:
        client = OpenAI(api_key=api_key)
except Exception:
    USE_SDK_V1 = False
    try:
        import openai  # SDK < 1.0
        if api_key:
            openai.api_key = api_key
    except Exception:
        openai = None
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt



# ============ Config general ============

st.set_page_config(page_title="IPA — Dashboard", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"]  {
  font-family: "Inter", system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
</style>
""", unsafe_allow_html=True)


st.title("Índice de Producción Académica per cápita (IP)")
st.caption("IIPA = (PPC + PPA + LCL + PPI) / (PTC + 0.5·PMT). Incluye mapeo robusto de CLASE, "
           "separación de años de visualización vs. cálculo, deduplicación por DOI/Título y componente intercultural (tope λ≤1).")

# ============ Carga de datos de publicaciones ============
def load_pubs(uploaded_file=None):
    if uploaded_file is not None:
        return pd.read_excel(uploaded_file)
    # Fallback: si existe "Libro2.xlsx" junto a este archivo
    example_path = os.path.join(os.path.dirname(__file__), "Libro2.xlsx")
    if os.path.exists(example_path):
        try:
            return pd.read_excel(example_path, sheet_name=0)
        except Exception:
            return pd.read_excel(example_path)
    return pd.DataFrame()

uploaded_pubs = st.file_uploader("Excel de publicaciones", type=["xlsx"])
df = load_pubs(uploaded_pubs)

if df.empty:
    st.info("No hay datos. Suba su Excel o coloque 'Libro2.xlsx' junto a este archivo.")
    st.stop()

# Normalización de encabezados
df.columns = [str(c).strip().upper() for c in df.columns]

# Asegurar columnas mínimas
for col in ["AÑO","FACULTAD","CARRERA","TIPO","PUBLICACIÓN","REVISTA","FECHA","DOI","URL","CUARTIL","INDEXACIÓN","INTERCULTURAL","CLASE","SEDE"]:
    if col not in df.columns:
        df[col] = np.nan
# Columna opcional para conteo de capítulos por libro
if "TOTAL_CAPITULOS" not in df.columns:
    df["TOTAL_CAPITULOS"] = np.nan

# Tipos y fechas
df["AÑO"] = pd.to_numeric(df["AÑO"], errors="coerce").astype("Int64")
if "FECHA" in df.columns:
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")

# ============ Normalización robusta de CLASE ============
CLASE_MAP = {
    # Artículos científicos
    "ARTICULO": "ARTICULO",
    "ARTÍCULO": "ARTICULO",
    "ARTICULO_CIENTIFICO": "ARTICULO",
    "ARTICLE": "ARTICULO",
    # Proceedings (actas)
    "PROCEEDINGS": "PROCEEDINGS",
    "CONFERENCE_PAPER": "PROCEEDINGS",
    "PAPER CONGRESO": "PROCEEDINGS",
    # Libros y capítulos
    "LIBRO": "LIBRO",
    "BOOK": "LIBRO",
    "CAPITULO": "CAPITULO",
    "CAPÍTULO": "CAPITULO",
    "BOOK_CHAPTER": "CAPITULO",
    # Propiedad intelectual aplicada
    "PROPIEDAD_INTELECTUAL": "PPI",
    "PATENTE": "PPI",
    "REGISTRO": "PPI",
    "SOFTWARE REGISTRADO": "PPI",
    # Producción artística
    "PRODUCCION_ARTISTICA_INTERNACIONAL": "ARTE_INT",
    "PRODUCCIÓN_ARTÍSTICA_INTERNACIONAL": "ARTE_INT",
    "PRODUCCION_ARTISTICA_NACIONAL": "ARTE_NAC",
    "PRODUCCIÓN_ARTÍSTICA_NACIONAL": "ARTE_NAC",
}

KEYWORDS = {
    "proceedings": ["proceedings", "conference", "congreso", "actas"],
    "libro": ["libro", "book"],
    "capitulo": ["capitulo", "capítulo", "chapter"],
    "ppi": ["propiedad", "patente", "registro", "software"],
    "arte_int": ["artistica internacional", "exhibicion internacional", "premio internacional"],
    "arte_nac": ["artistica nacional", "evento nacional", "premio nacional"],
}

def _norm_text(x: str) -> str:
    x = "" if pd.isna(x) else str(x)
    x = x.strip().lower()
    x = x.replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
    return x

def normalize_clase(row) -> str:
    # 1) Mapeo directo por CLASE
    clase_raw = _norm_text(row.get("CLASE",""))
    if clase_raw:
        # Intente match exacto contra el diccionario (sin acentos)
        for k, v in CLASE_MAP.items():
            if _norm_text(k) == clase_raw:
                return v
    # 2) Heurísticas por TIPO/INDEXACIÓN/CUARTIL
    tipo = _norm_text(row.get("TIPO",""))
    idx  = _norm_text(row.get("INDEXACIÓN",""))
    cu   = _norm_text(row.get("CUARTIL",""))

    # Proceedings
    if any(w in tipo for w in KEYWORDS["proceedings"]):
        return "PROCEEDINGS"
    # Libros / capítulos
    if any(w in tipo for w in KEYWORDS["libro"]):
        return "LIBRO"
    if any(w in tipo for w in KEYWORDS["capitulo"]):
        return "CAPITULO"
    # PPI
    if any(w in tipo for w in KEYWORDS["ppi"]):
        return "PPI"
    # Arte
    if any(w in tipo for w in KEYWORDS["arte_int"]):
        return "ARTE_INT"
    if any(w in tipo for w in KEYWORDS["arte_nac"]):
        return "ARTE_NAC"
    # Artículo científico por calidad/indexación
    if cu in {"q1","q2","q3","q4"} or any(s in idx for s in ["scopus","wos","web of science","latindex"]):
        return "ARTICULO"
    if "articulo" in tipo or "artículo" in tipo:
        return "ARTICULO"
    return "OTRO"

if "CLASE_NORM" not in df.columns:
    df["CLASE_NORM"] = df.apply(normalize_clase, axis=1)
else:
    # Asegurar consistencia si ya viene cargada
    df["CLASE_NORM"] = df["CLASE_NORM"].astype(str).str.upper().str.strip()

# ============ Parámetros y filtros ============
years_all = sorted([int(y) for y in df["AÑO"].dropna().unique()])
current_year = pd.Timestamp.today().year
default_vis = [y for y in years_all if y >= current_year-3] or years_all

with st.sidebar:
    st.header("Filtros de visualización")
    year_vis_sel = st.multiselect("Años para visualizar", years_all, default=default_vis)
    fac_sel = st.multiselect("Facultad", sorted(df["FACULTAD"].dropna().unique()), default=sorted(df["FACULTAD"].dropna().unique()))
    car_sel = st.multiselect("Carrera", sorted(df["CARRERA"].dropna().unique()), default=sorted(df["CARRERA"].dropna().unique()))
    tipo_sel = st.multiselect("Tipo de publicación", sorted(df["TIPO"].dropna().unique()), default=sorted(df["TIPO"].dropna().unique()))
    sede_sel = st.multiselect("Sede", sorted(df["SEDE"].dropna().unique()), default=sorted(df["SEDE"].dropna().unique()))


    st.divider()
    st.header("Cálculo del IIPA")
    year_calc_sel = st.multiselect("Años del periodo (3 años concluidos)", years_all, default=default_vis)
    denom_year = st.selectbox("Año denominador (PTC + 0.5·PMT)", sorted(year_calc_sel) if year_calc_sel else years_all, index=len(sorted(year_calc_sel))-1 if year_calc_sel else (len(years_all)-1 if years_all else 0))
    dedup = st.checkbox("Deduplicar por DOI/Título (recomendado)", value=True)
    st.subheader("Parámetros LCL (libros y capítulos)")
    usar_total_caps = st.checkbox("Usar TOTAL_CAPITULOS si existe (peso = 1/TOTAL_CAPITULOS)", value=False)
    factor_cap = st.number_input(
    "Factor fijo por capítulo (si no hay TOTAL_CAPITULOS)",
    min_value=0.1, max_value=1.0, value=0.25, step=0.05
    )

    st.subheader("Interculturalidad (para artículos)")
    intercultural_from_col = st.checkbox("Usar columna INTERCULTURAL (True/1) si existe", value=False)
    intercultural_inc = st.slider("Incremento por artículo (0 a 0.21)", min_value=0.0, max_value=0.21, value=0.21, step=0.01)

# Denominador — personal académico
st.sidebar.header("Personal académico (denominador)")
uploaded_staff = st.sidebar.file_uploader("Excel de personal (AÑO, FACULTAD, PTC, PMT)", type=["xlsx"], key="staff")
ptc_manual = st.sidebar.number_input("PTC (manual si no sube Excel)", min_value=0, value=0, step=1)
pmt_manual = st.sidebar.number_input("PMT (manual si no sube Excel)", min_value=0, value=0, step=1)

def apply_filters(base, years, fac, car, tipo, sede):
    f = base.copy()
    if years: f = f[f["AÑO"].isin(years)]
    if fac:   f = f[f["FACULTAD"].isin(fac)]
    if car:   f = f[f["CARRERA"].isin(car)]
    if tipo:  f = f[f["TIPO"].isin(tipo)]
    if sede:  f = f[f["SEDE"].isin(sede)]
    return f

fdf_vis  = apply_filters(df, year_vis_sel, fac_sel, car_sel, tipo_sel, sede_sel)
fdf_calc = apply_filters(df, year_calc_sel, fac_sel, car_sel, tipo_sel, sede_sel)

# Deduplicación por DOI/Título
def deduplicate(df_in):
    if df_in.empty:
        return df_in
    d = df_in.copy()
    d["_DOI"] = d["DOI"].fillna("").astype(str).str.strip().str.lower()
    d["_TIT"] = d["PUBLICACIÓN"].fillna("").astype(str).str.strip().str.lower()
    d["_KEY"] = np.where(d["_DOI"] != "", "doi:" + d["_DOI"], "tit:" + d["_TIT"])
    return d.drop_duplicates(subset=["_KEY"])

if dedup:
    fdf_calc = deduplicate(fdf_calc)

# ============ φ / λ para artículos (PPC) ============
def infer_phi(row):
    cu = str(row.get("CUARTIL", "")).upper().strip()
    idx = str(row.get("INDEXACIÓN", "")).upper().strip()
    # φ base por calidad
    if cu == "Q1": phi = 1.0
    elif cu == "Q2": phi = 0.9
    elif cu == "Q3": phi = 0.8
    elif cu == "Q4": phi = 0.7
    else:
        if ("SCOPUS" in idx or "WOS" in idx or "WEB OF SCIENCE" in idx):
            phi = 0.6  # A
        elif "LATINDEX" in idx:
            phi = 0.2  # L
        elif idx not in ("", "NO REGISTRADO", "NAN"):
            phi = 0.5  # B (regionales)
        else:
            phi = 0.0
    # interculturalidad opcional (+0.21, tope 1)
    inc = 0.0
    if intercultural_from_col and "INTERCULTURAL" in row.index:
        val = str(row.get("INTERCULTURAL","")).strip().lower()
        if val in ("1","true","sí","si","y","yes"):
            inc = intercultural_inc
    lam = min(1.0, phi + inc)
    return lam

# ============ Cálculo de componentes IIPA ============
# PPC: ARTICULO + PROCEEDINGS (solo indexados/cuatril)
is_article = fdf_calc["CLASE_NORM"].eq("ARTICULO")
is_proc = fdf_calc["CLASE_NORM"].eq("PROCEEDINGS") & (
    fdf_calc["INDEXACIÓN"].str.contains("SCOPUS|WOS|WEB OF SCIENCE", case=False, na=True) |
    fdf_calc["CUARTIL"].str.contains("Q[1-4]", case=False, na=True)
)
is_ppc = is_article | is_proc
ppc = fdf_calc.loc[is_ppc].apply(infer_phi, axis=1).sum()

# PPA: arte internacional (1.0) + nacional (0.9)
ppa = float(fdf_calc["CLASE_NORM"].eq("ARTE_INT").sum())*1.0 + float(fdf_calc["CLASE_NORM"].eq("ARTE_NAC").sum())*0.9

# LCL: libros + capítulos (con opción de ponderar capítulos)
mask_libro = fdf_calc["CLASE_NORM"].eq("LIBRO")
mask_cap   = fdf_calc["CLASE_NORM"].eq("CAPITULO")

libros = float(mask_libro.sum())

if usar_total_caps:
    # Pesar cada capítulo como 1 / TOTAL_CAPITULOS; si falta o es inválido, usar factor fijo
    caps_df = fdf_calc.loc[mask_cap].copy()
    caps_df["_den"] = pd.to_numeric(caps_df["TOTAL_CAPITULOS"], errors="coerce")
    caps_df["_w"]   = 1.0 / caps_df["_den"]
    caps = caps_df["_w"].where(~caps_df["_w"].isna() & np.isfinite(caps_df["_w"]), other=float(factor_cap)).sum()
else:
    # Sin TOTAL_CAPITULOS: contar capítulos con un factor fijo
    caps = float(mask_cap.sum()) * float(factor_cap)

lcl = libros + caps


# PPI: propiedad intelectual aplicada
ppi = float(fdf_calc["CLASE_NORM"].eq("PPI").sum())

numerador_total = ppc + ppa + lcl + ppi

# ============ Denominador: PTC + 0.5·PMT (año denominador) ============
def get_denominator():
    if uploaded_staff is not None:
        s = pd.read_excel(uploaded_staff)
        s.columns = [str(c).strip().upper() for c in s.columns]
        for c in ["AÑO","FACULTAD","PTC","PMT"]:
            if c not in s.columns: s[c] = np.nan
        s["AÑO"] = pd.to_numeric(s["AÑO"], errors="coerce").astype("Int64")
        base = s[s["AÑO"] == int(denom_year)]
        PTC = pd.to_numeric(base["PTC"], errors="coerce").fillna(0).sum()
        PMT = pd.to_numeric(base["PMT"], errors="coerce").fillna(0).sum()
        return float(PTC + 0.5*PMT), float(PTC), float(PMT)
    return float(ptc_manual + 0.5*pmt_manual), float(ptc_manual), float(pmt_manual)

den, PTC_sum, PMT_sum = get_denominator()
iipa = (numerador_total / den) if den > 0 else np.nan

# ============ KPIs ============
c1, c2, c3, c4 = st.columns(4)
c1.metric("PPC (artículos ponderados)", f"{ppc:.2f}")
c2.metric("PPA (artística)", f"{ppa:.2f}")
c3.metric("LCL + PPI", f"{(lcl+ppi):.2f}")
c4.metric("Numerador total", f"{numerador_total:.2f}")

c5, c6, c7 = st.columns(3)
c5.metric("PTC", f"{int(PTC_sum)}")
c6.metric("PMT", f"{int(PMT_sum)}")
c7.metric("IIPA", f"{iipa:.3f}" if not np.isnan(iipa) else "—")

st.caption(f"Periodo (años cálculo): {sorted(set(year_calc_sel))} | Año denominador: {denom_year} | Deduplicación: {'Sí' if dedup else 'No'}")
st.caption(
    f"LCL = LIBROS ({int(libros)}) + CAPÍTULOS ("
    f"{'1/TOTAL_CAPITULOS' if usar_total_caps else f'factor fijo = {factor_cap:.2f}'})."
)


# ============ Visualización (sobre fdf_vis) ============
st.divider()
st.subheader("Exploración de publicaciones (visualización)")
# Paleta (puede cambiar "goldgreen" por otra: 'viridis', 'blues', 'redblue', etc.)
color_scale = alt.Scale(scheme="tableau10")  # Alternativas: "category10", "dark2", "set2"


by_year = fdf_vis.groupby("AÑO").size().reset_index(name="Publicaciones")

bars_year = alt.Chart(by_year).mark_bar().encode(
    x=alt.X("AÑO:O", title="Año"),
    y=alt.Y("Publicaciones:Q", title="N.º de publicaciones"),
    tooltip=["AÑO","Publicaciones"],
    color=alt.value("#2E7D32")  # color fijo (verde) o use color_scale
)

labels_year = alt.Chart(by_year).mark_text(
    align="center", baseline="bottom", dy=-5
).encode(
    x="AÑO:O",
    y="Publicaciones:Q",
    text="Publicaciones:Q"
)

st.altair_chart(
    (bars_year + labels_year).properties(title="Publicaciones por año"),
    use_container_width=True
)
# ======= Gráfico de tendencia por facultad (versión mejorada) =======
by_fac_trend = fdf_vis.groupby(["AÑO","FACULTAD"]).size().reset_index(name="Publicaciones")

highlight = alt.selection_point(on="mouseover", fields=["FACULTAD"], nearest=True, empty=False)

line_fac = alt.Chart(by_fac_trend).mark_line(
    point=alt.OverlayMarkDef(filled=True, size=80, stroke="black", strokeWidth=0.5),
    strokeWidth=3
).encode(
    x=alt.X("AÑO:O", title="Año"),
    y=alt.Y("Publicaciones:Q", title="N.º de publicaciones"),
    color=alt.Color("FACULTAD:N", title="Facultad", scale=color_scale),
    opacity=alt.condition(highlight, alt.value(1.0), alt.value(0.2)),
    tooltip=["FACULTAD","AÑO","Publicaciones"]
).add_params(highlight).properties(
    title="Tendencia por facultad (resalte con el ratón)"
).configure_axis(
    grid=True,
    gridColor="#e0e0e0"
).configure_view(
    strokeWidth=0
)

st.altair_chart(line_fac, use_container_width=True)



by_fac = fdf_vis.groupby(["AÑO","FACULTAD"]).size().reset_index(name="Publicaciones")

stacked = alt.Chart(by_fac).mark_bar().encode(
    x=alt.X("FACULTAD:N", title="Facultad"),
    y=alt.Y("sum(Publicaciones):Q", stack="normalize", title="Proporción dentro del año"),
    color=alt.Color("AÑO:O", scale=color_scale),
    tooltip=["AÑO","FACULTAD","Publicaciones"]
).properties(title="Composición relativa por facultad (porcentaje)")

st.altair_chart(stacked, use_container_width=True)


fdf_vis["_CU"] = fdf_vis["CUARTIL"].fillna("SIN CUARTIL").str.upper().str.strip()
by_cu = fdf_vis.groupby(["AÑO","_CU"]).size().reset_index(name="Publicaciones")

heat = alt.Chart(by_cu).mark_rect().encode(
    x=alt.X("AÑO:O", title="Año"),
    y=alt.Y("_CU:N", title="Cuartil / Calidad"),
    color=alt.Color("Publicaciones:Q", title="N.º de publicaciones"),
    tooltip=["AÑO","_CU","Publicaciones"]
).properties(title="Intensidad por cuartil y año (heatmap)")

st.altair_chart(heat, use_container_width=True)

st.caption("Progreso hacia la meta CACES (IIPA ≥ 1.5)")
st.progress( min(1.0, float(0 if np.isnan(iipa) else iipa) / 1.5) )

# Detalle de artículos del periodo de cálculo (λ)
is_ppc_rows = fdf_calc[is_ppc]
if not is_ppc_rows.empty:
    detail = is_ppc_rows[["AÑO","FACULTAD","CARRERA","PUBLICACIÓN","REVISTA","CUARTIL","INDEXACIÓN","INTERCULTURAL","CLASE_NORM"]].copy()
    # φ base solo para referencia (sin incremento intercultural)
    def phi_base(row):
        cu = str(row.get("CUARTIL", "")).upper().strip()
        idx = str(row.get("INDEXACIÓN", "")).upper().strip()
        if cu == "Q1": return 1.0
        if cu == "Q2": return 0.9
        if cu == "Q3": return 0.8
        if cu == "Q4": return 0.7
        if ("SCOPUS" in idx or "WOS" in idx or "WEB OF SCIENCE" in idx): return 0.6
        if "LATINDEX" in idx: return 0.2
        if idx not in ("", "NO REGISTRADO", "NAN"): return 0.5
        return 0.0
    detail["φ (impacto)"] = detail.apply(phi_base, axis=1)
    detail["λ (φ + intercultural, tope 1)"] = is_ppc_rows.apply(infer_phi, axis=1).values
    st.subheader("Detalle de PPC (artículos/proceedings) en el periodo de cálculo")
    st.dataframe(detail, use_container_width=True)

st.divider()

st.caption(
    "Notas: (1) Proceedings cuentan en PPC solo si están indexados (Scopus/WoS) o con cuartil. "
    "(2) LCL: libros ponderan 1; capítulos ponderan 1/TOTAL_CAPITULOS si se activa y existe la columna; "
    f"en caso contrario capítulos ponderan un factor fijo configurable (actual: {factor_cap:.2f}). "
    "(3) Interculturalidad: +0.21 por artículo marcado, tope λ≤1. "
    "(4) Use deduplicación para evitar doble conteo por coautorías."
)



# ============ Consultas en lenguaje natural (IA) ============
st.divider()
st.subheader("Consultas en lenguaje natural (IA)")

# Construir contexto
contexto = {
    "Periodo": list(sorted(set(year_calc_sel))),
    "Denominador": {
        "Año": int(denom_year),
        "PTC": int(PTC_sum),
        "PMT": int(PMT_sum),
        "Valor": float(den) if den > 0 else None,
    },
    "Componentes": {
        "PPC": float(ppc),
        "PPA": float(ppa),
        "LCL": float(lcl),
        "PPI": float(ppi),
    },
    "IIPA": float(iipa) if not np.isnan(iipa) else None,
}

question = st.text_input("Ejemplo: ¿El IIPA supera 1.5 en el periodo seleccionado?")

if st.button("Preguntar a la IA") and question:
    if USE_SDK_V1 and client:
        try:
            resp = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres analista institucional. Responde con precisión usando solo el contexto dado."},
                    {"role": "user", "content": f"Pregunta: {question}\n\nContexto: {contexto}"}
                ],
                temperature=0.1
            )
            st.success(resp.choices[0].message.content)
        except Exception as e:
            st.error(f"Error (SDK v1): {e}")
    elif (not USE_SDK_V1) and openai:
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres analista institucional. Responde con precisión usando solo el contexto dado."},
                    {"role": "user", "content": f"Pregunta: {question}\n\nContexto: {contexto}"}
                ],
                temperature=0.1
            )
            st.success(resp["choices"][0]["message"]["content"])
        except Exception as e:
            st.error(f"Error (SDK legacy): {e}")
    else:
        st.error("No se detecta OPENAI_API_KEY o el paquete openai. Revise 'Secrets' y requirements.")
