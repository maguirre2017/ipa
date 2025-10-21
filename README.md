
# CACES IIPA — Dashboard (Streamlit)

## Ejecutar
```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

- Cargue su Excel de publicaciones o deje `Libro2.xlsx` junto a `app.py`.
- (Opcional) Cargue Excel de personal con columnas: `AÑO, FACULTAD, PTC, PMT`.
- Defina los **años de cálculo** (3 años) y el **año denominador** (usa PTC + 0.5·PMT).
- Active **deduplicación por DOI/Título**.
- Revise KPIs: PPC, PPA, LCL, PPI, IIPA.

## Requisitos de columnas (publicaciones)
`AÑO, FACULTAD, CARRERA, TIPO, PUBLICACIÓN, REVISTA, FECHA, DOI, URL, CUARTIL, INDEXACIÓN, [opcional] INTERCULTURAL, [opcional] CLASE`

## Clasificación robusta (`CLASE_NORM`)
Si su Excel ya trae `CLASE_NORM`, se usa directamente; si no, se infiere combinando `CLASE`, `TIPO`, `INDEXACIÓN`, `CUARTIL`.
Valores estandarizados: `ARTICULO`, `PROCEEDINGS`, `LIBRO`, `CAPITULO`, `PPI`, `ARTE_INT`, `ARTE_NAC`, `OTRO`.
