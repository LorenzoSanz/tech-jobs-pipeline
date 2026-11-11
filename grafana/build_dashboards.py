"""Builds grafana/dashboards/*.json. Usage: python grafana/build_dashboards.py grafana/dashboards

Layout rules, so the three dashboards look the same:
- every section starts with a row header and fills the 24 columns;
- KPI tiles are 4 high, charts and short tables 9, long tables 12 or more;
- every filter is a dropdown, in the same order on every dashboard.
"""

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
DS = {"type": "grafana-postgresql-datasource", "uid": "jobpipe-pg"}

KPI_H, CHART_H, TABLE_H = 4, 9, 13

# Region filter: postings with no detected region count as 'other'.
REGION_SQL = "coalesce(nullif(regions, '{}'), '{other}') && ARRAY[$region]::text[]"


def any_of(column, var):
    """`column IN ($var)`, true for "All" without listing every value."""
    return f"('__all' IN (${var}) OR {column} IN (${var}))"


# ----------------------------------------------------------------------------- panels


def target(sql, fmt="table"):
    return {"refId": "A", "datasource": DS, "rawQuery": True, "editorMode": "code", "format": fmt, "rawSql": sql.strip()}


def panel(kind, title, sql, fmt="table", description="", options=None, defaults=None, overrides=None, width=None):
    return {
        "type": kind, "title": title, "description": description, "datasource": DS,
        "targets": [target(sql, fmt)], "options": options or {},
        "fieldConfig": {"defaults": {"noValue": "—", **(defaults or {})}, "overrides": overrides or []},
        "_width": width,
    }  # fmt: skip


def stat(title, sql, unit="locale", description="", decimals=0, steps=None):
    return panel(
        "stat", title, sql, description=description,
        options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                 "colorMode": "value", "graphMode": "none", "textMode": "value", "justifyMode": "center",
                 "text": {"valueSize": 34}},
        defaults={"unit": unit, "decimals": decimals, "color": {"mode": "thresholds"},
                  "thresholds": {"mode": "absolute", "steps": steps or [{"color": "#5794F2", "value": None}]}},
    )  # fmt: skip


def table(title, sql, description="", overrides=None, money=None):
    """A table; `money` is a regex of columns shown as amounts, `Puesto` links to the posting."""
    overrides = list(overrides or [])
    if money:
        overrides.append({"matcher": {"id": "byRegexp", "options": money},
                          "properties": [{"id": "unit", "value": "locale"}, {"id": "decimals", "value": 0},
                                         {"id": "custom.align", "value": "right"}]})  # fmt: skip
    return panel(
        "table", title, sql, description=description,
        options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        defaults={"custom": {"align": "auto", "filterable": False, "inspect": False, "minWidth": 70}}, overrides=overrides,
    )


def link_to_posting(field="Puesto", url_field="url"):
    return [
        {"matcher": {"id": "byName", "options": field},
         "properties": [{"id": "links", "value": [{"title": "Abrir oferta", "url": "${__data.fields." + url_field + "}",
                                                   "targetBlank": True}]},
                        {"id": "custom.minWidth", "value": 260}]},
        {"matcher": {"id": "byName", "options": url_field}, "properties": [{"id": "custom.hidden", "value": True}]},
    ]  # fmt: skip


def bars(title, sql, x, horizontal=False, description=""):
    return panel(
        "barchart", title, sql, description=description,
        options={"xField": x, "orientation": "horizontal" if horizontal else "vertical", "showValue": "auto",
                 "legend": {"showLegend": False}, "barWidth": 0.8, "xTickLabelRotation": 0},
        defaults={"color": {"mode": "fixed", "fixedColor": "#5794F2"}, "custom": {"fillOpacity": 80, "lineWidth": 0}},
    )  # fmt: skip


def timeseries(title, sql, description="", style="bars"):
    custom = {"drawStyle": "bars", "fillOpacity": 70, "lineWidth": 0, "stacking": {"mode": "normal"}}
    if style == "points":
        custom = {"drawStyle": "points", "pointSize": 7}
    elif style == "line":
        custom = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 10, "showPoints": "never"}
    return panel(
        "timeseries", title, sql, fmt="time_series", description=description,
        options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                 "tooltip": {"mode": "multi", "sort": "desc"}},
        defaults={"custom": custom, "unit": "locale", "color": {"mode": "palette-classic"}},
    )  # fmt: skip


class Grid:
    """Places panels left to right in full-width rows, so nothing is left ragged."""

    def __init__(self):
        self.panels, self.y = [], 0

    def section(self, title):
        self.panels.append({"type": "row", "title": title, "collapsed": False, "panels": [],
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}})  # fmt: skip
        self.y += 1
        return self

    def line(self, height, *panels):
        widths = [p.pop("_width") or 24 // len(panels) for p in panels]
        assert sum(widths) == 24, [p["title"] for p in panels]
        x = 0
        for p, w in zip(panels, widths):
            p["gridPos"] = {"x": x, "y": self.y, "w": w, "h": height}
            self.panels.append(p)
            x += w
        self.y += height
        return self

    def done(self):
        for n, p in enumerate(self.panels, 1):
            p["id"] = n
        return self.panels


# ----------------------------------------------------------------------------- filters (all dropdowns)


def custom_var(name, label, values, default, multi=False, description=""):
    opts = [{"text": t, "value": v, "selected": v in default} for t, v in values]
    cur_text = [t for t, v in values if v in default]
    return {"type": "custom", "name": name, "label": label, "description": description, "multi": multi,
            "includeAll": False, "query": ",".join(f"{t} : {v}" for t, v in values), "options": opts,
            "current": {"text": cur_text if multi else cur_text[0], "value": default if multi else default[0]}}  # fmt: skip


def query_var(name, label, sql, multi=False, all_option=False, description=""):
    v = {"type": "query", "name": name, "label": label, "description": description, "datasource": DS,
         "query": sql, "definition": sql, "refresh": 1, "multi": multi, "includeAll": all_option, "sort": 0}  # fmt: skip
    if all_option:
        v["allValue"] = "'__all'"
        v["current"] = {"text": ["All"], "value": ["$__all"]}
    return v


REGIONS = [("Suiza", "ch"), ("España", "es"), ("Resto de Europa", "eu"), ("Otras / sin región", "other")]
REGION_VAR = custom_var("region", "Región", REGIONS, ["ch", "es", "eu"], multi=True)
OFFER_VAR = custom_var(
    "offer", "Tu oferta (bruto anual)", [(f"{n // 1000}k", str(n)) for n in range(20000, 300001, 5000)], ["100000"],
    description="Compara una cifra con las ofertas publicadas en la moneda elegida.",
)


def role_var(source):
    return query_var("role", "Rol", f"SELECT role FROM {source} GROUP BY 1 ORDER BY count(*) DESC",
                     multi=True, all_option=True, description="Familia de puesto, deducida del título.")  # fmt: skip


def dashboard(uid, title, grid, variables, time_from="now-1y", description=""):
    return {
        "uid": uid, "title": title, "description": description, "tags": ["jobpipe"], "timezone": "browser",
        "schemaVersion": 39, "version": 1, "editable": False, "graphTooltip": 1, "liveNow": False,
        "time": {"from": time_from, "to": "now"}, "refresh": "",
        "timepicker": {"refresh_intervals": []},
        "templating": {"list": variables}, "annotations": {"list": []},
        "links": [{"type": "dashboards", "tags": ["jobpipe"], "asDropdown": True, "title": "Otros paneles",
                   "includeVars": False, "keepTime": True}],
        "panels": grid.done(),
    }  # fmt: skip


# ----------------------------------------------------------------------------- Salarios

SAL_WHERE = f"""
currency = ${{currency:sqlstring}}
  AND {REGION_SQL}
  AND {any_of("role", "role")}
  AND (NOT predicted OR ${{predicted:raw}})
  AND $__timeFilter(posted_at)
"""


def percentile(p):
    return f"SELECT percentile_cont({p}) WITHIN GROUP (ORDER BY midpoint) FROM gold.salaries WHERE {SAL_WHERE}"


salaries = dashboard(
    "jobpipe-salaries", "Salarios",
    description="Rangos salariales publicados en ofertas. Bruto anual, sin conversión de divisas.",
    variables=[
        REGION_VAR,
        role_var("gold.salaries"),
        query_var("currency", "Moneda", "SELECT currency FROM silver.posted_salaries GROUP BY 1 "
                  "ORDER BY array_position(ARRAY['CHF', 'EUR'], currency) NULLS LAST, count(*) DESC",
                  description="Las cifras nunca se convierten entre monedas."),
        OFFER_VAR,
        custom_var("predicted", "Estimaciones de Adzuna", [("Excluir", "false"), ("Incluir", "true")], ["false"],
                   description="Adzuna estima el salario de ofertas que no lo publican. Mejor excluirlas para negociar."),
        query_var("adzuna", "Búsqueda en Adzuna",
                  "SELECT DISTINCT country || ' | ' || coalesce(what, category, 'todo') FROM silver.adzuna_salary_histogram ORDER BY 1"),
    ],
    grid=Grid()
    .section("Resumen ($currency, punto medio del rango)")
    .line(
        KPI_H,
        stat("Ofertas con salario", f"SELECT count(*) FROM gold.salaries WHERE {SAL_WHERE}"),
        stat("p25", percentile(0.25), description="Una de cada cuatro ofertas paga menos que esto."),
        stat("Mediana", percentile(0.5)),
        stat("p75", percentile(0.75), description="Una de cada cuatro ofertas paga más que esto."),
        stat("p90", percentile(0.9)),
        stat("Tu oferta supera al",
             f"SELECT 100.0 * avg((midpoint <= ${{offer:sqlstring}}::numeric)::int) FROM gold.salaries WHERE {SAL_WHERE}",
             unit="percent", description="Porcentaje de ofertas cuyo punto medio es menor o igual que tu oferta.",
             steps=[{"color": "#F2495C", "value": None}, {"color": "#FF9830", "value": 25},
                    {"color": "#FADE2A", "value": 50}, {"color": "#73BF69", "value": 75}]),
    )  # fmt: skip
    .section("Distribución")
    .line(
        CHART_H,
        panel("histogram", "Punto medio del rango", f'SELECT midpoint AS "Punto medio" FROM gold.salaries WHERE {SAL_WHERE}',
              options={"bucketCount": 20, "combine": False, "legend": {"showLegend": False}},
              defaults={"unit": "locale", "decimals": 0, "color": {"mode": "fixed", "fixedColor": "#5794F2"},
                        "custom": {"fillOpacity": 80, "lineWidth": 0}}),
        table("Por rol",
              f"""
SELECT role AS "Rol", count(*) AS "Ofertas",
       percentile_cont(0.25) WITHIN GROUP (ORDER BY midpoint) AS "p25",
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY midpoint) AS "Mediana",
       percentile_cont(0.75) WITHIN GROUP (ORDER BY midpoint) AS "p75"
FROM gold.salaries WHERE {SAL_WHERE}
GROUP BY 1 ORDER BY "Mediana" DESC
""", money="p25|Mediana|p75"),
    )  # fmt: skip
    .section("Ofertas mejor pagadas")
    .line(
        TABLE_H,
        table("Rangos más altos · clic en el puesto para abrir la oferta",
              f"""
SELECT company AS "Empresa", title AS "Puesto", role AS "Rol", coalesce(location, country) AS "Lugar",
       min_annual AS "Mínimo", max_annual AS "Máximo", to_char(posted_at, 'YYYY-MM-DD') AS "Publicada", source AS "Fuente", url
FROM gold.salaries WHERE {SAL_WHERE}
ORDER BY max_annual DESC LIMIT 100
""", overrides=link_to_posting(), money="Mínimo|Máximo"),
    )  # fmt: skip
    .section("Referencias externas")
    .line(
        CHART_H,
        bars("Adzuna · ofertas por tramo salarial ($adzuna)",
             """
SELECT to_char(bucket_from, 'FM999G999') AS "Desde", postings AS "Ofertas"
FROM silver.adzuna_salary_histogram
WHERE country || ' | ' || coalesce(what, category, 'todo') = ${adzuna:sqlstring}
ORDER BY bucket_from
""", x="Desde", description="Salarios anunciados en Adzuna para tu búsqueda. Jobs by Adzuna."),
        timeseries("Adzuna · salario medio anunciado por mes",
                   """
SELECT month::timestamptz AS time, country || ' ' || category AS metric, avg_salary AS value
FROM silver.adzuna_salary_history ORDER BY 1
""", style="line", description="Media de la categoría completa; Adzuna no la da por palabra clave. Jobs by Adzuna."),
    )  # fmt: skip
    .line(
        CHART_H,
        table("Levels.fyi · compensación real por ubicación (USD)",
              """
SELECT job_family AS "Familia", salary_type AS "Tipo", focus_tags AS "Foco", location AS "Ubicación",
       coalesce(yoe_range || ' años', 'todos') AS "Experiencia",
       p25, p50 AS "Mediana", p75, p90, sample_size AS "Muestras"
FROM silver.levelsfyi_benchmarks
ORDER BY location, kind DESC, yoe_range
""", money="p25|Mediana|p75|p90",
              description="Data source: Levels.fyi (https://www.levels.fyi). Solo con la API oficial (LEVELS_FYI_API_KEY)."),
    ),  # fmt: skip
)

# ----------------------------------------------------------------------------- Mercado

POSTING_WHERE = f"""{REGION_SQL}
  AND {any_of("role", "role")}
  AND {any_of("company", "company")}"""
HAS_SALARY = """EXISTS (SELECT 1 FROM silver.posted_salaries s
        WHERE s.source = p.source AND s.source_id = p.source_id AND NOT s.predicted)"""

market = dashboard(
    "jobpipe-market", "Mercado y ofertas",
    description="Volumen de ofertas por mes y región, quién contrata, y lista de ofertas.",
    time_from="now-2y",
    variables=[
        REGION_VAR,
        role_var("silver.postings"),
        query_var("company", "Empresa",
                  "SELECT company FROM silver.postings WHERE company IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 500",
                  multi=True, all_option=True, description="Las 500 empresas con más ofertas."),
        custom_var("with_salary", "Salario", [("Todas las ofertas", "false"), ("Solo con salario publicado", "true")], ["false"]),
    ],
    grid=Grid()
    .section("Resumen")
    .line(
        KPI_H,
        stat("Vistas en los últimos 7 días",
             f"SELECT count(*) FROM silver.postings WHERE last_seen > now() - interval '7 days' AND {POSTING_WHERE}"),
        stat("Nuevas en los últimos 30 días",
             f"SELECT count(*) FROM silver.postings WHERE coalesce(published, first_seen) > now() - interval '30 days' AND {POSTING_WHERE}"),
        stat("Empresas contratando (90 días)",
             f"SELECT count(DISTINCT lower(company)) FROM silver.postings WHERE last_seen > now() - interval '90 days' AND {POSTING_WHERE}"),
        stat("Con salario publicado",
             f"SELECT 100.0 * count(*) FILTER (WHERE {HAS_SALARY}) / nullif(count(*), 0) FROM silver.postings p WHERE {POSTING_WHERE}",
             unit="percent", decimals=1),
    )  # fmt: skip
    .section("Tendencia")
    .line(
        CHART_H,
        timeseries("Ofertas publicadas por mes y región",
                   f"""
SELECT month::timestamptz AS time, region AS metric, sum(postings) AS value
FROM gold.postings_monthly
WHERE $__timeFilter(month::timestamptz) AND region IN ($region) AND {any_of("role", "role")}
GROUP BY 1, 2 ORDER BY 1
""", description="Fecha de publicación según la fuente; si no la da, la primera vez que se vio. HN aporta la historia desde 2011."),
    )  # fmt: skip
    .section("Quién contrata (90 días)")
    .line(
        CHART_H,
        table("Empresas con más ofertas",
              f"""
SELECT company AS "Empresa", count(*) AS "Ofertas", to_char(max(coalesce(published, first_seen)), 'YYYY-MM-DD') AS "Última"
FROM silver.postings
WHERE company IS NOT NULL AND last_seen > now() - interval '90 days' AND {POSTING_WHERE}
GROUP BY 1 ORDER BY 2 DESC LIMIT 50
"""),
        bars("Ofertas por rol",
             f"""
SELECT role AS "Rol", count(*) AS "Ofertas"
FROM silver.postings
WHERE last_seen > now() - interval '90 days' AND {POSTING_WHERE}
GROUP BY 1 ORDER BY 2 DESC
""", x="Rol", horizontal=True),
    )  # fmt: skip
    .section("Ofertas")
    .line(
        16,
        table("Ofertas del periodo · clic en el puesto para abrir la oferta",
              f"""
SELECT to_char(coalesce(p.published, p.first_seen), 'YYYY-MM-DD') AS "Publicada", p.company AS "Empresa", p.title AS "Puesto",
       p.role AS "Rol", coalesce(p.location, p.country) AS "Lugar", array_to_string(p.regions, ', ') AS "Región",
       (SELECT string_agg(s.currency || ' ' || round(s.min_annual / 1000) || 'k–' || round(s.max_annual / 1000) || 'k', ' / ')
          FROM silver.posted_salaries s
         WHERE s.source = p.source AND s.source_id = p.source_id AND NOT s.predicted) AS "Salario",
       p.source AS "Fuente", p.url
FROM silver.postings p
WHERE {POSTING_WHERE}
  AND $__timeFilter(coalesce(p.published, p.first_seen))
  AND (NOT ${{with_salary:raw}} OR {HAS_SALARY})
ORDER BY 1 DESC NULLS LAST LIMIT 500
""", overrides=link_to_posting()),
    ),  # fmt: skip
)

# ----------------------------------------------------------------------------- Pipeline

pipeline = dashboard(
    "jobpipe-pipeline", "Salud del pipeline",
    description="Qué se ha recogido, cuándo, y si alguna fuente ha dejado de devolver datos.",
    time_from="now-30d",
    variables=[],
    grid=Grid()
    .section("Estado")
    .line(
        KPI_H,
        stat("Última carga en PostgreSQL", "SELECT extract(epoch FROM max(loaded_at)) * 1000 FROM silver.load_log",
             unit="dateTimeFromNow"),
        stat("Ofertas en silver", "SELECT count(*) FROM silver.postings"),
        stat("Ejecuciones en el periodo",
             "SELECT count(*) FROM silver.ingest_runs WHERE $__timeFilter(coalesce(last_fetched, ingest_date::timestamptz))"),
        stat("Días sin recoger (peor fuente)",
             "SELECT max(current_date - last_ingest) FROM gold.source_health WHERE source NOT IN ('adzuna_salary', 'levelsfyi')",
             steps=[{"color": "#73BF69", "value": None}, {"color": "#FF9830", "value": 2}, {"color": "#F2495C", "value": 7}]),
    )  # fmt: skip
    .section("Por fuente")
    .line(
        CHART_H,
        table("Fuentes",
              """
SELECT source AS "Fuente", runs AS "Ejecuciones", records AS "Registros", to_char(last_ingest, 'YYYY-MM-DD') AS "Última recogida",
       current_date - last_ingest AS "Días"
FROM gold.source_health ORDER BY 1
"""),
        timeseries("Registros por ejecución",
                   """
SELECT coalesce(last_fetched, ingest_date::timestamptz) AS time, source AS metric, records AS value
FROM silver.ingest_runs
WHERE $__timeFilter(coalesce(last_fetched, ingest_date::timestamptz))
ORDER BY 1
""", style="points"),
    ),  # fmt: skip
)

OUT.mkdir(parents=True, exist_ok=True)
for name, board in [("salaries", salaries), ("market", market), ("pipeline", pipeline)]:
    (OUT / f"{name}.json").write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(name, len(board["panels"]), "panels")
