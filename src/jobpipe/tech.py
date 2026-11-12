"""Technologies a posting asks for, found in its title and description.

A fixed catalogue of patterns rather than free keyword extraction: the result
has to be comparable month to month and against your profile, so "Postgres",
"PostgreSQL" and "postgres" must all land on the same key, and a new spelling
is added here once instead of polluting every chart.

Patterns are case-insensitive. The ambiguous names are the hard part: "Go" is
matched only capitalised and not as a verb ("Go deep"), Java never matches
JavaScript, "React" never matches React Native. R and C are left out: too many
false positives for the few postings they would add. A company's own
product does not count: every Datadog posting mentions Datadog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Technology:
    key: str
    label: str
    category: str
    pattern: str
    # Lowercase words the pattern cannot match without, "|"-separated (default: the key).
    # Checked with ``in`` before the regex runs: most postings name few technologies,
    # and a substring test is far cheaper than 80 regex searches over a long description.
    needles: str = ""


CATEGORIES = {
    "language": ("Languages", "Lenguajes"),
    "data": ("Data", "Datos"),
    "database": ("Databases", "Bases de datos"),
    "cloud": ("Cloud", "Nube"),
    "infra": ("Infrastructure", "Infraestructura"),
    "observability": ("Observability", "Observabilidad"),
    "ml": ("ML / AI", "ML / IA"),
    "web": ("Web frameworks", "Frameworks web"),
    "mobile": ("Mobile", "Móvil"),
}

CATALOGUE: tuple[Technology, ...] = (
    Technology("python", "Python", "language", r"\bpython\b"),
    Technology("java", "Java", "language", r"\bjava\b(?![ -]?script)"),
    Technology("javascript", "JavaScript", "language", r"\bjavascript\b"),
    Technology("typescript", "TypeScript", "language", r"\btypescript\b"),
    # "Go deep", "Go onsite", "Go to market" are the verb: a capitalised Go
    # followed by a lowercase word only counts when the word is about code.
    Technology("go", "Go", "language",
               r"\bgolang\b|(?-i:\bGo\b)(?![- ]to\b|-live\b|-getter)"
               r"(?!\s+(?!(?:and|or|fluency|runtime|code|services|microservices|experience|programming|backend"
               r"|developers?|engineers?|modules?|is)\b)(?-i:[a-z]))"),
    Technology("rust", "Rust", "language", r"\brust\b"),
    Technology("scala", "Scala", "language", r"\bscala\b"),
    Technology("kotlin", "Kotlin", "language", r"\bkotlin\b"),
    Technology("csharp", "C# / .NET", "language", r"(?<!\w)c#|\.net\b|\bdotnet\b", "c#|.net|dotnet"),
    Technology("cpp", "C++", "language", r"(?<!\w)c\+\+", "c++"),
    Technology("ruby", "Ruby", "language", r"\bruby\b"),
    Technology("php", "PHP", "language", r"\bphp\b"),
    Technology("elixir", "Elixir", "language", r"\belixir\b"),
    Technology("swift", "Swift", "language", r"\bswift\b(?!ui)|\bswiftui\b"),
    Technology("sql", "SQL", "language", r"\bsql\b"),
    Technology("spark", "Spark", "data", r"\b(py)?spark\b"),
    Technology("kafka", "Kafka", "data", r"\bkafka\b"),
    Technology("flink", "Flink", "data", r"\bflink\b"),
    Technology("airflow", "Airflow", "data", r"\bairflow\b"),
    Technology("dbt", "dbt", "data", r"\bdbt\b"),
    Technology("dagster", "Dagster", "data", r"\bdagster\b"),
    Technology("snowflake", "Snowflake", "data", r"\bsnowflake\b"),
    Technology("bigquery", "BigQuery", "data", r"\bbig ?query\b", "query"),
    Technology("redshift", "Redshift", "data", r"\bredshift\b"),
    Technology("databricks", "Databricks", "data", r"\bdatabricks\b"),
    Technology("hadoop", "Hadoop", "data", r"\bhadoop\b"),
    Technology("trino", "Trino / Presto", "data", r"\btrino\b|\bpresto(db)?\b", "trino|presto"),
    Technology("iceberg", "Iceberg", "data", r"\biceberg\b"),
    Technology("pandas", "pandas", "data", r"\bpandas\b"),
    Technology("tableau", "Tableau", "data", r"\btableau\b"),
    Technology("powerbi", "Power BI", "data", r"\bpower ?bi\b", "power"),
    Technology("looker", "Looker", "data", r"\blooker\b"),
    Technology("postgresql", "PostgreSQL", "database", r"\bpostgres(ql)?\b", "postgres"),
    Technology("mysql", "MySQL", "database", r"\bmysql\b|\bmariadb\b", "mysql|mariadb"),
    Technology("mongodb", "MongoDB", "database", r"\bmongo(db)?\b", "mongo"),
    Technology("redis", "Redis", "database", r"\bredis\b"),
    Technology("elasticsearch", "Elasticsearch", "database", r"\belastic ?search\b|\bopensearch\b", "elastic|opensearch"),
    Technology("cassandra", "Cassandra", "database", r"\bcassandra\b"),
    Technology("dynamodb", "DynamoDB", "database", r"\bdynamo ?db\b", "dynamo"),
    Technology("clickhouse", "ClickHouse", "database", r"\bclickhouse\b"),
    Technology("duckdb", "DuckDB", "database", r"\bduckdb\b"),
    Technology("aws", "AWS", "cloud", r"\baws\b|amazon web services", "aws|amazon web services"),
    Technology("gcp", "Google Cloud", "cloud", r"\bgcp\b|google cloud", "gcp|google cloud"),
    Technology("azure", "Azure", "cloud", r"\bazure\b"),
    Technology("kubernetes", "Kubernetes", "infra", r"\bkubernetes\b|\bk8s\b", "kubernetes|k8s"),
    Technology("docker", "Docker", "infra", r"\bdocker\b"),
    Technology("terraform", "Terraform", "infra", r"\bterraform\b"),
    Technology("ansible", "Ansible", "infra", r"\bansible\b"),
    Technology("helm", "Helm", "infra", r"\bhelm\b"),
    Technology("linux", "Linux", "infra", r"\blinux\b"),
    Technology("prometheus", "Prometheus", "observability", r"\bprometheus\b"),
    Technology("grafana", "Grafana", "observability", r"\bgrafana\b"),
    Technology("datadog", "Datadog", "observability", r"\bdatadog\b"),
    Technology("opentelemetry", "OpenTelemetry", "observability", r"\bopentelemetry\b|\botel\b", "opentelemetry|otel"),
    Technology("pytorch", "PyTorch", "ml", r"\bpytorch\b"),
    Technology("tensorflow", "TensorFlow", "ml", r"\btensorflow\b"),
    Technology("sklearn", "scikit-learn", "ml", r"\bscikit[- ]learn\b|\bsklearn\b", "scikit|sklearn"),
    Technology("llm", "LLMs", "ml", r"\bllms?\b|large language models?", "llm|large language model"),
    Technology("react", "React", "web", r"\breact(\.?js)?\b(?! native)"),
    Technology("vue", "Vue", "web", r"\bvue(\.?js)?\b"),
    Technology("angular", "Angular", "web", r"\bangular(js)?\b"),
    Technology("nodejs", "Node.js", "web", r"\bnode\.?js\b", "node"),
    Technology("django", "Django", "web", r"\bdjango\b"),
    Technology("flask", "Flask", "web", r"\bflask\b"),
    Technology("fastapi", "FastAPI", "web", r"\bfastapi\b"),
    Technology("spring", "Spring", "web", r"\bspring ?boot\b|\bspring framework\b"),
    Technology("rails", "Rails", "web", r"\brails\b"),
    Technology("graphql", "GraphQL", "web", r"\bgraphql\b"),
    Technology("grpc", "gRPC", "web", r"\bgrpc\b"),
    Technology("ios", "iOS", "mobile", r"\bios\b"),
    Technology("android", "Android", "mobile", r"\bandroid\b"),
    Technology("flutter", "Flutter", "mobile", r"\bflutter\b"),
    Technology("react_native", "React Native", "mobile", r"\breact native\b", "react native"),
)  # fmt: skip

BY_KEY = {tech.key: tech for tech in CATALOGUE}
_COMPILED = tuple(
    (tech.key, tuple((tech.needles or tech.key).split("|")), re.compile(tech.pattern, re.IGNORECASE))
    for tech in CATALOGUE
)


def technologies_in(text: str | None, company: str | None = None) -> tuple[str, ...]:
    """Keys of every catalogued technology mentioned in ``text``, in catalogue order.

    Technologies named like ``company`` are left out ("Grafana Labs" drops grafana).
    """
    if not text:
        return ()
    own = (company or "").lower().replace(" ", "")
    # casefold() as the regex flag folds case, plus Turkish dotted and dotless i ("LİNUX", "lınux").
    folded = text.casefold().replace("ı", "i").replace("̇", "")
    return tuple(
        key for key, needles, pattern in _COMPILED
        if any(n in folded for n in needles) and pattern.search(text) and not (own and key in own)
    )  # fmt: skip
