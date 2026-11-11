"""Builds the dashboards in English and Spanish.

Usage: python grafana/build_dashboards.py grafana/dashboards
writes grafana/dashboards/{en,es}/{feed,salaries,market,pipeline}.json.

Layout rules, so every dashboard looks the same:
- every section starts with a row header and fills the 24 columns;
- KPI tiles are 4 high, charts and short tables 9, long tables 13 or more;
- every filter is a dropdown, in the same order on every dashboard;
- colours come from one blue-to-purple ramp.

Both languages share variable names and values (role keys, region codes), so
the language link keeps the current filters.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from jobpipe import roles, tech  # noqa: E402

OUT = Path(sys.argv[1])
DS = {"type": "grafana-postgresql-datasource", "uid": "jobpipe-pg"}
LANGS = ("en", "es")
KPI_H, CHART_H, TABLE_H = 4, 9, 13

BLUE, SKY, INDIGO, VIOLET, PURPLE, LAVENDER, FUCHSIA = (
    "#3B82F6", "#60A5FA", "#6366F1", "#8B5CF6", "#A855F7", "#C4B5FD", "#D946EF",
)  # fmt: skip


def ramp(n, start=BLUE, end=PURPLE):
    """n colours evenly spaced from blue to purple."""
    a, b = (tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in (start, end))
    steps = [i / (n - 1) if n > 1 else 0 for i in range(n)]
    return ["#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b)) for t in steps]


# Region filter: postings with no detected region count as 'other'.
REGION_SQL = "coalesce(nullif(regions, '{}'), '{other}') && ARRAY[$region]::text[]"
REGIONS = {"ch": ("Switzerland", "Suiza"), "es": ("Spain", "España"), "eu": ("Rest of Europe", "Resto de Europa"),
           "other": ("Other / unknown", "Otras / sin región")}  # fmt: skip
REGION_COLORS = dict(zip(REGIONS, [BLUE, PURPLE, SKY, LAVENDER]))
SOURCES = ("hn", "greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "personio",
           "adzuna", "adzuna_salary", "levelsfyi")


def any_of(column, var):
    """`column IN ($var)`, true for "All" without listing every value."""
    return f"('__all' IN (${var}) OR {column} IN (${var}))"


def label_sql(column, labels):
    """SQL CASE that turns a stored key into its label."""
    whens = " ".join(f"WHEN '{key}' THEN '{text}'" for key, text in labels.items())
    return f"CASE {column} {whens} ELSE {column} END"


# ----------------------------------------------------------------------------- panels


def target(sql, fmt="table"):
    return {"refId": "A", "datasource": DS, "rawQuery": True, "editorMode": "code", "format": fmt, "rawSql": sql.strip()}


def panel(kind, title, sql, fmt="table", description="", options=None, defaults=None, overrides=None):
    return {
        "type": kind, "title": title, "description": description, "datasource": DS,
        "targets": [target(sql, fmt)], "options": options or {},
        "fieldConfig": {"defaults": {"noValue": "—", **(defaults or {})}, "overrides": overrides or []},
    }  # fmt: skip


def stat(title, sql, unit="locale", description="", decimals=0, steps=None):
    """A KPI card: name and value inside one gradient tile, no panel header."""
    p = panel(
        "stat", "", sql, description=description,
        options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                 "colorMode": "background", "graphMode": "none", "textMode": "value_and_name",
                 "justifyMode": "center", "text": {"titleSize": 14, "valueSize": 30}},
        defaults={"displayName": title, "unit": unit, "decimals": decimals, "color": {"mode": "thresholds"},
                  "thresholds": {"mode": "absolute", "steps": steps or [{"color": BLUE, "value": None}]}},
    )  # fmt: skip
    p["_ramp"] = steps is None  # coloured by Grid.line, along the row
    return p


def by_name(name, *properties):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": k, "value": v} for k, v in properties]}


def by_regex(regex, *properties):
    return {"matcher": {"id": "byRegexp", "options": regex}, "properties": [{"id": k, "value": v} for k, v in properties]}


def series_colors(colors):
    return [by_name(name, ("color", {"mode": "fixed", "fixedColor": color})) for name, color in colors.items()]


def table(title, sql, description="", overrides=None, money=None, bars=None):
    """A table. `money`: regex of amount columns; `bars`: regex of columns drawn as gradient bars."""
    overrides = list(overrides or [])
    if money:
        overrides.append(by_regex(money, ("unit", "locale"), ("decimals", 0), ("custom.align", "right")))
    if bars:
        overrides.append(by_regex(bars, ("custom.cellOptions", {"type": "gauge", "mode": "gradient",
                                                                "valueDisplayMode": "text"}),
                                  ("color", {"mode": "continuous-BlPu"}), ("custom.minWidth", 150)))  # fmt: skip
    return panel(
        "table", title, sql, description=description,
        options={"showHeader": True, "cellHeight": "md", "footer": {"show": False}},
        defaults={"custom": {"align": "auto", "filterable": False, "inspect": False, "minWidth": 70}},
        overrides=[by_regex("Role|Rol", ("custom.minWidth", 180))] + overrides,
    )


def link_to_posting(text, field, url_field="url"):
    return [
        by_name(field, ("links", [{"title": text, "url": "${__data.fields." + url_field + "}", "targetBlank": True}]),
                ("custom.minWidth", 260)),
        by_name(url_field, ("custom.hidden", True)),
    ]  # fmt: skip


def barchart(title, sql, x, horizontal=False, description="", unit=None, colors=None):
    """Bars shaded blue to purple by value; with `colors`, one fixed colour per series, stacked."""
    p = panel(
        "barchart", title, sql, description=description,
        options={"xField": x, "orientation": "horizontal" if horizontal else "vertical", "showValue": "auto",
                 "legend": {"showLegend": bool(colors), "displayMode": "list", "placement": "bottom"},
                 "barWidth": 0.75, "barRadius": 0.2, "xTickLabelRotation": 0, "tooltip": {"mode": "multi" if colors else "single"},
                 "stacking": "normal" if colors else "none"},
        defaults={"color": {"mode": "continuous-BlPu"}, "custom": {"fillOpacity": 90, "lineWidth": 0, "gradientMode": "scheme"}},
        overrides=series_colors(colors or {}),
    )  # fmt: skip
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if colors:
        p["fieldConfig"]["defaults"]["custom"]["gradientMode"] = "none"
    return p


def timeseries(title, sql, description="", style="bars", colors=None, shades=None, unit="locale"):
    custom = {"drawStyle": "bars", "fillOpacity": 85, "gradientMode": "none", "lineWidth": 0,
              "stacking": {"mode": "normal"}}  # fmt: skip
    if style == "points":
        custom = {"drawStyle": "points", "pointSize": 9}
    elif style == "line":
        custom = {"drawStyle": "line", "lineWidth": 2, "lineInterpolation": "linear", "fillOpacity": 18,
                  "gradientMode": "opacity", "showPoints": "never"}  # fmt: skip
    color = {"mode": "shades", "fixedColor": shades} if shades else {"mode": "palette-classic"}
    return panel(
        "timeseries", title, sql, fmt="time_series", description=description,
        options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                 "tooltip": {"mode": "multi", "sort": "desc"}},
        defaults={"custom": custom, "unit": unit, "color": color},
        overrides=series_colors(colors or {}),
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
        assert 24 % len(panels) == 0, len(panels)
        width, x = 24 // len(panels), 0
        colors = iter(ramp(len(panels)))
        for p in panels:
            color = next(colors)
            if p.pop("_ramp", False):
                p["fieldConfig"]["defaults"]["thresholds"]["steps"][0]["color"] = color
            p["gridPos"] = {"x": x, "y": self.y, "w": width, "h": height}
            self.panels.append(p)
            x += width
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


def query_var(name, label, sql, multi=False, all_option=False, description="", default=None):
    v = {"type": "query", "name": name, "label": label, "description": description, "datasource": DS,
         "query": sql, "definition": sql, "refresh": 1, "multi": multi, "includeAll": all_option, "sort": 0}  # fmt: skip
    if all_option:
        v["allValue"] = "'__all'"
        v["current"] = {"text": ["All"], "value": ["$__all"]}
    if default:  # {value: text}
        v["current"] = {"text": list(default.values()), "value": list(default)}
    return v


def labels_of(column):
    """Technology keys in an array column, as their labels, in the array's order."""
    return (f"array_to_string(ARRAY(SELECT t.label FROM unnest({column}) WITH ORDINALITY AS u(key, n) "
            f"JOIN silver.technologies t USING (key) ORDER BY n), ', ')")  # fmt: skip


# ----------------------------------------------------------------------------- dashboards


def build(lang):
    """The three dashboards in one language."""

    def t(en, es):
        return es if lang == "es" else en

    other = "es" if lang == "en" else "en"
    role_label = label_sql("role", {f.key: f.label(lang) for f in roles.ALL})
    region_names = {code: t(*names) for code, names in REGIONS.items()}
    region_label = label_sql("region", region_names)
    open_posting = t("Open posting", "Abrir oferta")

    def uid(name, language=lang):
        return f"jobpipe-{name}" + ("-es" if language == "es" else "")

    region_var = custom_var("region", t("Region", "Región"), [(region_names[c], c) for c in REGIONS],
                            ["ch", "es", "eu"], multi=True)  # fmt: skip

    def role_var(source):
        return query_var(
            "role", t("Role", "Rol"),
            f"SELECT role AS __value, {role_label} AS __text FROM {source} GROUP BY role ORDER BY count(*) DESC",
            multi=True, all_option=True, description=t("Role family, from the job title.", "Familia de puesto, deducida del título."),
        )  # fmt: skip

    def dashboard(name, title, grid, variables, time_from="now-1y", description=""):
        return {
            "uid": uid(name), "title": title, "description": description, "tags": ["jobpipe", lang],
            "timezone": "browser", "schemaVersion": 39, "version": 1, "editable": False, "graphTooltip": 1,
            "liveNow": False, "time": {"from": time_from, "to": "now"}, "refresh": "",
            "timepicker": {"refresh_intervals": []},
            "templating": {"list": variables}, "annotations": {"list": []},
            "links": [
                {"type": "dashboards", "tags": ["jobpipe", lang], "asDropdown": True,
                 "title": t("Other dashboards", "Otros paneles"), "includeVars": False, "keepTime": True},
                {"type": "link", "title": t("Español", "English"), "url": f"/d/{uid(name, other)}", "icon": "doc",
                 "tooltip": t("Ver en español", "View in English"), "includeVars": True, "keepTime": True,
                 "targetBlank": False, "asDropdown": False, "tags": []},
            ],
            "panels": grid.done(),
        }  # fmt: skip

    # ------------------------------------------------------------------------- feed

    feed_where = f"""{REGION_SQL}
  AND {any_of("role", "role")}
  AND coalesce(score, 0) * 100 >= ${{min_match:raw}}
  AND first_seen > now() - interval '1 day' * ${{new:raw}}"""
    know, lack = t("You know", "Conoces"), t("You lack", "Te falta")
    needs_profile = t("Needs config/profile.toml; run jobpipe load after editing it.",
                      "Necesita config/profile.toml; ejecuta jobpipe load después de editarlo.")  # fmt: skip

    feed = dashboard(
        "feed", t("For you", "Para ti"),
        description=t("Open postings that fit your profile, best match first, and what they ask for that you lack. ",
                      "Ofertas abiertas que encajan con tu perfil, de mejor a peor, y lo que piden que te falta. ")
        + needs_profile,
        time_from="now-90d",
        variables=[
            region_var,
            role_var("gold.feed"),
            custom_var("min_match", t("Match", "Encaje"),
                       [(t("Any", "Cualquiera"), "0"), ("50%+", "50"), ("70%+", "70"), ("90%+", "90")], ["0"],
                       description=t("Share of the technologies a posting asks for that you know.",
                                     "Porcentaje de las tecnologías que pide la oferta que conoces.")),
            custom_var("new", t("First seen", "Vista por primera vez"),
                       [(t("Any time", "Cuando sea"), "36500"), (t("Last 24 hours", "Últimas 24 horas"), "1"),
                        (t("Last 7 days", "Últimos 7 días"), "7"), (t("Last 30 days", "Últimos 30 días"), "30")],
                       ["36500"]),
        ],
        grid=Grid()
        .section(t("Summary", "Resumen"))
        .line(
            KPI_H,
            stat(t("Open postings for you", "Ofertas abiertas para ti"), f"SELECT count(*) FROM gold.feed WHERE {feed_where}",
                 description=needs_profile),
            stat(t("New this week", "Nuevas esta semana"),
                 f"SELECT count(*) FROM gold.feed WHERE {feed_where} AND first_seen > now() - interval '7 days'"),
            stat(t("Strong matches (70%+)", "Buen encaje (70 %+)"),
                 f"SELECT count(*) FROM gold.feed WHERE {feed_where} AND score >= 0.7"),
            stat(t("Median match", "Encaje mediano"),
                 f"SELECT 100 * percentile_cont(0.5) WITHIN GROUP (ORDER BY score) FROM gold.feed WHERE {feed_where}",
                 unit="percent"),
        )  # fmt: skip
        .section(t("Postings for you · best match first", "Ofertas para ti · de mejor a peor encaje"))
        .line(
            16,
            table(t("Click the title to open the posting", "Clic en el puesto para abrir la oferta"),
                  f"""
SELECT round(100 * score) AS "{t("Match", "Encaje")}", title AS "{t("Title", "Puesto")}",
       company AS "{t("Company", "Empresa")}", coalesce(location, country) AS "{t("Location", "Lugar")}",
       {labels_of("have")} AS "{know}", {labels_of("missing")} AS "{lack}",
       to_char(first_seen, 'YYYY-MM-DD') AS "{t("First seen", "Vista")}", source AS "{t("Source", "Fuente")}", url
FROM gold.feed
WHERE {feed_where}
ORDER BY rank DESC, cardinality(have) DESC, first_seen DESC
LIMIT 300
""", overrides=link_to_posting(open_posting, t("Title", "Puesto"))
                  + [by_name(t("Match", "Encaje"), ("unit", "percent"), ("min", 0), ("max", 100)),
                     by_regex(f"{know}|{lack}", ("custom.minWidth", 200))],
                  bars=t("Match", "Encaje"),
                  description=t("Postings that name no known technology have no match and come last. Ranking favours postings that name more of your skills.",
                                "Las ofertas que no nombran ninguna tecnología conocida no tienen encaje y salen al final. El orden favorece las que nombran más de tus tecnologías.")),
        )  # fmt: skip
        .section(t("What to learn", "Qué aprender"))
        .line(
            CHART_H + 2,
            barchart(t("What you lack most often · % of these postings", "Lo que más te falta · % de estas ofertas"),
                     f"""
SELECT t.label AS "{t("Technology", "Tecnología")}",
       round(100.0 * count(*) / nullif((SELECT count(*) FROM gold.feed WHERE {feed_where} AND score IS NOT NULL), 0), 1)
         AS "{t("Postings", "Ofertas")}"
FROM gold.feed f
CROSS JOIN LATERAL unnest(f.missing) AS u(key)
JOIN silver.technologies t USING (key)
WHERE {feed_where}
GROUP BY t.label ORDER BY 2 DESC, 1 LIMIT 15
""", x=t("Technology", "Tecnología"), horizontal=True, unit="percent",
                     description=t("Out of the postings above that name at least one technology.",
                                   "Sobre las ofertas de arriba que nombran al menos una tecnología.")),
            barchart(t("Most asked in these postings", "Lo más pedido en estas ofertas"),
                     f"""
SELECT t.label AS "{t("Technology", "Tecnología")}",
       nullif(count(*) FILTER (WHERE u.key = ANY(f.have)), 0) AS "{know}",
       nullif(count(*) FILTER (WHERE u.key = ANY(f.missing)), 0) AS "{lack}"
FROM gold.feed f
CROSS JOIN LATERAL unnest(f.have || f.missing) AS u(key)
JOIN silver.technologies t USING (key)
WHERE {feed_where}
GROUP BY t.label ORDER BY count(*) DESC, 1 LIMIT 15
""", x=t("Technology", "Tecnología"), horizontal=True, colors={know: BLUE, lack: PURPLE}),
        ),  # fmt: skip
    )

    # ------------------------------------------------------------------------- salaries

    where = f"""
currency = ${{currency:sqlstring}}
  AND {REGION_SQL}
  AND {any_of("role", "role")}
  AND (NOT predicted OR ${{predicted:raw}})
  AND $__timeFilter(posted_at)
"""

    def percentile(p):
        return f"SELECT percentile_cont({p}) WITHIN GROUP (ORDER BY midpoint) FROM gold.salaries WHERE {where}"

    offer = t("Your offer beats", "Tu oferta supera al")
    salaries = dashboard(
        "salaries", t("Salaries", "Salarios"),
        description=t("Salary ranges stated in postings. Gross per year, never converted between currencies.",
                      "Rangos salariales publicados en ofertas. Bruto anual, sin conversión de divisas."),
        variables=[
            region_var,
            role_var("gold.salaries"),
            query_var("currency", t("Currency", "Moneda"),
                      "SELECT currency FROM silver.posted_salaries GROUP BY 1 "
                      "ORDER BY array_position(ARRAY['CHF', 'EUR'], currency) NULLS LAST, count(*) DESC",
                      description=t("Amounts are never converted between currencies.",
                                    "Las cifras nunca se convierten entre monedas.")),
            custom_var("offer", t("Your offer (gross / year)", "Tu oferta (bruto anual)"),
                       [(f"{n // 1000}k", str(n)) for n in range(20000, 300001, 5000)], ["100000"],
                       description=t("Compare a figure with the postings in the chosen currency.",
                                     "Compara una cifra con las ofertas publicadas en la moneda elegida.")),
            custom_var("predicted", t("Adzuna estimates", "Estimaciones de Adzuna"),
                       [(t("Exclude", "Excluir"), "false"), (t("Include", "Incluir"), "true")], ["false"],
                       description=t("Adzuna estimates a salary for postings that do not state one. Better left out when negotiating.",
                                     "Adzuna estima el salario de ofertas que no lo publican. Mejor excluirlas para negociar.")),
            query_var("adzuna", t("Adzuna search", "Búsqueda en Adzuna"),
                      "SELECT DISTINCT country || ' | ' || coalesce(what, category, 'todo') FROM silver.adzuna_salary_histogram ORDER BY 1"),
        ],
        grid=Grid()
        .section(t("Summary · $currency, midpoint of the range", "Resumen · $currency, punto medio del rango"))
        .line(
            KPI_H,
            stat(t("Postings with salary", "Ofertas con salario"), f"SELECT count(*) FROM gold.salaries WHERE {where}"),
            stat("p25", percentile(0.25), description=t("One posting in four pays less than this.",
                                                        "Una de cada cuatro ofertas paga menos que esto.")),
            stat(t("Median", "Mediana"), percentile(0.5)),
            stat("p75", percentile(0.75), description=t("One posting in four pays more than this.",
                                                        "Una de cada cuatro ofertas paga más que esto.")),
            stat("p90", percentile(0.9)),
            stat(offer,
                 f"SELECT 100.0 * avg((midpoint <= ${{offer:sqlstring}}::numeric)::int) FROM gold.salaries WHERE {where}",
                 unit="percent", description=t("Share of postings whose midpoint is at or below your offer.",
                                               "Porcentaje de ofertas cuyo punto medio es menor o igual que tu oferta."),
                 steps=[{"color": FUCHSIA, "value": None}, {"color": PURPLE, "value": 25},
                        {"color": INDIGO, "value": 50}, {"color": BLUE, "value": 75}]),
        )  # fmt: skip
        .section(t("Distribution", "Distribución"))
        .line(
            CHART_H,
            panel("histogram", t("Midpoint of the range", "Punto medio del rango"),
                  f'SELECT midpoint AS "{t("Midpoint", "Punto medio")}" FROM gold.salaries WHERE {where}',
                  options={"bucketCount": 20, "combine": False, "legend": {"showLegend": False}},
                  defaults={"unit": "locale", "color": {"mode": "fixed", "fixedColor": INDIGO},
                            "custom": {"fillOpacity": 85, "lineWidth": 0, "gradientMode": "opacity"}}),
            table(t("By role", "Por rol"),
                  f"""
SELECT {role_label} AS "{t("Role", "Rol")}", count(*) AS "{t("Postings", "Ofertas")}",
       percentile_cont(0.25) WITHIN GROUP (ORDER BY midpoint) AS "p25",
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY midpoint) AS "{t("Median", "Mediana")}",
       percentile_cont(0.75) WITHIN GROUP (ORDER BY midpoint) AS "p75"
FROM gold.salaries WHERE {where}
GROUP BY role ORDER BY 4 DESC
""", money=f"p25|{t('Median', 'Mediana')}|p75", bars=t("Median", "Mediana")),
        )  # fmt: skip
        .section(t("Best-paying postings", "Ofertas mejor pagadas"))
        .line(
            TABLE_H,
            table(t("Highest ranges · click the title to open the posting",
                    "Rangos más altos · clic en el puesto para abrir la oferta"),
                  f"""
SELECT company AS "{t("Company", "Empresa")}", title AS "{t("Title", "Puesto")}", {role_label} AS "{t("Role", "Rol")}",
       coalesce(location, country) AS "{t("Location", "Lugar")}",
       min_annual AS "{t("Min", "Mínimo")}", max_annual AS "{t("Max", "Máximo")}",
       to_char(posted_at, 'YYYY-MM-DD') AS "{t("Posted", "Publicada")}", source AS "{t("Source", "Fuente")}", url
FROM gold.salaries WHERE {where}
ORDER BY max_annual DESC LIMIT 100
""", overrides=link_to_posting(open_posting, t("Title", "Puesto")),
                  money=f"{t('Min', 'Mínimo')}|{t('Max', 'Máximo')}", bars=t("Max", "Máximo")),
        )  # fmt: skip
        .section(t("External benchmarks", "Referencias externas"))
        .line(
            CHART_H,
            barchart(t("Adzuna · postings per salary band ($adzuna)", "Adzuna · ofertas por tramo salarial ($adzuna)"),
                     f"""
SELECT to_char(bucket_from, 'FM999G999') AS "{t("From", "Desde")}", postings AS "{t("Postings", "Ofertas")}"
FROM silver.adzuna_salary_histogram
WHERE country || ' | ' || coalesce(what, category, 'todo') = ${{adzuna:sqlstring}}
ORDER BY bucket_from
""", x=t("From", "Desde"), description=t("Advertised salaries on Adzuna for your search. Jobs by Adzuna.",
                                         "Salarios anunciados en Adzuna para tu búsqueda. Jobs by Adzuna.")),
            timeseries(t("Adzuna · average advertised salary per month", "Adzuna · salario medio anunciado por mes"),
                       """
SELECT month::timestamptz AS time, country || ' ' || category AS metric, avg_salary AS value
FROM silver.adzuna_salary_history ORDER BY 1
""", style="line", shades=VIOLET,
                       description=t("Average for the whole category; Adzuna does not give it per keyword. Jobs by Adzuna.",
                                     "Media de la categoría completa; Adzuna no la da por palabra clave. Jobs by Adzuna.")),
        )  # fmt: skip
        .line(
            CHART_H,
            table(t("Levels.fyi · actual pay by location (USD)", "Levels.fyi · compensación real por ubicación (USD)"),
                  f"""
SELECT job_family AS "{t("Family", "Familia")}", salary_type AS "{t("Type", "Tipo")}", focus_tags AS "{t("Focus", "Foco")}",
       location AS "{t("Location", "Ubicación")}",
       coalesce(yoe_range || ' {t("years", "años")}', '{t("all", "todos")}') AS "{t("Experience", "Experiencia")}",
       p25, p50 AS "{t("Median", "Mediana")}", p75, p90, sample_size AS "{t("Samples", "Muestras")}"
FROM silver.levelsfyi_benchmarks
ORDER BY location, kind DESC, yoe_range
""", money=f"p25|{t('Median', 'Mediana')}|p75|p90", bars=t("Median", "Mediana"),
                  description=t("Data source: Levels.fyi (https://www.levels.fyi). Only with the official API (LEVELS_FYI_API_KEY).",
                                "Data source: Levels.fyi (https://www.levels.fyi). Solo con la API oficial (LEVELS_FYI_API_KEY).")),
        ),  # fmt: skip
    )

    # ------------------------------------------------------------------------- market

    posting_where = f"""{REGION_SQL}
  AND {any_of("role", "role")}
  AND {any_of("company", "company")}"""
    has_salary = """EXISTS (SELECT 1 FROM silver.posted_salaries s
        WHERE s.source = p.source AND s.source_id = p.source_id AND NOT s.predicted)"""

    market = dashboard(
        "market", t("Market and postings", "Mercado y ofertas"),
        description=t("Postings per month and region, who is hiring, and the list of postings.",
                      "Volumen de ofertas por mes y región, quién contrata, y lista de ofertas."),
        time_from="now-2y",
        variables=[
            region_var,
            role_var("silver.postings"),
            query_var("company", t("Company", "Empresa"),
                      "SELECT company FROM silver.postings WHERE company IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 500",
                      multi=True, all_option=True,
                      description=t("The 500 companies with the most postings.", "Las 500 empresas con más ofertas.")),
            query_var("technology", t("Technologies (trend)", "Tecnologías (tendencia)"),
                      "SELECT key AS __value, label AS __text FROM silver.technologies ORDER BY lower(label)",
                      multi=True, default={k: tech.BY_KEY[k].label for k in ("python", "sql", "kafka", "dbt")}),
            custom_var("with_salary", t("Salary", "Salario"),
                       [(t("All postings", "Todas las ofertas"), "false"),
                        (t("Only with a stated salary", "Solo con salario publicado"), "true")], ["false"]),
        ],
        grid=Grid()
        .section(t("Summary", "Resumen"))
        .line(
            KPI_H,
            stat(t("Seen in the last 7 days", "Vistas en los últimos 7 días"),
                 f"SELECT count(*) FROM silver.postings WHERE last_seen > now() - interval '7 days' AND {posting_where}"),
            stat(t("New in the last 30 days", "Nuevas en los últimos 30 días"),
                 f"SELECT count(*) FROM silver.postings WHERE coalesce(published, first_seen) > now() - interval '30 days' AND {posting_where}"),
            stat(t("Companies hiring (90 days)", "Empresas contratando (90 días)"),
                 f"SELECT count(DISTINCT lower(company)) FROM silver.postings WHERE last_seen > now() - interval '90 days' AND {posting_where}"),
            stat(t("With a stated salary", "Con salario publicado"),
                 f"SELECT 100.0 * count(*) FILTER (WHERE {has_salary}) / nullif(count(*), 0) FROM silver.postings p WHERE {posting_where}",
                 unit="percent", decimals=1),
        )  # fmt: skip
        .section(t("Trend", "Tendencia"))
        .line(
            CHART_H,
            timeseries(t("Postings per month and region", "Ofertas publicadas por mes y región"),
                       f"""
SELECT month::timestamptz AS time, {region_label} AS metric, sum(postings) AS value
FROM gold.postings_monthly
WHERE $__timeFilter(month::timestamptz) AND region IN ($region) AND {any_of("role", "role")}
GROUP BY 1, region ORDER BY 1
""", colors={region_names[c]: REGION_COLORS[c] for c in REGIONS},
                       description=t("Publication date from the source, or the first time it was seen. HN goes back to 2011.",
                                     "Fecha de publicación según la fuente; si no la da, la primera vez que se vio. HN aporta la historia desde 2011.")),
        )  # fmt: skip
        .section(t("Who is hiring (90 days)", "Quién contrata (90 días)"))
        .line(
            CHART_H,
            table(t("Companies with the most postings", "Empresas con más ofertas"),
                  f"""
SELECT company AS "{t("Company", "Empresa")}", count(*) AS "{t("Postings", "Ofertas")}",
       to_char(max(coalesce(published, first_seen)), 'YYYY-MM-DD') AS "{t("Latest", "Última")}"
FROM silver.postings
WHERE company IS NOT NULL AND last_seen > now() - interval '90 days' AND {posting_where}
GROUP BY 1 ORDER BY 2 DESC LIMIT 50
""", bars=t("Postings", "Ofertas")),
            barchart(t("Postings by role", "Ofertas por rol"),
                     f"""
SELECT {role_label} AS "{t("Role", "Rol")}", count(*) AS "{t("Postings", "Ofertas")}"
FROM silver.postings
WHERE last_seen > now() - interval '90 days' AND {posting_where}
GROUP BY role ORDER BY 2 DESC
""", x=t("Role", "Rol"), horizontal=True),
        )  # fmt: skip
        .section(t("Technologies", "Tecnologías"))
        .line(
            CHART_H + 2,
            barchart(t("Most asked · % of postings in the period", "Lo más pedido · % de las ofertas del periodo"),
                     f"""
SELECT t.label AS "{t("Technology", "Tecnología")}",
       round(100.0 * count(*) / nullif((SELECT count(*) FROM silver.postings
                                         WHERE {posting_where} AND $__timeFilter(coalesce(published, first_seen))
                                        ), 0), 1) AS "{t("Postings", "Ofertas")}"
FROM silver.postings p
CROSS JOIN LATERAL unnest(p.technologies) AS u(key)
JOIN silver.technologies t USING (key)
WHERE {posting_where} AND $__timeFilter(coalesce(p.published, p.first_seen))
GROUP BY t.label ORDER BY 2 DESC, 1 LIMIT 20
""", x=t("Technology", "Tecnología"), horizontal=True, unit="percent",
                     description=t("From the title and description of each posting, see src/jobpipe/tech.py.",
                                   "Sacado del título y la descripción de cada oferta, ver src/jobpipe/tech.py.")),
            timeseries(t("Share of postings asking for each technology, per month", "Porcentaje de ofertas que pide cada tecnología, por mes"),
                       f"""
SELECT date_trunc('month', coalesce(p.published, p.first_seen)) AS time, t.label AS metric,
       100.0 * count(*) FILTER (WHERE t.key = ANY(p.technologies)) / count(*) AS value
FROM silver.postings p
CROSS JOIN silver.technologies t
WHERE t.key IN ($technology) AND {posting_where} AND $__timeFilter(coalesce(p.published, p.first_seen))
GROUP BY 1, 2 HAVING count(*) >= 10 ORDER BY 1
""", style="line", unit="percent", colors=dict(zip(["Python", "SQL", "Kafka", "dbt"], [BLUE, INDIGO, PURPLE, FUCHSIA])),
                       description=t("Months with fewer than 10 postings are left out. HN goes back to 2011; the other sources only have what was open when collected.",
                                     "Se omiten los meses con menos de 10 ofertas. HN llega hasta 2011; las demás fuentes solo tienen lo que estaba abierto al recogerlas.")),
        )  # fmt: skip
        .section(t("Postings", "Ofertas"))
        .line(
            16,
            table(t("Postings in the period · click the title to open the posting",
                    "Ofertas del periodo · clic en el puesto para abrir la oferta"),
                  f"""
SELECT to_char(coalesce(p.published, p.first_seen), 'YYYY-MM-DD') AS "{t("Posted", "Publicada")}",
       p.company AS "{t("Company", "Empresa")}", p.title AS "{t("Title", "Puesto")}", {role_label} AS "{t("Role", "Rol")}",
       coalesce(p.location, p.country) AS "{t("Location", "Lugar")}", (SELECT string_agg({region_label}, ', ') FROM unnest(p.regions) AS r(region)) AS "{t("Region", "Región")}",
       (SELECT string_agg(s.currency || ' ' || round(s.min_annual / 1000) || 'k–' || round(s.max_annual / 1000) || 'k', ' / ')
          FROM silver.posted_salaries s
         WHERE s.source = p.source AND s.source_id = p.source_id AND NOT s.predicted) AS "{t("Salary", "Salario")}",
       p.source AS "{t("Source", "Fuente")}", p.url
FROM silver.postings p
WHERE {posting_where}
  AND $__timeFilter(coalesce(p.published, p.first_seen))
  AND (NOT ${{with_salary:raw}} OR {has_salary})
ORDER BY 1 DESC NULLS LAST LIMIT 500
""", overrides=link_to_posting(open_posting, t("Title", "Puesto"))),
        ),  # fmt: skip
    )

    # ------------------------------------------------------------------------- pipeline

    pipeline = dashboard(
        "pipeline", t("Pipeline health", "Salud del pipeline"),
        description=t("What was collected, when, and whether a source stopped returning data.",
                      "Qué se ha recogido, cuándo, y si alguna fuente ha dejado de devolver datos."),
        time_from="now-30d",
        variables=[],
        grid=Grid()
        .section(t("Status", "Estado"))
        .line(
            KPI_H,
            stat(t("Last load into PostgreSQL", "Última carga en PostgreSQL"),
                 "SELECT extract(epoch FROM max(loaded_at)) * 1000 FROM silver.load_log", unit="dateTimeFromNow"),
            stat(t("Postings in silver", "Ofertas en silver"), "SELECT count(*) FROM silver.postings"),
            stat(t("Runs in the period", "Ejecuciones en el periodo"),
                 "SELECT count(*) FROM silver.ingest_runs WHERE $__timeFilter(coalesce(last_fetched, ingest_date::timestamptz))"),
            stat(t("Days without data (worst source)", "Días sin recoger (peor fuente)"),
                 "SELECT max(current_date - last_ingest) FROM gold.source_health WHERE source NOT IN ('adzuna_salary', 'levelsfyi')",
                 steps=[{"color": BLUE, "value": None}, {"color": PURPLE, "value": 2}, {"color": FUCHSIA, "value": 7}]),
        )  # fmt: skip
        .section(t("By source", "Por fuente"))
        .line(
            CHART_H,
            table(t("Sources", "Fuentes"),
                  f"""
SELECT source AS "{t("Source", "Fuente")}", runs AS "{t("Runs", "Ejecuciones")}", records AS "{t("Records", "Registros")}",
       to_char(last_ingest, 'YYYY-MM-DD') AS "{t("Last run", "Última recogida")}", current_date - last_ingest AS "{t("Days", "Días")}"
FROM gold.source_health ORDER BY 1
""", bars=t("Records", "Registros")),
            timeseries(t("Records per run", "Registros por ejecución"),
                       """
SELECT coalesce(last_fetched, ingest_date::timestamptz) AS time, source AS metric, records AS value
FROM silver.ingest_runs
WHERE $__timeFilter(coalesce(last_fetched, ingest_date::timestamptz))
ORDER BY 1
""", style="points", colors=dict(zip(SOURCES, ramp(len(SOURCES), SKY, FUCHSIA)))),
        ),  # fmt: skip
    )
    return {"feed": feed, "salaries": salaries, "market": market, "pipeline": pipeline}


for lang in LANGS:
    folder = OUT / lang
    folder.mkdir(parents=True, exist_ok=True)
    for name, board in build(lang).items():
        (folder / f"{name}.json").write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{lang}/{name}", len(board["panels"]), "panels")
