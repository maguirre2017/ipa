# ===============================================
# DASHBOARD IIPA - Libro único (Publicaciones + Personal, sin DEDICACIÓN en Excel)
# ===============================================
import os, re
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import plotly.graph_objects as go

# ------------------ Configuración base ------------------
st.set_page_config(page_title="IIPA — Dashboard (Libro único)", layout="wide")

# Tipografía básica (opcional)
st.markdown("""
<style>
html, body, [class*="css"]  {
  font-family: "Inter", system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}
</style>
""", unsafe_allow_html=True)

# ------------------ Encabezado ------------------
LOGO = "logo_uagraria_transparente_final.png"  # si existe en la carpeta, se mostrará
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists(LOGO):
        st.image(LOGO, width=90)
with col_title:
    st.title("Índice de Producción Académica per cápita (IIPA)")
st.caption(
    "Libro Excel único (hojas 'Publicaciones' y 'Personal'). "
    "Deduplicación por DOI/Título atribuida al primer autor. "
    "Interculturalidad aplicada hasta el 21% de los artículos/proceedings (tope λ≤1)."
)

# ------------------ Carga del libro ------------------
uploaded_book = st.file_uploader("Libro Excel único (Publicaciones + Personal)", type=["xlsx"])
if uploaded_book is None:
    st.info("Suba el archivo Excel único con hojas 'Publicaciones' y 'Personal'.")
    st.stop()

xfile = pd.ExcelFile(uploaded_book)
CAND_PUBLIC = {"PUBLICACIONES","PRODUCCION","PRODUCCIÓN","ARTICULOS","ARTÍCULOS","PUBS"}
CAND_STAFF  = {"PERSONAL","STAFF","DOCENTES","ACADEMICO","ACADÉMICO"}

def _cols_upper(df_):
    df_.columns = [str(c).strip().upper() for c in df_.columns]
    return df_

def _find_sheet(xf, candidates, default_idx=None):
    up = {s.strip().upper(): s for s in xf.sheet_names}
    for upname, orig in up.items():
        if upname in candidates:
            return orig
    if default_idx is not None:
        return xf.sheet_names[default_idx]
    return None

sheet_pub = _find_sheet(xfile, CAND_PUBLIC, default_idx=0)
sheet_stf = _find_sheet(xfile, CAND_STAFF, default_idx=None)

df_pub = pd.read_excel(xfile, sheet_name=sheet_pub) if sheet_pub else pd.read_excel(xfile, sheet_name=0)
staff_df = pd.read_excel(xfile, sheet_name=sheet_stf) if sheet_stf else pd.DataFrame()

df_pub  = _cols_upper(df_pub)
if not staff_df.empty:
    staff_df = _cols_upper(staff_df)

# ------------------ Publicaciones: columnas mínimas ------------------
for col in [
    "AÑO","SEDE","FACULTAD","CARRERA","TIPO","PUBLICACIÓN","REVISTA","FECHA",
    "DOI","URL","CUARTIL","INDEXACIÓN","CLASE","TOTAL_CAPITULOS",
    "AUTORES","DOCENTE","DOCENTES","AUTOR"  # por si viene alguno para autores
]:
    if col not in df_pub.columns:
        df_pub[col] = np.nan

df_pub["AÑO"] = pd.to_numeric(df_pub["AÑO"], errors="coerce").astype("Int64")
if "FECHA" in df_pub.columns:
    df_pub["FECHA"] = pd.to_datetime(df_pub["FECHA"], errors="coerce")

# ------------------ Personal: columnas mínimas (sin DEDICACIÓN) ------------------
if not staff_df.empty:
    for col in ["AÑO","DOCENTE","VINCULACION","FACULTAD","CARRERA","SEDE"]:
        if col not in staff_df.columns: staff_df[col] = np.nan

def _norm_txt(x):
    x = "" if pd.isna(x) else str(x)
    x = x.strip().upper()
    x = (x.replace("Á","A").replace("É","E").replace("Í","I").replace("Ó","O").replace("Ú","U"))
    x = " ".join(x.split())
    return x

if not staff_df.empty:
    # Mapear nombres de columnas equivalentes
    if "PROFESOR" in staff_df.columns and "DOCENTE" not in staff_df.columns:
        staff_df["DOCENTE"] = staff_df["PROFESOR"]
    if "NOMBRE" in staff_df.columns and "DOCENTE" not in staff_df.columns:
        staff_df["DOCENTE"] = staff_df["NOMBRE"]
    if "TIPO_VINCULACION" in staff_df.columns and "VINCULACION" not in staff_df.columns:
        staff_df["VINCULACION"] = staff_df["TIPO_VINCULACION"]
    if "TIPO" in staff_df.columns and "VINCULACION" not in staff_df.columns:
        staff_df["VINCULACION"] = staff_df["TIPO"]

    staff_df["DOCENTE_NORM"] = staff_df["DOCENTE"].map(_norm_txt)
    staff_df["VINCULACION"]  = staff_df["VINCULACION"].map(_norm_txt)
    staff_df["AÑO"]          = pd.to_numeric(staff_df["AÑO"], errors="coerce").astype("Int64")
    staff_df.loc[~staff_df["VINCULACION"].isin(["NOMBRAMIENTO","OCASIONAL"]), "VINCULACION"] = np.nan

# ------------------ Normalización de CLASE ------------------
def _norm_str(x):
    x = "" if pd.isna(x) else str(x)
    x = x.strip().lower()
    x = x.replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
    return x

CLASE_MAP = {
    "ARTICULO":"ARTICULO","ARTICLE":"ARTICULO","ARTICULO_CIENTIFICO":"ARTICULO",
    "PROCEEDINGS":"PROCEEDINGS","CONFERENCE_PAPER":"PROCEEDINGS","PAPER CONGRESO":"PROCEEDINGS",
    "LIBRO":"LIBRO","BOOK":"LIBRO",
    "CAPITULO":"CAPITULO","BOOK_CHAPTER":"CAPITULO",
    "PROPIEDAD_INTELECTUAL":"PPI","PATENTE":"PPI","REGISTRO":"PPI","SOFTWARE REGISTRADO":"PPI",
    "PRODUCCION_ARTISTICA_INTERNACIONAL":"ARTE_INT","PRODUCCIÓN_ARTÍSTICA_INTERNACIONAL":"ARTE_INT",
    "PRODUCCION_ARTISTICA_NACIONAL":"ARTE_NAC","PRODUCCIÓN_ARTÍSTICA_NACIONAL":"ARTE_NAC"
}
KEYWORDS = {
    "proceedings":["proceedings","conference","congreso","actas"],
    "libro":["libro","book"],
    "capitulo":["capitulo","capítulo","chapter"],
    "ppi":["propiedad","patente","registro","software"],
    "arte_int":["artistica internacional","exhibicion internacional","premio internacional"],
    "arte_nac":["artistica nacional","evento nacional","premio nacional"],
}

def normalize_clase(row):
    clase_raw = _norm_str(row.get("CLASE",""))
    if clase_raw:
        for k,v in CLASE_MAP.items():
            if _norm_str(k) == clase_raw:
                return v
    tipo = _norm_str(row.get("TIPO",""))
    idx  = _norm_str(row.get("INDEXACIÓN",""))
    cu   = _norm_str(row.get("CUARTIL",""))
    if any(w in tipo for w in KEYWORDS["proceedings"]): return "PROCEEDINGS"
    if any(w in tipo for w in KEYWORDS["libro"]): return "LIBRO"
    if any(w in tipo for w in KEYWORDS["capitulo"]): return "CAPITULO"
    if any(w in tipo for w in KEYWORDS["ppi"]): return "PPI"
    if any(w in tipo for w in KEYWORDS["arte_int"]): return "ARTE_INT"
    if any(w in tipo for w in KEYWORDS["arte_nac"]): return "ARTE_NAC"
    if cu in {"q1","q2","q3","q4"} or any(s in idx for s in ["scopus","wos","web of science","latindex"]): return "ARTICULO"
    if "articulo" in tipo or "artículo" in tipo: return "ARTICULO"
    return "OTRO"

df_pub["CLASE_NORM"] = df_pub.apply(normalize_clase, axis=1)

# ------------------ Primer autor + deduplicación ------------------
autor_cols = ["DOCENTES","DOCENTE","AUTORES","AUTOR","INVESTIGADORES","INVESTIGADOR"]
col_autores = next((c for c in autor_cols if c in df_pub.columns), None)

def split_first_author(s: str) -> str:
    if pd.isna(s): return ""
    s = str(s)
    s = re.sub(r"\s+y\s+", ",", s, flags=re.IGNORECASE)
    parts = re.split(r"[;,/|&]+", s)
    for p in parts:
        t = " ".join(p.strip().split())
        if t: return t
    return ""

df_pub["_DOI"] = df_pub["DOI"].fillna("").astype(str).str.strip().str.lower()
df_pub["_TIT"] = df_pub["PUBLICACIÓN"].fillna("").astype(str).str.strip().str.lower()
df_pub["_KEY"] = np.where(df_pub["_DOI"]!="", "doi:"+df_pub["_DOI"], "tit:"+df_pub["_TIT"])

df_pub["PRIMER_AUTOR"] = df_pub[col_autores].map(split_first_author) if col_autores else ""
df_pub["PRIMER_AUTOR_NORM"] = df_pub["PRIMER_AUTOR"].map(_norm_txt)

# Regla: la publicación deduplicada se atribuye al PRIMER AUTOR
df_pub = (df_pub.sort_values(by=["PRIMER_AUTOR"], ascending=True)
               .drop_duplicates(subset=["_KEY"], keep="first")
               .copy())

# Vincular VINCULACION del primer autor por AÑO desde hoja Personal (si existe)
if not staff_df.empty:
    staff_key = staff_df[["AÑO","DOCENTE","VINCULACION"]].dropna(subset=["DOCENTE"]).copy()
    staff_key["DOCENTE_NORM"] = staff_key["DOCENTE"].map(_norm_txt)
    staff_key["VINCULACION"]  = staff_key["VINCULACION"].map(_norm_txt)

    df_pub = df_pub.merge(
        staff_key[["AÑO","DOCENTE_NORM","VINCULACION"]],
        left_on=["AÑO","PRIMER_AUTOR_NORM"],
        right_on=["AÑO","DOCENTE_NORM"],
        how="left",
        suffixes=("","_STAFF")
    )
    df_pub["VINCULACION_PUB"] = df_pub["VINCULACION"].fillna("SIN VINCULACION")
else:
    df_pub["VINCULACION_PUB"] = "SIN VINCULACION"

# ------------------ Parámetros y filtros (sidebar) ------------------
years_all = sorted([int(y) for y in df_pub["AÑO"].dropna().unique()])
current_year = pd.Timestamp.today().year
default_vis = [y for y in years_all if y >= current_year - 3] or years_all

with st.sidebar:
    st.header("Filtros de visualización")
    year_vis_sel = st.multiselect("Años para visualizar", years_all, default=default_vis)
    fac_sel = st.multiselect("Facultad", sorted(df_pub["FACULTAD"].dropna().unique()),
                             default=sorted(df_pub["FACULTAD"].dropna().unique()))
    car_sel = st.multiselect("Carrera", sorted(df_pub["CARRERA"].dropna().unique()),
                             default=sorted(df_pub["CARRERA"].dropna().unique()))
    tipo_sel = st.multiselect("Tipo de publicación", sorted(df_pub["TIPO"].dropna().unique()),
                              default=sorted(df_pub["TIPO"].dropna().unique()))
    sede_sel = st.multiselect("Sede", sorted(df_pub["SEDE"].dropna().unique()),
                              default=sorted(df_pub["SEDE"].dropna().unique()))

    st.divider()
    st.header("Cálculo del IIPA")
    year_calc_sel = st.multiselect("Años del periodo (3 años concluidos)", years_all, default=default_vis)
    denom_year = st.selectbox(
        "Año denominador (PTC + 0.5·PMT)",
        sorted(year_calc_sel) if year_calc_sel else years_all,
        index=len(sorted(year_calc_sel)) - 1 if year_calc_sel else (len(years_all) - 1 if years_all else 0)
    )
    st.caption("La deduplicación ya se aplicó por DOI/Título y se atribuye al primer autor.")

    # LCL (libros/capítulos)
    st.subheader("Capítulos — factor fijo (si no hay TOTAL_CAPITULOS)")
    factor_cap = st.number_input("Factor fijo por capítulo", min_value=0.1, max_value=1.0, value=0.25, step=0.05)
    usar_total_caps = st.checkbox("Usar TOTAL_CAPITULOS si existe (peso = 1 / TOTAL_CAPITULOS)", value=False)

    # Interculturalidad (21% máximo, sin usar columna del libro)
    intercultural_21 = st.checkbox("Aplicar componente intercultural (hasta 21% de artículos/proceedings)", value=True)

# ------------------ Helpers de filtrado y ponderaciones ------------------
def slice_df(base, years, fac, car, tipo, sede):
    f = base.copy()
    if years: f = f[f["AÑO"].isin(years)]
    if fac:   f = f[f["FACULTAD"].isin(fac)]
    if car:   f = f[f["CARRERA"].isin(car)]
    if tipo:  f = f[f["TIPO"].isin(tipo)]
    if sede:  f = f[f["SEDE"].isin(sede)]
    return f

def phi_base_only(row):
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

def numerador_IIPA(subdf: pd.DataFrame, intercultural_21=True) -> tuple:
    """
    Calcula: PPC (φ y λ con tope y hasta 21%), PPA, LCL, PPI y el numerador total.
    Devuelve: (numerador, ppc_rows, ppa, lcl, ppi, n_aplicados_intercultural)
    """
    # PPC = artículos + proceedings indexados/cuatril
    is_article = subdf["CLASE_NORM"].eq("ARTICULO")
    is_proc = subdf["CLASE_NORM"].eq("PROCEEDINGS") & (
        subdf["INDEXACIÓN"].str.contains("SCOPUS|WOS|WEB OF SCIENCE", case=False, na=True) |
        subdf["CUARTIL"].str.contains("Q[1-4]", case=False, na=True)
    )
    ppc_rows = subdf.loc[is_article | is_proc].copy()
    if ppc_rows.empty:
        return 0.0, ppc_rows.assign(phi_base=[], lambda_=[]), 0.0, 0.0, 0.0, 0

    ppc_rows["phi_base"] = ppc_rows.apply(phi_base_only, axis=1)

    # Aplicación del 21% intercultural (sin usar columna del libro)
    n_total = len(ppc_rows)
    ppc_rows["lambda"] = ppc_rows["phi_base"]
    n_aplicados = 0
    if intercultural_21 and n_total > 0:
        n_limit = int(np.floor(0.21 * n_total))  # hasta 21% de los artículos/proceedings
        # Mayor ganancia donde φ está más lejos de 1.0
        ppc_rows["gain"] = np.minimum(1.0, ppc_rows["phi_base"] + 0.21) - ppc_rows["phi_base"]
        to_apply = ppc_rows.sort_values("gain", ascending=False).index[:n_limit]
        ppc_rows.loc[to_apply, "lambda"] = np.minimum(1.0, ppc_rows.loc[to_apply, "phi_base"] + 0.21)
        n_aplicados = len(to_apply)

    ppc = float(ppc_rows["lambda"].sum())

    # PPA: arte internacional (1.0) + nacional (0.9)
    ppa = float(subdf["CLASE_NORM"].eq("ARTE_INT").sum()) * 1.0 + \
          float(subdf["CLASE_NORM"].eq("ARTE_NAC").sum()) * 0.9

    # LCL: libros + capítulos (con opción de ponderar por TOTAL_CAPITULOS)
    mask_libro = subdf["CLASE_NORM"].eq("LIBRO")
    mask_cap   = subdf["CLASE_NORM"].eq("CAPITULO")
    libros = float(mask_libro.sum())

    if usar_total_caps:
        caps_df = subdf.loc[mask_cap].copy()
        caps_df["_den"] = pd.to_numeric(caps_df["TOTAL_CAPITULOS"], errors="coerce")
        caps_df["_w"]   = 1.0 / caps_df["_den"]
        caps = caps_df["_w"].where(~caps_df["_w"].isna() & np.isfinite(caps_df["_w"]),
                                   other=float(factor_cap)).sum()
    else:
        caps = float(mask_cap.sum()) * float(factor_cap)

    lcl = libros + caps

    # PPI: propiedad intelectual aplicada (conteo unitario)
    ppi = float(subdf["CLASE_NORM"].eq("PPI").sum())

    numerador = ppc + ppa + lcl + ppi
    return numerador, ppc_rows, ppa, lcl, ppi, n_aplicados

# ------------------ Denominador — ingreso manual (PTC/PMT) ------------------
with st.sidebar:
    st.header("Personal académico (denominador)")
    ptc_manual = st.number_input("PTC (Nombramiento + Ocasional)", min_value=0, value=0, step=1)
    pmt_manual = st.number_input("PMT (Nombramiento + Ocasional)", min_value=0, value=0, step=1)

def den_val(ptc, pmt):
    return float(ptc) + 0.5 * float(pmt)

# ------------------ Cálculo IIPA por cohorte (Nombramiento, Ocasional, Total) ------------------
calc_all = slice_df(df_pub, year_calc_sel, fac_sel, car_sel, tipo_sel, sede_sel)
calc_nom = calc_all[calc_all["VINCULACION_PUB"].eq("NOMBRAMIENTO")]
calc_oca = calc_all[calc_all["VINCULACION_PUB"].eq("OCASIONAL")]
calc_tot = calc_all

num_nom, ppc_nom_rows, ppa_nom, lcl_nom, ppi_nom, n_ap_nom = numerador_IIPA(calc_nom, intercultural_21=intercultural_21)
num_oca, ppc_oca_rows, ppa_oca, lcl_oca, ppi_oca, n_ap_oca = numerador_IIPA(calc_oca, intercultural_21=intercultural_21)
num_tot, ppc_tot_rows, ppa_tot, lcl_tot, ppi_tot, n_ap_tot = numerador_IIPA(calc_tot, intercultural_21=intercultural_21)

den_nom = den_val(ptc_manual, pmt_manual) if not calc_nom.empty else den_val(ptc_manual, pmt_manual)
den_oca = den_val(ptc_manual, pmt_manual) if not calc_oca.empty else den_val(ptc_manual, pmt_manual)
den_tot = den_val(ptc_manual, pmt_manual)

iipa_nom = (num_nom / den_nom) if den_nom > 0 else np.nan
iipa_oca = (num_oca / den_oca) if den_oca > 0 else np.nan
iipa_tot = (num_tot / den_tot) if den_tot > 0 else np.nan

# ------------------ KPIs ------------------
c1, c2, c3 = st.columns(3)
c1.metric("IIPA — Nombramiento", f"{iipa_nom:.3f}" if not np.isnan(iipa_nom) else "—",
          help=f"Numerador: {num_nom:.2f} | Den: {den_nom:.2f} | 21% aplicado a {n_ap_nom} artículos.")
c2.metric("IIPA — Ocasional", f"{iipa_oca:.3f}" if not np.isnan(iipa_oca) else "—",
          help=f"Numerador: {num_oca:.2f} | Den: {den_oca:.2f} | 21% aplicado a {n_ap_oca} artículos.")
c3.metric("IIPA — Total", f"{iipa_tot:.3f}" if not np.isnan(iipa_tot) else "—",
          help=f"Numerador: {num_tot:.2f} | Den: {den_tot:.2f} | 21% aplicado a {n_ap_tot} artículos.")

# ------------------ Velocímetros (Plotly) ------------------
def gauge_iipa(valor, titulo):
    max_gauge = 2.0
    if np.isnan(valor): valor = 0.0
    steps = [
        {"range": [0.0, 0.5], "color": "#E57373"},   # Deficiente
        {"range": [0.5, 1.0], "color": "#FBC02D"},   # Poco satisfactorio
        {"range": [1.0, 1.5], "color": "#FFD54F"},   # Cuasi satisfactorio
        {"range": [1.5, max_gauge], "color": "#66BB6A"}  # Satisfactorio
    ]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=float(valor),
        number={"valueformat": ".2f"},
        gauge={
            "axis": {"range": [0, max_gauge]},
            "bar": {"color": "#455A64"},
            "steps": steps,
            "threshold": {"line": {"color": "#2E7D32", "width": 4}, "value": 1.5}
        },
        title={"text": f"{titulo}", "font": {"size": 14}}
    ))
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=220)
    return fig

g1, g2, g3 = st.columns(3)
with g1:
    st.plotly_chart(gauge_iipa(iipa_nom, "IIPA — Nombramiento"), use_container_width=True)
with g2:
    st.plotly_chart(gauge_iipa(iipa_oca, "IIPA — Ocasional"), use_container_width=True)
with g3:
    st.plotly_chart(gauge_iipa(iipa_tot, "IIPA — Total"), use_container_width=True)

st.caption(
    f"Periodo cálculo: {sorted(set(year_calc_sel))} | Año denominador: {denom_year} | "
    f"Intercultural ≤21% aplicado: {'Sí' if intercultural_21 else 'No'}."
)

# ------------------ Visualización (años seleccionados para VISUALIZAR) ------------------
st.divider()
st.subheader("Exploración de publicaciones (visualización)")

vis = df_pub.copy()
vis = vis[vis["AÑO"].isin(year_vis_sel)] if year_vis_sel else vis
vis = vis[vis["FACULTAD"].isin(fac_sel)] if fac_sel else vis
vis = vis[vis["CARRERA"].isin(car_sel)]  if car_sel else vis
vis = vis[vis["TIPO"].isin(tipo_sel)]    if tipo_sel else vis
vis = vis[vis["SEDE"].isin(sede_sel)]    if sede_sel else vis

vis["VINCULACION_PUB"] = vis["VINCULACION_PUB"].fillna("SIN VINCULACION")

# Publicaciones por año (apilado por tipo de vinculación)
by_year_vinc = vis.groupby(["AÑO","VINCULACION_PUB"]).size().reset_index(name="Publicaciones")
chart_year = (
    alt.Chart(by_year_vinc)
      .mark_bar()
      .encode(
          x=alt.X("AÑO:O", title="Año"),
          y=alt.Y("sum(Publicaciones):Q", title="N.º de publicaciones"),
          color=alt.Color("VINCULACION_PUB:N", title="Vinculación",
                          scale=alt.Scale(range=["#2E7D32", "#81C784", "#B0BEC5"])),
          tooltip=["AÑO","VINCULACION_PUB","Publicaciones"]
      )
      .properties(title="Publicaciones por año (por tipo de vinculación)")
)
st.altair_chart(chart_year, use_container_width=True)

# Distribución proporcional por Facultad
by_fac_vinc = vis.groupby(["FACULTAD","VINCULACION_PUB"]).size().reset_index(name="Publicaciones")
chart_fac_prop = (
    alt.Chart(by_fac_vinc)
      .mark_bar()
      .encode(
          x=alt.X("FACULTAD:N", title="Facultad"),
          y=alt.Y("sum(Publicaciones):Q", stack="normalize", title="Proporción dentro del total"),
          color=alt.Color("VINCULACION_PUB:N", title="Vinculación",
                          scale=alt.Scale(range=["#2E7D32", "#81C784", "#B0BEC5"])),
          tooltip=["FACULTAD","VINCULACION_PUB","Publicaciones"]
      )
      .properties(title="Distribución proporcional de publicaciones por Facultad")
)
st.altair_chart(chart_fac_prop, use_container_width=True)

# Heatmap cuartil-año (paleta 'greens')
vis["_CU"] = vis["CUARTIL"].fillna("SIN CUARTIL").str.upper().str.strip()
by_cu = vis.groupby(["AÑO","_CU"]).size().reset_index(name="Publicaciones")
heat = (
    alt.Chart(by_cu)
      .mark_rect()
      .encode(
          x=alt.X("AÑO:O", title="Año"),
          y=alt.Y("_CU:N", title="Cuartil / Calidad"),
          color=alt.Color("Publicaciones:Q", title="N.º de publicaciones",
                          scale=alt.Scale(scheme="greens")),
          tooltip=["AÑO","_CU","Publicaciones"]
      )
      .properties(title="Densidad de publicaciones por cuartil y año")
)
st.altair_chart(heat, use_container_width=True)

# ------------------ Tabla final filtrable ------------------
st.subheader("Tabla de publicaciones consideradas (primer autor)")
year_tab = st.multiselect("Año (tabla)", years_all, default=year_vis_sel or years_all, key="tab_years")
vinc_tab = st.multiselect("Tipo de vinculación (tabla)",
                          ["NOMBRAMIENTO","OCASIONAL","SIN VINCULACION"],
                          default=["NOMBRAMIENTO","OCASIONAL","SIN VINCULACION"])

tab = vis.copy()
if year_tab:
    tab = tab[tab["AÑO"].isin(year_tab)]
if vinc_tab:
    tab = tab[tab["VINCULACION_PUB"].isin(vinc_tab)]

cols_show = ["AÑO","SEDE","FACULTAD","CARRERA","PRIMER_AUTOR","VINCULACION_PUB",
             "PUBLICACIÓN","REVISTA","CUARTIL","INDEXACIÓN","CLASE_NORM","DOI","URL"]
tab = tab[cols_show].rename(columns={
    "PRIMER_AUTOR": "DOCENTE (primer autor)",
    "VINCULACION_PUB": "VINCULACION"
})
st.dataframe(tab, use_container_width=True)

# ------------------ Detalle de PPC (φ base y λ final) ------------------
st.subheader("Detalle de PPC (φ base y λ final) — periodo de cálculo (TOTAL)")
calc_all_for_detail = slice_df(df_pub, year_calc_sel, fac_sel, car_sel, tipo_sel, sede_sel)
if not calc_all_for_detail.empty:
    _, ppc_rows_detail, *_ = numerador_IIPA(calc_all_for_detail, intercultural_21=intercultural_21)
    detail = ppc_rows_detail[["AÑO","FACULTAD","CARRERA","PUBLICACIÓN","REVISTA","CUARTIL","INDEXACIÓN","CLASE_NORM"]].copy()
    detail["φ (impacto)"] = ppc_rows_detail["phi_base"].values
    detail["λ (final)"]   = ppc_rows_detail["lambda"].values
    st.dataframe(detail, use_container_width=True)
else:
    st.info("No hay artículos/proceedings en el periodo de cálculo para mostrar detalle.")


st.divider()
st.caption(
    "Notas: Consideraciones tomadas en cuenta "
    "(1) Proceedings cuentan en PPC solo si están indexados (Scopus/WoS). "
    "(2) LCL: libros ponderan 1; capítulos ponderan 1/TOTAL_CAPITULOS si se activa; de lo contrario, factor fijo. "
    "(3) Interculturalidad: opción de +0.21 aplicada hasta el 21% del total de artículos PPC. "
    "(4) Se ha utilizado deduplicación para evitar doble conteo por coautorías."
)
