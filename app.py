import os
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import plotly.graph_objects as go

# ================== Config general ==================
st.set_page_config(page_title="IIPA — Dashboard", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"]  { font-family: "Inter", system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
</style>
""", unsafe_allow_html=True)

# ================== Encabezado con logo ==================
logo_path = "logo_uagraria.png"  # coloque este archivo junto a app.py
if os.path.exists(logo_path):
    st.markdown(
        f"""
        <div style='display:flex; align-items:center; gap:15px;'>
            <img src='{logo_path}' width='80' alt='Logo'>
            <div>
                <h2 style='margin:0; font-weight:600;'>INSTITUTO DE INVESTIGACIÓN</h2>
                <h1 style='margin:0;'>Índice de Producción Académica (IP)</h1>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.markdown("<h2 style='margin:0;'>INSTITUTO DE INVESTIGACIÓN</h2>", unsafe_allow_html=True)
    st.title("Índice de Producción Académica (IP)")

st.caption("""
IIPA = (PPC + PPA + LCL + PPI) / (PTC + 0.5·PMT).
Incluye mapeo de CLASE, filtros por sede/facultad/carrera, separación de años de visualización vs. cálculo,
deduplicación por DOI/Título, LCL configurable, y componente intercultural con tope λ≤1.
""")

# ================== Carga de datos ==================
def load_pubs(uploaded_file=None):
    if uploaded_file is not None:
        return pd.read_excel(uploaded_file)
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

df.columns = [str(c).strip().upper() for c in df.columns]

for col in ["AÑO","SEDE","FACULTAD","CARRERA","TIPO","PUBLICACIÓN","REVISTA","FECHA","DOI","URL","CUARTIL","INDEXACIÓN","CLASE","TOTAL_CAPITULOS","INTERCULTURAL"]:
    if col not in df.columns:
        df[col] = np.nan

df["AÑO"] = pd.to_numeric(df["AÑO"], errors="coerce").astype("Int64")
if "FECHA" in df.columns:
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")

# ================== Normalización robusta de CLASE ==================
def _norm_text(x: str) -> str:
    x = "" if pd.isna(x) else str(x)
    x = x.strip().lower()
    x = (x
         .replace("á","a").replace("é","e").replace("í","i")
         .replace("ó","o").replace("ú","u"))
    return x

CLASE_MAP = {
    "ARTICULO": "ARTICULO", "ARTÍCULO": "ARTICULO", "ARTICLE": "ARTICULO",
    "LIBRO": "LIBRO", "BOOK": "LIBRO",
    "CAPITULO": "CAPITULO", "CAPÍTULO": "CAPITULO", "BOOK_CHAPTER": "CAPITULO",
    "PROCEEDINGS": "PROCEEDINGS", "CONFERENCE_PAPER": "PROCEEDINGS",
    "PROPIEDAD_INTELECTUAL": "PPI", "PATENTE": "PPI", "REGISTRO": "PPI", "SOFTWARE REGISTRADO": "PPI",
    "PRODUCCION_ARTISTICA_INTERNACIONAL": "ARTE_INT", "PRODUCCIÓN_ARTÍSTICA_INTERNACIONAL": "ARTE_INT",
    "PRODUCCION_ARTISTICA_NACIONAL": "ARTE_NAC", "PRODUCCIÓN_ARTÍSTICA_NACIONAL": "ARTE_NAC",
}
KEYWORDS = {
    "proceedings": ["proceedings", "conference", "congreso", "actas", "proc.", "proceeding"],
    "libro": ["libro", "book", "monografia", "monografía"],
    "capitulo": ["capitulo", "capítulo", "chapter", "cap. de libro", "cap. libro", "book chapter"],
    "ppi": ["propiedad", "patente", "registro", "software", "derechos de autor"],
    "arte_int": ["artistica internacional", "exhibicion internacional", "premio internacional", "exposición internacional"],
    "arte_nac": ["artistica nacional", "evento nacional", "premio nacional", "exposición nacional"],
}

def normalize_clase(row) -> str:
    clase_raw = _norm_text(row.get("CLASE",""))
    tipo      = _norm_text(row.get("TIPO",""))
    idx       = _norm_text(row.get("INDEXACIÓN",""))
    cu        = _norm_text(row.get("CUARTIL",""))
    titulo    = _norm_text(row.get("PUBLICACIÓN",""))
    revista   = _norm_text(row.get("REVISTA",""))

    # 0) Respete mapeo directo si coincide
    if clase_raw:
        for k, v in CLASE_MAP.items():
            if _norm_text(k) == clase_raw:
                return v

    # 1) CAPÍTULO (prioridad)
    if any(w in tipo for w in KEYWORDS["capitulo"]) or any(w in titulo for w in KEYWORDS["capitulo"]):
        return "CAPITULO"

    # 2) LIBRO
    if any(w in tipo for w in KEYWORDS["libro"]) or ("isbn" in titulo and "capitulo" not in titulo):
        return "LIBRO"

    # 3) PROCEEDINGS
    if any(w in tipo for w in KEYWORDS["proceedings"]) or "proceedings" in revista:
        return "PROCEEDINGS"

    # 4) PPI
    if any(w in tipo for w in KEYWORDS["ppi"]) or any(w in titulo for w in KEYWORDS["ppi"]):
        return "PPI"

    # 5) ARTE
    if any(w in tipo for w in KEYWORDS["arte_int"]) or "bienal" in titulo:
        return "ARTE_INT"
    if any(w in tipo for w in KEYWORDS["arte_nac"]):
        return "ARTE_NAC"

    # 6) ARTÍCULO (por cuartil/indexación)
    if cu in {"q1","q2","q3","q4"}:
        return "ARTICULO"
    if any(s in idx for s in ["scopus","wos","web of science","latindex","redalyc","scielo"]):
        return "ARTICULO"
    if "articulo" in tipo or "artículo" in tipo or "article" in tipo:
        return "ARTICULO"

    return "OTRO"

# Forzar reclasificación con lógica nueva
df["CLASE_NORM"] = df.apply(normalize_clase, axis=1)

# ================== Parámetros y filtros ==================
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
    denom_year = st.selectbox("Año denominador (PTC + 0.5·PMT)",
                              sorted(year_calc_sel) if year_calc_sel else years_all,
                              index=len(sorted(year_calc_sel))-1 if year_calc_sel else (len(years_all)-1 if years_all else 0))
    dedup = st.checkbox("Deduplicar por DOI/Título (recomendado)", value=True)

    st.subheader("Parámetros LCL (libros y capítulos)")
    usar_total_caps = st.checkbox("Usar TOTAL_CAPITULOS si existe (peso = 1/TOTAL_CAPITULOS)", value=False)
    factor_cap = st.number_input("Factor fijo por capítulo (si no hay TOTAL_CAPITULOS)",
                                 min_value=0.1, max_value=1.0, value=0.25, step=0.05)

    st.subheader("Interculturalidad (artículos)")
    aplicar_intercultural = st.checkbox("Aplicar +0.21 hasta el 21% del total de artículos PPC", value=False)
    intercultural_inc = 0.21

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

fdf_vis  = apply_filters(df, year_vis_sel,  fac_sel, car_sel, tipo_sel, sede_sel)
fdf_calc = apply_filters(df, year_calc_sel, fac_sel, car_sel, tipo_sel, sede_sel)

# ================== Deduplicación ==================
def deduplicate(df_in, by_class=False):
    """
    Deduplica por DOI/Título. Si by_class=True, deduplica por (KEY, CLASE_NORM),
    de modo que un mismo DOI solo cuente una vez dentro de cada CLASE.
    """
    if df_in is None or df_in.empty:
        return df_in
    d = df_in.copy()
    d["_DOI"] = d["DOI"].fillna("").astype(str).str.strip().str.lower()
    d["_TIT"] = d["PUBLICACIÓN"].fillna("").astype(str).str.strip().str.lower()
    d["_KEY"] = np.where(d["_DOI"] != "", "doi:" + d["_DOI"], "tit:" + d["_TIT"])
    subset_cols = ["_KEY", "CLASE_NORM"] if by_class else ["_KEY"]
    return d.drop_duplicates(subset=subset_cols)

if dedup:
    # Cálculo: deduplicación global
    fdf_calc = deduplicate(fdf_calc, by_class=False)
    # Visualizaciones: deduplicación por CLASE
    fdf_vis_dedup = deduplicate(fdf_vis, by_class=True)
else:
    fdf_vis_dedup = fdf_vis

# ================== φ / λ para artículos (PPC) ==================
def phi_base_only(row):
    cu = str(row.get("CUARTIL", "")).upper().strip()
    idx = str(row.get("INDEXACIÓN", "")).upper().strip()
    if   cu == "Q1": return 1.0
    elif cu == "Q2": return 0.9
    elif cu == "Q3": return 0.8
    elif cu == "Q4": return 0.7
    else:
        if ("SCOPUS" in idx or "WOS" in idx or "WEB OF SCIENCE" in idx): return 0.6
        elif "LATINDEX" in idx: return 0.2
        elif idx not in ("", "NO REGISTRADO", "NAN"): return 0.5
        else: return 0.0

# PPC: artículos + proceedings (solo indexados/cuatril)
is_article = fdf_calc["CLASE_NORM"].eq("ARTICULO")
is_proc = fdf_calc["CLASE_NORM"].eq("PROCEEDINGS") & (
    fdf_calc["INDEXACIÓN"].str.contains("SCOPUS|WOS|WEB OF SCIENCE", case=False, na=True) |
    fdf_calc["CUARTIL"].str.contains("Q[1-4]", case=False, na=True)
)
is_ppc = is_article | is_proc

ppc_rows = fdf_calc.loc[is_ppc].copy()
ppc_rows["phi_base"] = ppc_rows.apply(phi_base_only, axis=1)
n_ppc_total = int(len(ppc_rows))

ppc_rows["lambda"] = ppc_rows["phi_base"]
n_aplicados, pct_aplicado = 0, 0.0
if aplicar_intercultural and n_ppc_total > 0:
    n_limit = int(np.floor(0.21 * n_ppc_total))
    ppc_rows["gain"] = np.minimum(1.0, ppc_rows["phi_base"] + intercultural_inc) - ppc_rows["phi_base"]
    cands = ppc_rows.sort_values("gain", ascending=False)
    to_apply_idx = cands.index[:n_limit]
    ppc_rows.loc[to_apply_idx, "lambda"] = np.minimum(1.0, ppc_rows.loc[to_apply_idx, "phi_base"] + intercultural_inc)
    n_aplicados = len(to_apply_idx)
    pct_aplicado = (n_aplicados / n_ppc_total * 100.0) if n_ppc_total > 0 else 0.0

ppc = float(ppc_rows["lambda"].sum())

# PPA (arte)
ppa = float(fdf_calc["CLASE_NORM"].eq("ARTE_INT").sum())*1.0 + float(fdf_calc["CLASE_NORM"].eq("ARTE_NAC").sum())*0.9

# LCL (libros + capítulos)
mask_libro = fdf_calc["CLASE_NORM"].eq("LIBRO")
mask_cap   = fdf_calc["CLASE_NORM"].eq("CAPITULO")
libros = float(mask_libro.sum())
if usar_total_caps:
    caps_df = fdf_calc.loc[mask_cap].copy()
    caps_df["_den"] = pd.to_numeric(caps_df["TOTAL_CAPITULOS"], errors="coerce")
    caps_df["_w"]   = 1.0 / caps_df["_den"]
    caps = caps_df["_w"].where(~caps_df["_w"].isna() & np.isfinite(caps_df["_w"]), other=float(factor_cap)).sum()
else:
    caps = float(mask_cap.sum()) * float(factor_cap)
lcl = libros + caps

# PPI
ppi = float(fdf_calc["CLASE_NORM"].eq("PPI").sum())

numerador_total = ppc + ppa + lcl + ppi

# ================== Denominador ==================
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

# ================== KPIs ==================
c1, c2, c3, c4 = st.columns(4)
c1.metric("PPC (artículos ponderados)", f"{ppc:.2f}")
c2.metric("PPA (artística)", f"{ppa:.2f}")
c3.metric("LCL + PPI", f"{(lcl+ppi):.2f}")
c4.metric("Numerador total", f"{numerador_total:.2f}")

c5, c6, c7 = st.columns(3)
c5.metric("PTC", f"{int(PTC_sum)}")
c6.metric("PMT", f"{int(PMT_sum)}")
c7.metric("IIPA", f"{iipa:.3f}" if not np.isnan(iipa) else "—")

st.caption(f"Periodo (cálculo): {sorted(set(year_calc_sel))} | Año denominador: {denom_year} | Deduplicación: {'Sí' if dedup else 'No'}")
st.caption(f"Visualización deduplicada por CLASE: {'Sí' if dedup else 'No'}")
st.caption(f"LCL = LIBROS ({int(libros)}) + CAPÍTULOS ({'1/TOTAL_CAPITULOS' if usar_total_caps else f'factor fijo = {factor_cap:.2f}'}).")
if aplicar_intercultural:
    st.caption(f"Interculturalidad aplicada a {n_aplicados} de {n_ppc_total} artículos PPC ({pct_aplicado:.1f}% del total; tope 21%).")
else:
    st.caption("Interculturalidad: no aplicada.")

# ================== Visualización (paleta verde) ==================
st.divider()
st.subheader("Exploración de publicaciones")

palette_verde = ["#004D40", "#00796B", "#2E7D32", "#66BB6A", "#A5D6A7"]
color_scale = alt.Scale(range=palette_verde)

# --- Publicaciones por año ---
by_year = fdf_vis_dedup.groupby("AÑO").size().reset_index(name="Publicaciones")
bars_year = (
    alt.Chart(by_year).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
    .encode(
        x=alt.X("AÑO:O", title="Año"),
        y=alt.Y("Publicaciones:Q", title="N.º de publicaciones"),
        tooltip=["AÑO","Publicaciones"],
        color=alt.Color("AÑO:O", scale=color_scale, legend=None)
    ).properties(title="Publicaciones por año")
)
labels_year = (
    alt.Chart(by_year).mark_text(align="center", baseline="bottom", dy=-5, fontWeight="bold", color="#1B5E20")
    .encode(x="AÑO:O", y="Publicaciones:Q", text="Publicaciones:Q")
)
st.altair_chart(bars_year + labels_year, use_container_width=True)

# --- Tendencia por facultad ---
by_fac_trend = fdf_vis_dedup.groupby(["AÑO","FACULTAD"]).size().reset_index(name="Publicaciones")
highlight = alt.selection_point(on="mouseover", fields=["FACULTAD"], nearest=True, empty=False)
line_fac = (
    alt.Chart(by_fac_trend)
    .mark_line(point=alt.OverlayMarkDef(filled=True, size=70, stroke="#1B5E20"), strokeWidth=3)
    .encode(
        x=alt.X("AÑO:O", title="Año"),
        y=alt.Y("Publicaciones:Q", title="N.º de publicaciones"),
        color=alt.Color("FACULTAD:N", title="Facultad", scale=color_scale),
        opacity=alt.condition(highlight, alt.value(1.0), alt.value(0.25)),
        tooltip=["FACULTAD","AÑO","Publicaciones"]
    )
    .add_params(highlight)
    .properties(title="Tendencia por facultad (deduplicada por CLASE)")
    .configure_axis(grid=True, gridColor="#e0e0e0")
    .configure_view(strokeWidth=0)
)
st.altair_chart(line_fac, use_container_width=True)

# --- Composición relativa por facultad ---
by_fac = fdf_vis_dedup.groupby(["AÑO","FACULTAD"]).size().reset_index(name="Publicaciones")
stacked = (
    alt.Chart(by_fac)
    .mark_bar()
    .encode(
        x=alt.X("FACULTAD:N", title="Facultad"),
        y=alt.Y("sum(Publicaciones):Q", stack="normalize", title="Proporción dentro del año"),
        color=alt.Color("AÑO:O", title="Año", scale=color_scale),
        tooltip=["AÑO","FACULTAD","Publicaciones"]
    ).properties(title="Composición relativa por Facultad (deduplicada por CLASE)")
)
st.altair_chart(stacked, use_container_width=True)

# --- Producción por tipo (libros, capítulos, proceedings, artículos por base) ---
def _norm(s):
    s = "" if pd.isna(s) else str(s)
    s = s.strip().upper()
    return s

def map_tipo_agregado(row):
    clase = _norm(row.get("CLASE_NORM", ""))
    idx   = _norm(row.get("INDEXACIÓN", ""))
    cu    = _norm(row.get("CUARTIL", ""))

    if clase == "LIBRO": return "Libros"
    if clase == "CAPITULO": return "Capítulos de libros"

    if clase == "PROCEEDINGS":
        if "SCOPUS" in idx or "WOS" in idx or "WEB OF SCIENCE" in idx:
            return "Conference proceedings (indexados)"
        else:
            return None

    if clase != "ARTICULO":
        return None

    if "LATINDEX" in idx:
        return "Artículos en Latindex Catálogo"

    if cu in {"Q1","Q2","Q3","Q4"} or "SCOPUS" in idx or "WOS" in idx or "WEB OF SCIENCE" in idx:
        return "Artículos en bases de impacto"

    if idx not in ("", "NO REGISTRADO", "NAN"):
        return "Artículos en bases regionales"

    return None

vis_tipo = fdf_vis_dedup.copy()
vis_tipo["TIPO_AGREGADO"] = vis_tipo.apply(map_tipo_agregado, axis=1)
vis_tipo = vis_tipo.dropna(subset=["TIPO_AGREGADO"])

prod_tipo_year = (
    vis_tipo.groupby(["AÑO", "TIPO_AGREGADO"]).size()
    .reset_index(name="Publicaciones")
    .sort_values(["AÑO", "TIPO_AGREGADO"])
)

orden_categorias = [
    "Libros",
    "Capítulos de libros",
    "Conference proceedings (indexados)",
    "Artículos en bases de impacto",
    "Artículos en bases regionales",
    "Artículos en Latindex Catálogo",
]

chart_tipo = (
    alt.Chart(prod_tipo_year)
    .mark_bar()
    .encode(
        x=alt.X("AÑO:O", title="Año"),
        y=alt.Y("sum(Publicaciones):Q", title="N.º de publicaciones"),
        color=alt.Color("TIPO_AGREGADO:N", title="Tipo", sort=orden_categorias,
                        scale=alt.Scale(range=palette_verde + ["#B2DFDB", "#81C784"])),
        tooltip=["AÑO", "TIPO_AGREGADO", "Publicaciones"]
    )
    .properties(title="Producción por tipo de salida (deduplicada por CLASE)")
)
st.altair_chart(chart_tipo, use_container_width=True)

# --- Heatmap de cuartiles (escala verde) ---
fdf_vis_dedup["_CU"] = fdf_vis_dedup["CUARTIL"].fillna("SIN CUARTIL").str.upper().str.strip()
by_cu = fdf_vis_dedup.groupby(["AÑO","_CU"]).size().reset_index(name="Publicaciones")
heat = (
    alt.Chart(by_cu)
    .mark_rect(stroke="white", strokeWidth=0.5)
    .encode(
        x=alt.X("AÑO:O", title="Año"),
        y=alt.Y("_CU:N", title="Cuartil / Calidad"),
        color=alt.Color("Publicaciones:Q", title="N.º de publicaciones", scale=alt.Scale(scheme="greens")),
        tooltip=["AÑO","_CU","Publicaciones"]
    )
    .properties(title="Intensidad por cuartil y año (Heatmap — deduplicada por CLASE)")
)
st.altair_chart(heat, use_container_width=True)

# ================== Velocímetro CACES ==================
meta_caces = 1.5
avance = float(0 if np.isnan(iipa) else iipa)
max_gauge = 2.0
if avance < 0.5: estado = "Deficiente"
elif avance < 1.0: estado = "Poco satisfactorio"
elif avance < 1.5: estado = "Cuasi satisfactorio"
else: estado = "Satisfactorio"

steps = [
    {"range": [0.0, 0.5], "color": "#E57373"},
    {"range": [0.5, 1.0], "color": "#FBC02D"},
    {"range": [1.0, 1.5], "color": "#FFD54F"},
    {"range": [1.5, max_gauge], "color": "#66BB6A"}
]

fig = go.Figure(go.Indicator(
    mode = "gauge+number+delta",
    value = avance,
    number = {"valueformat": ".2f"},
    delta = {"reference": meta_caces, "increasing": {"color": "#2E7D32"}, "decreasing": {"color": "#C62828"}},
    gauge = {
        "axis": {"range": [0, max_gauge]},
        "bar": {"color": "#455A64"},
        "steps": steps,
        "threshold": {"line": {"color": "#2E7D32", "width": 4}, "thickness": 0.75, "value": meta_caces}
    },
    title = {"text": f"IIPA — {estado} (meta 1.5)", "font": {"size": 16}}
))
st.plotly_chart(fig, use_container_width=True)

# ================== Detalle PPC ==================
if not ppc_rows.empty:
    detail = ppc_rows[["AÑO","SEDE","FACULTAD","CARRERA","PUBLICACIÓN","REVISTA","CUARTIL",
                       "INDEXACIÓN","phi_base","lambda"]].copy()
    detail = detail.rename(columns={"phi_base":"φ (impacto)", "lambda":"λ (final)"})
    detail["INTERCULTURAL_APLICADA"] = detail["λ (final)"] > detail["φ (impacto)"]
    st.subheader("Detalle de PPC (φ base y λ final)")
    st.dataframe(detail, use_container_width=True)

st.divider()
st.caption(
    "Notas: (1) Procede deduplicación global en cálculo y por CLASE en visualización. "
    "(2) Proceedings cuentan en PPC solo si están indexados (Scopus/WoS) o con cuartil. "
    "(3) LCL: libros ponderan 1; capítulos ponderan 1/TOTAL_CAPITULOS si se activa; de lo contrario, factor fijo. "
    "(4) Interculturalidad: opción de +0.21 aplicada hasta el 21% del total de artículos PPC (sin usar columnas del Excel). "
    "(5) Use deduplicación para evitar doble conteo por coautorías."
)
