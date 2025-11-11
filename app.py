# ===============================================
# DASHBOARD IIPA (Libro único) — VINCULACIÓN desde "TIPO DE VINCULACIÓN"
# ===============================================
import os, re
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import plotly.graph_objects as go

# ------------------ Configuración base ------------------
st.set_page_config(page_title="IP — Dashboard (Libro único)", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"]  { font-family: "Inter", system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
</style>
""", unsafe_allow_html=True)

# ------------------ Encabezado ------------------
LOGO = "logo_uagraria_transparente_final.png"  # coloque el PNG en la misma carpeta
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists(LOGO):
        st.image(LOGO, width=90)
with col_title:
    st.title("Índice de Producción Académica per cápita (IP)")
st.caption(
    "Libro Excel único. La cohorte (Nombramiento/Ocasional) se toma de la columna 'TIPO DE VINCULACIÓN'. "
    "Deduplicación por DOI/Título atribuida al primer autor. Interculturalidad hasta 21% (tope λ≤1)."
)

# ------------------ Utilidades ------------------
def _cols_upper(df_):
    df_.columns = [str(c).strip().upper() for c in df_.columns]
    return df_

def _norm_txt(x):
    x = "" if pd.isna(x) else str(x)
    x = x.strip().upper()
    x = x.replace("Á","A").replace("É","E").replace("Í","I").replace("Ó","O").replace("Ú","U")
    x = " ".join(x.split())
    return x

def _norm_str(x):
    x = "" if pd.isna(x) else str(x)
    x = x.strip().lower()
    x = x.replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
    return x

# ------------------ Carga del libro ------------------
st.subheader("Datos de entrada")
uploaded_book = st.file_uploader("Suba el Excel (.xlsx). Alternativas: colocar 'Libro2.xlsx' junto al app o usar IIPA_EXCEL_PATH", type=["xlsx"])

xl_path_env = os.getenv("IIPA_EXCEL_PATH")
local_default = os.path.join(os.path.dirname(__file__), "Libro2.xlsx")

# Resolver origen
if uploaded_book is not None:
    xfile = pd.ExcelFile(uploaded_book)
elif xl_path_env and os.path.exists(xl_path_env):
    xfile = pd.ExcelFile(xl_path_env)
elif os.path.exists(local_default):
    xfile = pd.ExcelFile(local_default)
else:
    st.warning("No se detecta archivo. Suba el .xlsx o coloque 'Libro2.xlsx' junto al app, o defina IIPA_EXCEL_PATH.")
    st.stop()

# Detectar hoja de publicaciones
CAND_PUBLIC = {"PUBLICACIONES","PRODUCCION","PRODUCCIÓN","ARTICULOS","ARTÍCULOS","PUBS"}
def _find_sheet(xf, candidates, default_idx=None):
    up = {s.strip().upper(): s for s in xf.sheet_names}
    for upname, orig in up.items():
        if upname in candidates:
            return orig
    if default_idx is not None:
        return xf.sheet_names[default_idx]
    return None

sheet_pub = _find_sheet(xfile, CAND_PUBLIC, default_idx=0)
df = pd.read_excel(xfile, sheet_name=sheet_pub) if sheet_pub else pd.read_excel(xfile, sheet_name=0)
df = _cols_upper(df)

# ------------------ Asegurar columnas mínimas ------------------
for col in [
    "AÑO","SEDE","FACULTAD","CARRERA","TIPO","PUBLICACIÓN","REVISTA","FECHA",
    "DOI","URL","CUARTIL","INDEXACIÓN","CLASE","TOTAL_CAPITULOS",
    "NOMBRES","AUTORES","DOCENTE","DOCENTES","AUTOR", "TIPO DE VINCULACIÓN"
]:
    if col not in df.columns:
        df[col] = np.nan

# Tipos
df["AÑO"] = pd.to_numeric(df["AÑO"], errors="coerce").astype("Int64")
if "FECHA" in df.columns:
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")

# ------------------ Normalización de CLASE ------------------
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

df["CLASE_NORM"] = df.apply(normalize_clase, axis=1)

# ------------------ Primer autor + deduplicación (canónica por publicación) ------------------
import re

# 1) Normalizadores robustos (incluyen ñ)
def _norm_txt_upper(x: str) -> str:
    x = "" if pd.isna(x) else str(x)
    x = x.strip().upper()
    x = (x.replace("Á","A").replace("É","E").replace("Í","I")
           .replace("Ó","O").replace("Ú","U").replace("Ñ","N"))
    x = " ".join(x.split())
    return x

def _norm_txt_lower(x: str) -> str:
    x = "" if pd.isna(x) else str(x)
    x = x.strip().lower()
    x = (x.replace("á","a").replace("é","e").replace("í","i")
           .replace("ó","o").replace("ú","u").replace("ñ","n"))
    x = " ".join(x.split())
    return x

# 2) Columnas posibles de autores
autor_cols = ["NOMBRES", "DOCENTES", "DOCENTE", "AUTORES", "AUTOR", "INVESTIGADORES", "INVESTIGADOR"]
col_autores = next((c for c in autor_cols if c in df.columns), None)

def split_first_author(s: str) -> str:
    """Devuelve el primer autor de una cadena (si hay lista) o el nombre tal cual si no parece lista."""
    if pd.isna(s):
        return ""
    s = str(s).strip()
    if not s:
        return ""
    # Normalizar separadores de listas: ; , / | & y ' y '
    s_norm = re.sub(r"\s+y\s+", ",", s, flags=re.IGNORECASE)
    parts = re.split(r"[;,/|&]+", s_norm)
    if len(parts) <= 1:
        return " ".join(s.split())  # caso NOMBRES con un solo docente
    for p in parts:
        t = " ".join(p.strip().split())
        if t:
            return t
    return " ".join(s.split())

# 3) Claves de publicación
df["_DOI"] = df["DOI"].fillna("").astype(str).str.strip().str.lower()
df["_TIT"] = df["PUBLICACIÓN"].fillna("").astype(str).str.strip().str.lower()
df["_KEY"] = np.where(df["_DOI"] != "", "doi:" + df["_DOI"], "tit:" + df["_TIT"])

# 4) Primer autor por fila (prioriza NOMBRES si existe)
if col_autores:
    df["PRIMER_AUTOR"] = df[col_autores].map(split_first_author)
else:
    df["PRIMER_AUTOR"] = ""

df["PRIMER_AUTOR_NORM"] = df["PRIMER_AUTOR"].map(_norm_txt_upper)

# 5) Guardar orden original del Excel para desempates
df["_ORD"] = np.arange(len(df))

# 6) Construir PRIMER AUTOR CANÓNICO por publicación (del primer campo de lista disponible)
#    Intentamos encontrar una "lista de autores" dentro del grupo; si no hay, usamos el PRIMER_AUTOR más frecuente.
def pick_authors_list(series: pd.Series) -> str:
    # primera cadena que parezca lista (>1 autor)
    for s in series.dropna():
        s = str(s).strip()
        if re.search(r"[;,/|&]", s) or re.search(r"\s+y\s+", s, flags=re.IGNORECASE):
            return s
    # si no hay listas, devolver la primera no vacía
    for s in series.dropna():
        s = str(s).strip()
        if s:
            return s
    return ""

# columnas donde podría estar la lista completa de autores
list_cols = [c for c in ["AUTORES","DOCENTES","DOCENTE","AUTOR"] if c in df.columns]
list_cols = (["NOMBRES"] + list_cols) if "NOMBRES" in df.columns else list_cols

# Para rapidez, preconstruimos una columna auxiliar con la "fuente de autores" preferida por fila
def first_nonempty_row_authors(row):
    for c in list_cols:
        val = row.get(c, "")
        if isinstance(val, str) and val.strip():
            return val
    return ""

df["_AUTORES_SRC"] = df.apply(first_nonempty_row_authors, axis=1)

# 7) Selección canónica por grupo (_KEY):
#    - Si encontramos lista: extraer primer autor canónico y quedarnos con la fila cuyo PRIMER_AUTOR_NORM coincide.
#    - Si no coincide ninguna, quedarnos con la fila de menor _ORD (primer registro del Excel).
keep_idx = []
for key, g in df.groupby("_KEY", sort=False):
    # si no hay DOI/Título, se trata como grupo único
    if key in ("", "tit:"):
        keep_idx.extend(g.index.tolist())
        continue

    # a) intentar extraer autores canónicos
    src_list = pick_authors_list(g["_AUTORES_SRC"])
    canon = split_first_author(src_list)
    canon_norm = _norm_txt_upper(canon)

    if canon_norm:
        # filas que coinciden con el primer autor canónico
        match = g[g["PRIMER_AUTOR_NORM"] == canon_norm]
        if not match.empty:
            # si hay varias, tomar la de menor _ORD (primer registro del Excel)
            keep_idx.append(match.sort_values("_ORD").index[0])
            continue

    # b) fallback: primer registro original del Excel en el grupo
    keep_idx.append(g.sort_values("_ORD").index[0])

# 8) Filtrar el DataFrame a las filas canónicas por publicación
df = df.loc[keep_idx].copy()

# ------------------ VINCULACIÓN desde "TIPO DE VINCULACIÓN" ------------------
# Se normaliza a NOMBRAMIENTO/OCASIONAL/SIN VINCULACION.
def map_vinc(s: str) -> str:
    s = _norm_txt(s)
    if s in ("NOMBRAMIENTO","OCASIONAL"):
        return s
    # mapeos frecuentes
    if s in ("OC","OCAS","OCACIONAL"): return "OCASIONAL"
    if s in ("NOM","NOMBRADO","NOMBRAM"): return "NOMBRAMIENTO"
    return "SIN VINCULACION"

src_vinc_cols = ["TIPO DE VINCULACIÓN","TIPO_VINCULACION","TIPO VINCULACION","VINCULACION","TIPO"]
vcol = next((c for c in src_vinc_cols if c in df.columns), None)
df["VINCULACION_PUB"] = df[vcol].map(map_vinc) if vcol else "SIN VINCULACION"

# ------------------ Parámetros y filtros ------------------
years_all = sorted([int(y) for y in df["AÑO"].dropna().unique()])
current_year = pd.Timestamp.today().year
default_vis = [y for y in years_all if y >= current_year - 3] or years_all

with st.sidebar:
    st.header("Filtros de visualización")
    year_vis_sel = st.multiselect("Años para visualizar", years_all, default=default_vis)
    fac_sel = st.multiselect("Facultad", sorted(df["FACULTAD"].dropna().unique()),
                             default=sorted(df["FACULTAD"].dropna().unique()))
    car_sel = st.multiselect("Carrera", sorted(df["CARRERA"].dropna().unique()),
                             default=sorted(df["CARRERA"].dropna().unique()))
    tipo_sel = st.multiselect("Tipo de publicación", sorted(df["TIPO"].dropna().unique()),
                              default=sorted(df["TIPO"].dropna().unique()))
    sede_sel = st.multiselect("Sede", sorted(df["SEDE"].dropna().unique()),
                              default=sorted(df["SEDE"].dropna().unique()))

    st.divider()
    st.header("Cálculo del IP")
    year_calc_sel = st.multiselect("Años del periodo (3 años concluidos)", years_all, default=default_vis)
    denom_year = st.selectbox(
        "Año denominador (PTC + 0.5·PMT)",
        sorted(year_calc_sel) if year_calc_sel else years_all,
        index=len(sorted(year_calc_sel)) - 1 if year_calc_sel else (len(years_all) - 1 if years_all else 0)
    )
    st.caption("La deduplicación ya se aplicó (DOI/Título) y se atribuye al primer autor.")

    # LCL (capítulos)
    st.subheader("Capítulos — factor fijo (si no hay TOTAL_CAPITULOS)")
    factor_cap = st.number_input("Factor fijo por capítulo", min_value=0.1, max_value=1.0, value=0.25, step=0.05)
    usar_total_caps = st.checkbox("Usar TOTAL_CAPITULOS si existe (peso = 1 / TOTAL_CAPITULOS)", value=False)

    # Interculturalidad (21% máximo)
    intercultural_21 = st.checkbox("Aplicar componente intercultural (hasta 21% de artículos/proceedings)", value=True)

    st.divider()
    st.header("Personal académico (denominador)")
    st.caption("Ingrese valores del último año concluido seleccionado para el denominador.")
    st.subheader("Nombramiento")
    PTC_nom = st.number_input("PTC — Nombramiento", min_value=0, value=0, step=1)
    PMT_nom = st.number_input("PMT — Nombramiento", min_value=0, value=0, step=1)
    st.subheader("Ocasional")
    PTC_oca = st.number_input("PTC — Ocasional", min_value=0, value=0, step=1)
    PMT_oca = st.number_input("PMT — Ocasional", min_value=0, value=0, step=1)
    st.caption(f"Totales → PTC: {PTC_nom + PTC_oca} | PMT: {PMT_nom + PMT_oca}")

def slice_df(base, years, fac, car, tipo, sede):
    f = base.copy()
    if years: f = f[f["AÑO"].isin(years)]
    if fac:   f = f[f["FACULTAD"].isin(fac)]
    if car:   f = f[f["CARRERA"].isin(car)]
    if tipo:  f = f[f["TIPO"].isin(tipo)]
    if sede:  f = f[f["SEDE"].isin(sede)]
    return f

# ------------------ φ base (impacto) ------------------
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

# ------------------ Numerador IIPA (con 21% intercultural) ------------------
def numerador_IIPA(subdf: pd.DataFrame, intercultural_21=True) -> tuple:
    """
    Devuelve: (numerador, ppc_rows, ppa, lcl, ppi, n_aplicados_intercultural)
    """
    # PPC: artículos + proceedings indexados/cuatril
    is_article = subdf["CLASE_NORM"].eq("ARTICULO")
    is_proc = subdf["CLASE_NORM"].eq("PROCEEDINGS") & (
        subdf["INDEXACIÓN"].str.contains("SCOPUS|WOS|WEB OF SCIENCE", case=False, na=True) |
        subdf["CUARTIL"].str.contains("Q[1-4]", case=False, na=True)
    )
    ppc_rows = subdf.loc[is_article | is_proc].copy()

    if ppc_rows.empty:
        return 0.0, ppc_rows.assign(phi_base=[], lambda_=[]), 0.0, 0.0, 0.0, 0

    ppc_rows["phi_base"] = ppc_rows.apply(phi_base_only, axis=1)

    # Interculturalidad hasta 21% de los artículos/proceedings
    n_total = len(ppc_rows)
    ppc_rows["lambda"] = ppc_rows["phi_base"]
    n_aplicados = 0

    if intercultural_21 and n_total > 0:
        n_limit = int(np.floor(0.21 * n_total))
        ppc_rows["gain"] = np.minimum(1.0, ppc_rows["phi_base"] + 0.21) - ppc_rows["phi_base"]
        to_apply = ppc_rows.sort_values("gain", ascending=False).index[:n_limit]
        ppc_rows.loc[to_apply, "lambda"] = np.minimum(1.0, ppc_rows.loc[to_apply, "phi_base"] + 0.21)
        n_aplicados = len(to_apply)

    ppc = float(ppc_rows["lambda"].sum())

    # PPA
    ppa = float(subdf["CLASE_NORM"].eq("ARTE_INT").sum()) * 1.0 + \
          float(subdf["CLASE_NORM"].eq("ARTE_NAC").sum()) * 0.9

    # LCL: libros + capítulos (agrupado por libro)
    mask_libro = subdf["CLASE_NORM"].eq("LIBRO")
    mask_cap = subdf["CLASE_NORM"].eq("CAPITULO")
    libros = float(mask_libro.sum())

    caps_df = subdf.loc[mask_cap].copy()
    if not caps_df.empty:
        # Construir una clave de libro robusta
        def _norm_key(s):
            s = "" if pd.isna(s) else str(s).strip().lower()
            s = (s.replace("á", "a").replace("é", "e").replace("í", "i")
                   .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
            s = " ".join(s.split())
            return s

        # Si existen columnas específicas del libro, úselas
        candidates = []
        if "DOI_LIBRO" in caps_df.columns:
            candidates.append(caps_df["DOI_LIBRO"].map(_norm_key))
        if "ISBN" in caps_df.columns:
            candidates.append(caps_df["ISBN"].map(_norm_key))
        if "TITULO_LIBRO" in caps_df.columns:
            candidates.append(caps_df["TITULO_LIBRO"].map(_norm_key))
        if "LIBRO" in caps_df.columns:
            candidates.append(caps_df["LIBRO"].map(_norm_key))

        # Heurística desde PUBLICACIÓN
        if "PUBLICACIÓN" in caps_df.columns:
            pub_base = caps_df["PUBLICACIÓN"].astype(str).str.lower()
            pub_base = pub_base.str.replace(r"cap[ií]tulo.*", "", regex=True)
            pub_base = pub_base.str.replace(r"chapter.*", "", regex=True)
            candidates.append(pub_base.map(_norm_key))

        # Use la primera columna no vacía como BOOK_KEY
        if candidates:
            BOOK_KEY = candidates[0].copy()
            for c in candidates[1:]:
                BOOK_KEY = np.where((BOOK_KEY == "") & (c != ""), c, BOOK_KEY)
        else:
            BOOK_KEY = (caps_df.get("REVISTA", "").astype(str).str.lower().fillna("") + " | " +
                        caps_df.get("AÑO", "").astype(str).fillna(""))

        caps_df["_BOOK_KEY"] = BOOK_KEY
        caps_df["_den"] = pd.to_numeric(caps_df["TOTAL_CAPITULOS"], errors="coerce")

        # Agrupar por libro: capítulos publicados por la universidad y denominador del libro
        grp = (caps_df
               .groupby("_BOOK_KEY", dropna=False)
               .agg(
                   caps_ua=("PUBLICACIÓN", "size"),
                   den_book=("_den", lambda s: s.dropna().iloc[0] if s.dropna().size else np.nan)
               )
               .reset_index())

        # Peso por libro
        grp["w_book"] = np.where(
            (grp["den_book"] > 0) & np.isfinite(grp["den_book"]),
            grp["caps_ua"] / grp["den_book"],
            grp["caps_ua"] * float(factor_cap)
        )

        caps = float(grp["w_book"].sum())
    else:
        caps = 0.0

    lcl = libros + caps

    # PPI
    ppi = float(subdf["CLASE_NORM"].eq("PPI").sum())

    numerador = ppc + ppa + lcl + ppi
    return numerador, ppc_rows, ppa, lcl, ppi, n_aplicados


# ------------------ Denominador ------------------
def den_val(ptc, pmt):
    return float(ptc) + 0.5 * float(pmt)

# ------------------ Cálculo por cohorte ------------------
calc_all = slice_df(df, year_calc_sel, fac_sel, car_sel, tipo_sel, sede_sel)
calc_nom = calc_all[calc_all["VINCULACION_PUB"].eq("NOMBRAMIENTO")]
calc_oca = calc_all[calc_all["VINCULACION_PUB"].eq("OCASIONAL")]
calc_tot = calc_all

num_nom, ppc_nom_rows, ppa_nom, lcl_nom, ppi_nom, n_ap_nom = numerador_IIPA(calc_nom, intercultural_21=intercultural_21)
num_oca, ppc_oca_rows, ppa_oca, lcl_oca, ppi_oca, n_ap_oca = numerador_IIPA(calc_oca, intercultural_21=intercultural_21)
num_tot, ppc_tot_rows, ppa_tot, lcl_tot, ppi_tot, n_ap_tot = numerador_IIPA(calc_tot, intercultural_21=intercultural_21)

den_nom = den_val(PTC_nom, PMT_nom)
den_oca = den_val(PTC_oca, PMT_oca)
den_tot = den_val(PTC_nom + PTC_oca, PMT_nom + PMT_oca)

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

# ------------------ Visualización ------------------
st.divider()
st.subheader("Exploración de publicaciones (visualización)")

vis = df.copy()
vis = vis[vis["AÑO"].isin(year_vis_sel)] if year_vis_sel else vis
vis = vis[vis["FACULTAD"].isin(fac_sel)] if fac_sel else vis
vis = vis[vis["CARRERA"].isin(car_sel)]  if car_sel else vis
vis = vis[vis["TIPO"].isin(tipo_sel)]    if tipo_sel else vis
vis = vis[vis["SEDE"].isin(sede_sel)]    if sede_sel else vis

# Paleta de verdes institucionales para categorías
green_scale = alt.Scale(range=["#1B5E20", "#2E7D32", "#43A047", "#66BB6A", "#81C784", "#A5D6A7", "#C8E6C9"])

# Publicaciones por año (apilado por vinculación)
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

# Distribución proporcional por Facultad (por vinculación)
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
          color=alt.Color("Publicaciones:Q", title="N.º de publicaciones", scale=alt.Scale(scheme="greens")),
          tooltip=["AÑO","_CU","Publicaciones"]
      )
      .properties(title="Densidad de publicaciones por cuartil y año")
)
st.altair_chart(heat, use_container_width=True)

# -------- NUEVO: Tipo de publicación por Facultad (categorías solicitadas) --------
import re
import unicodedata

def _norm(s: str) -> str:
    s = str(s or "").strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # sin tildes
    s = re.sub(r"\s+", " ", s)
    return s
def _class_pub_for_fac(row):
    clase = _norm(row.get("CLASE_NORM", ""))
    cu    = _norm(row.get("CUARTIL", ""))
    idx   = _norm(row.get("INDEXACIÓN", "") or row.get("INDEXACION", ""))

    # Capítulos
    if re.search(r"\b(CAPITULO|BOOK CHAPTER|CHAPTER IN BOOK|PART OF BOOK)\b", clase):
        return "Capítulos de libro"

    # Libros
    if re.search(r"\b(LIBRO|BOOK)\b", clase):
        return "Libros"

    # Proceedings en Scopus/WoS (ACI)
    if "PROCEEDINGS" in clase and (("SCOPUS" in idx) or ("WOS" in idx) or ("WEB OF SCIENCE" in idx)):
        return "Proceedings en Scopus/WoS (ACI)"

    # Artículos por calidad / base
    if re.search(r"\b(ARTICULO|ARTICLE)\b", clase):
        if cu in {"Q1","Q2","Q3","Q4"} or ("SCOPUS" in idx or "WOS" in idx or "WEB OF SCIENCE" in idx):
            return "Artículos en bases de impacto"
        if "LATINDEX" in idx and "CATALOGO" in idx:
            return "Artículos Latindex Catálogo"
        if idx not in {"", "NO REGISTRADO", "NAN"}:
            return "Artículos Bases Regionales"

    return None

# --- pipeline sin cambios, añadiendo la nueva categoría ---
vis_cat = vis.copy()
vis_cat["CATEGORIA_FAC"] = vis_cat.apply(_class_pub_for_fac, axis=1)
vis_cat = vis_cat.dropna(subset=["CATEGORIA_FAC"])

cat_order = [
    "Artículos en bases de impacto",
    "Artículos Latindex Catálogo",
    "Artículos Bases Regionales",
    "Libros",
    "Capítulos de libro",      # <-- nueva categoría
    "Proceedings en Scopus",
]

# paleta (6 tonos, consistente y legible)
cat_colors = ["#1B5E20", "#2E7D32", "#43A047", "#66BB6A", "#81C784", "#A5D6A7"]

vis_cat["CATEGORIA_FAC"] = pd.Categorical(vis_cat["CATEGORIA_FAC"], categories=cat_order, ordered=True)

by_fac_cat = vis_cat.groupby(["FACULTAD","CATEGORIA_FAC"]).size().reset_index(name="Publicaciones")

chart_type_fac = (
    alt.Chart(by_fac_cat)
      .mark_bar()
      .encode(
          x=alt.X("FACULTAD:N", title="Facultad"),
          y=alt.Y("sum(Publicaciones):Q", title="N.º de publicaciones"),
          color=alt.Color("CATEGORIA_FAC:N", title="Tipo de publicación",
                          scale=alt.Scale(domain=cat_order, range=cat_colors)),
          tooltip=["FACULTAD","CATEGORIA_FAC","Publicaciones"]
      )
      .properties(title="Tipo de publicación por Facultad")
)
# ponderados por facultad
st.altair_chart(chart_type_fac, use_container_width=True)

# agregados LCL (Libros + Capítulos ponderados)
lcl_df = pd.DataFrame({
 "FACULTAD": [*calc_tot["FACULTAD"].unique()]
})
# recomputar lcl por FACULTAD (usar su lógica exacta de ponderación)
def lcl_fac(sub):
    # Libros completos
    libros = float(sub["CLASE_NORM"].eq("LIBRO").sum())

    # Capítulos por libro (agrupado)
    caps_df = sub.loc[sub["CLASE_NORM"].eq("CAPITULO")].copy()
    if caps_df.empty:
        return libros, 0.0

    def _norm_key(s):
        s = "" if pd.isna(s) else str(s).strip().lower()
        s = (s.replace("á","a").replace("é","e").replace("í","i")
               .replace("ó","o").replace("ú","u").replace("ñ","n"))
        s = " ".join(s.split())
        return s

    candidates = []
    if "DOI_LIBRO" in caps_df.columns:     candidates.append(caps_df["DOI_LIBRO"].map(_norm_key))
    if "ISBN" in caps_df.columns:          candidates.append(caps_df["ISBN"].map(_norm_key))
    if "TITULO_LIBRO" in caps_df.columns:  candidates.append(caps_df["TITULO_LIBRO"].map(_norm_key))
    if "LIBRO" in caps_df.columns:         candidates.append(caps_df["LIBRO"].map(_norm_key))

    if "PUBLICACIÓN" in caps_df.columns:
        pub_base = caps_df["PUBLICACIÓN"].astype(str).str.lower()
        pub_base = pub_base.str.replace(r"cap[ií]tulo.*", "", regex=True).str.replace(r"chapter.*", "", regex=True)
        candidates.append(pub_base.map(_norm_key))

    if candidates:
        BOOK_KEY = candidates[0].copy()
        for c in candidates[1:]:
            BOOK_KEY = np.where((BOOK_KEY == "") & (c != ""), c, BOOK_KEY)
    else:
        BOOK_KEY = (caps_df.get("REVISTA","").astype(str).str.lower().fillna("") + " | " +
                    caps_df.get("AÑO","").astype(str).fillna(""))

    caps_df["_BOOK_KEY"] = BOOK_KEY
    caps_df["_den"] = pd.to_numeric(caps_df["TOTAL_CAPITULOS"], errors="coerce")

    grp = (caps_df
           .groupby("_BOOK_KEY", dropna=False)
           .agg(
               caps_ua=("PUBLICACIÓN", "size"),
               den_book=("_den", lambda s: s.dropna().iloc[0] if s.dropna().size else np.nan)
           )
           .reset_index())

    grp["w_book"] = np.where((grp["den_book"] > 0) & np.isfinite(grp["den_book"]),
                             grp["caps_ua"] / grp["den_book"],
                             grp["caps_ua"] * float(factor_cap))

    caps_w = float(grp["w_book"].sum())
    return float(libros), float(caps_w)
# --- calidad del dato (siempre definir caps_all antes de auditar) ---
caps_all = calc_tot.loc[calc_tot["CLASE_NORM"].eq("CAPITULO")].copy()

# Asegurar la columna TOTAL_CAPITULOS para evitar NameError/KeyError
if "TOTAL_CAPITULOS" not in caps_all.columns:
    caps_all["TOTAL_CAPITULOS"] = np.nan

# Denominador numérico y seguro
caps_all["_den"] = pd.to_numeric(caps_all["TOTAL_CAPITULOS"], errors="coerce")

# Boxplot solo si hay datos
if not caps_all.empty:
    chart_den = alt.Chart(caps_all).mark_boxplot().encode(
        x=alt.X("FACULTAD:N"),
        y=alt.Y("_den:Q", title="TOTAL_CAPITULOS")
    ).properties(title="Distribución de TOTAL_CAPITULOS (capítulos)")
    st.altair_chart(chart_den, use_container_width=True)
# --- auditoría: capítulos sin denominador válido ---
if not caps_all.empty:
    cols_audit = [c for c in ["FACULTAD", "PUBLICACIÓN", "TOTAL_CAPITULOS"] if c in caps_all.columns]
    audit_caps = caps_all.loc[caps_all["_den"].isna(), cols_audit].head(30)
    if not audit_caps.empty:
        st.caption("Capítulos sin denominador; se aplica factor_cap.")
        st.dataframe(audit_caps, use_container_width=True)


# --- tarjeta φ_base (promedio global del subconjunto) y PPC (suma de λ) en la misma fila ---
vis_phi = vis.copy()
vis_phi["phi_base"] = vis_phi.apply(phi_base_only, axis=1)

phi_mean = float(vis_phi["phi_base"].mean()) if not vis_phi.empty else float("nan")
phi_median = float(vis_phi["phi_base"].median()) if not vis_phi.empty else float("nan")
n_phi = int(len(vis_phi))

# Preparar PPC (de su cálculo existente)
ppc = ppc_tot_rows.copy()
ppc["aplica_21"] = ppc["lambda"].gt(ppc["phi_base"])
ppc["tipo"] = np.where(ppc["CLASE_NORM"].eq("PROCEEDINGS"), "Proceedings", "Artículo")
ppc["calidad"] = np.where(
    ppc["CUARTIL"].str.fullmatch("Q[1-4]", case=False, na=False),
    ppc["CUARTIL"].str.upper(),
    np.where(
        ppc["INDEXACIÓN"].str.contains("SCOPUS|WOS|WEB OF SCIENCE", case=False, na=False),
        "Scopus/WoS",
        "Otras"
    )
)

ppc_val = float(ppc["lambda"].sum()) if not ppc.empty else float("nan")
ppc_base = float(ppc["phi_base"].sum()) if not ppc.empty else float("nan")
n_aplicados = int(ppc["aplica_21"].sum()) if not ppc.empty else 0
limite_21 = int(np.floor(0.21 * len(ppc))) if len(ppc) > 0 else 0

# --- Tarjetas en una misma fila ---
col1, col2 = st.columns(2)

with col1:
    st.metric(
        "φ_base — Promedio",
        f"{phi_mean:.3f}" if not np.isnan(phi_mean) else "—",
        help=f"Mediana: {phi_median:.3f} | Registros: {n_phi}"
    )

with col2:
    st.metric(
        "PPC — Suma de λ",
        f"{ppc_val:.3f}" if not np.isnan(ppc_val) else "—",
        help=f"φ_base total: {ppc_base:.3f} | 21% aplicado a {n_aplicados}/{limite_21} publicaciones"
    )


# ------------------ Tabla final filtrable ------------------
st.subheader("Tabla de publicaciones consideradas (primer autor)")
year_tab = st.multiselect("Año (tabla)", years_all, default=year_vis_sel or years_all, key="tab_years")
vinc_tab = st.multiselect("Tipo de vinculación (tabla)",
                          ["NOMBRAMIENTO","OCASIONAL"],
                          default=["NOMBRAMIENTO","OCASIONAL"])

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
calc_all_for_detail = slice_df(df, year_calc_sel, fac_sel, car_sel, tipo_sel, sede_sel)
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
