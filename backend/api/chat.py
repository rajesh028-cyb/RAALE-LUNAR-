"""
Schema-Aware, Rule-Based Chat Engine  v3.

Pipeline for every question:
  1. Schema Discovery  — fetch column names from Neo4j (scoped to active dataset)
  2. ColumnMatcher     — map question tokens to real columns (fuzzy + plural)
  3. IntentClassifier  — classify intent from regex patterns
  4. CypherGenerator   — build a parameterized, dataset-scoped Cypher query
  5. QueryExecutor     — execute against Neo4j, format a natural-language answer

No external LLM, no LangChain, no OpenAI — pure deterministic graph queries.
Every answer is grounded in Neo4j data for the specified dataset.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver

from backend.common.logging_config import get_logger

logger = get_logger("chat_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNKNOWN_ANSWER = (
    "I don't have enough information in the uploaded dataset to answer that question."
)

NUMERIC_HINTS = [
    "salary", "age", "amount", "score", "price", "revenue", "cost",
    "count", "number", "qty", "quantity", "total", "value", "rate",
    "income", "budget", "sales", "profit", "loss", "volume", "weight",
    "height", "distance", "temp", "temperature", "size", "length",
    "width", "balance", "units", "fee", "tax", "discount", "order",
    "payment", "rating", "rank", "index", "percent",
]

_FILTER_STOP_WORDS = {
    "who", "what", "which", "where", "when", "how", "why",
    "list", "show", "find", "give", "tell", "get", "all", "the",
    "a", "an", "is", "are", "in", "of", "for", "do", "does",
    "work", "works", "have", "has", "employees", "employee", "people",
    "person", "staff", "departments", "department", "values", "value",
    "rows", "records", "average", "count", "total", "number",
    "maximum", "minimum", "max", "min", "mean", "unique", "distinct",
    "many", "much", "there", "i", "my", "with", "were", "was",
    "sum", "combined", "aggregate", "between", "and", "or", "not",
}

# ---------------------------------------------------------------------------
# Intent patterns — ordered by priority, first match wins.
# ---------------------------------------------------------------------------

INTENT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("lookup",         [r"\bwhat\s+(is|are)\b", r"\bwhich\b", r"\bwho\s+(is|are)\b", r"\bwhose\b", r"\bwhere\s+does\b"]),
    ("count_distinct", [r"\bhow\s+many\b", r"\bnumber\s+of\b", r"\bhow\s+much\b"]),
    ("average",        [r"\baverage\b",  r"\bavg\b",     r"\bmean\b"]),
    ("sum",            [r"\btotal\b",    r"\bsum\b",     r"\bcombined\b", r"\baggregate\b"]),
    ("maximum",        [r"\bmaximum\b",  r"\bmax\b",     r"\bhighest\b",  r"\blargest\b",  r"\bbiggest\b"]),
    ("minimum",        [r"\bminimum\b",  r"\bmin\b",     r"\blowest\b",   r"\bsmallest\b"]),
    ("count_all",      [r"\bcount\b"]),
    ("list_distinct",  [r"\bunique\b",   r"\bdistinct\b", r"\bdifferent\b"]),
    ("filter",         [r"\bfind\b",     r"\bsearch\b",  r"\bfilter\b",   r"\bwhere\b",    r"\bwith\b",
                        r"\bwho\s+(is|are|work|works|belong|belongs)\b",
                        r"\bstaff\s+in\b", r"\bpeople\s+in\b"]),
    ("list_all",       [r"\blist\b",     r"\bshow\b",    r"\bsee\b",      r"\bdisplay\b",
                        r"\ball\b",      r"\beveryone\b", r"\beverything\b",
                        r"\brows\b",     r"\brecords\b"]),
]

_COLUMN_REQUIRED = {"count_distinct", "list_distinct", "average", "sum", "maximum", "minimum"}


# ---------------------------------------------------------------------------
# Column Matcher
# ---------------------------------------------------------------------------

def _depluralize(word: str) -> List[str]:
    w = word.lower()
    candidates: List[str] = [w]
    if w.endswith("ies") and len(w) > 4:
        candidates.append(w[:-3] + "y")
    if w.endswith("ses") or w.endswith("xes"):
        candidates.append(w[:-2])
    if w.endswith("ves"):
        candidates.append(w[:-3] + "f")
    if w.endswith("oes"):
        candidates.append(w[:-2])
    if w.endswith("es") and len(w) > 3:
        candidates.append(w[:-2])
        candidates.append(w[:-1])
    if w.endswith("s") and len(w) > 3:
        candidates.append(w[:-1])
    return list(dict.fromkeys(candidates))


def match_column(token: str, columns: List[str]) -> Optional[str]:
    t = token.lower()
    col_map: Dict[str, str] = {c.lower(): c for c in columns}
    if t in col_map:
        return col_map[t]
    for candidate in _depluralize(t):
        if candidate in col_map:
            return col_map[candidate]
    if len(t) >= 3:
        for col_key, col_orig in col_map.items():
            if t in col_key or col_key in t:
                return col_orig
    return None


def find_column_in_question(question: str, columns: List[str]) -> Optional[str]:
    q_lower = question.lower()
    col_map_lower: Dict[str, str] = {c.lower(): c for c in columns}
    for col_key, col_orig in col_map_lower.items():
        if col_key in q_lower:
            return col_orig
    for word in re.findall(r"\b[a-zA-Z]\w+\b", question):
        result = match_column(word, columns)
        if result:
            return result
    return None


def is_numeric_column(col: str) -> bool:
    return any(hint in col.lower() for hint in NUMERIC_HINTS)


def _first_numeric_column(columns: List[str]) -> Optional[str]:
    for col in columns:
        if is_numeric_column(col):
            return col
    return None


# ---------------------------------------------------------------------------
# Intent Classifier
# ---------------------------------------------------------------------------

def classify_intent(question: str) -> str:
    q = question.lower().strip()
    for intent_name, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, q):
                return intent_name
    return "unknown"


# ---------------------------------------------------------------------------
# Filter-value extractor & Entity Prober
# ---------------------------------------------------------------------------

def extract_candidate_entities(question: str, columns: List[str], matched_column: Optional[str] = None) -> List[str]:
    quoted = re.findall(r'["\']([^"\']+)["\']', question)
    title_case = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', question)
    
    candidates = []
    candidates.extend(quoted)
    candidates.extend(title_case)
    
    stop_words = {"What", "Which", "Who", "How", "Show", "List", "Find", "Where", "When", "The", "All"}
    cleaned = []
    for c in candidates:
        if c not in stop_words and len(c) > 2:
            cleaned.append(c)
            
    col_names_lower = {c.lower() for c in columns}
    matched_col_lower = matched_column.lower() if matched_column else ""
    for word in re.findall(r"\b[a-zA-Z]+\b", question):
        w_low = word.lower()
        if w_low not in _FILTER_STOP_WORDS and w_low not in col_names_lower and len(w_low) > 2:
            if matched_col_lower and w_low in matched_col_lower:
                continue
            cleaned.append(word)
            
    return list(dict.fromkeys(cleaned))

def probe_entity_column(driver: Driver, dataset_name: str, entity: str) -> Optional[str]:
    cypher = f"""
    MATCH (d:Dataset {{name: $ds}})-[:HAS_ROW]->(r:Row)
    UNWIND keys(r) AS col
    WITH r, col WHERE toLower(toString(r[col])) CONTAINS toLower($entity)
    RETURN col AS matched_column, count(r) AS matches
    ORDER BY matches DESC LIMIT 1
    """
    try:
        with driver.session() as session:
            res = session.run(cypher, ds=dataset_name, entity=entity)
            record = res.single()
            if record:
                return record["matched_column"]
    except Exception as e:
        logger.error(f"Entity probe failed: {e}")
    return None

def extract_filter_value(question: str, columns: List[str]) -> Optional[str]:
    quoted = re.findall(r'["\']([^"\']+)["\']', question)
    if quoted:
        return quoted[0].strip()
    col_names_lower = {c.lower() for c in columns}
    for word in re.findall(r"\b[A-Z][a-zA-Z]*\b", question):
        if word.lower() not in _FILTER_STOP_WORDS and word.lower() not in col_names_lower:
            return word
    return None


# ---------------------------------------------------------------------------
# Cypher Generator
# ---------------------------------------------------------------------------

class CypherGenerator:
    """
    Builds dataset-scoped, fully-parameterised Cypher queries.
    User-supplied values are NEVER concatenated into the query string.
    When dataset_name is given, queries are scoped to that specific dataset node.
    """

    @staticmethod
    def _ds_match(dataset_name: Optional[str]) -> Tuple[str, Dict[str, Any]]:
        """
        Return (MATCH prefix, base_params) scoped to the given dataset.
        When dataset_name is None the query spans all datasets (fallback only).
        """
        if dataset_name:
            return (
                "MATCH (d:Dataset {name: $ds})-[:HAS_ROW]->(r:Row)",
                {"ds": dataset_name},
            )
        return "MATCH (d:Dataset)-[:HAS_ROW]->(r:Row)", {}

    def generate(
        self,
        intent: str,
        columns: List[str],
        matched_column: Optional[str],
        filter_value: Optional[str],
        dataset_name: Optional[str] = None,
        probed_entity: Optional[str] = None,
        probed_entity_col: Optional[str] = None,
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """Returns (cypher_string, params_dict) or (None, {})."""
        if not columns:
            return None, {}

        m, bp = self._ds_match(dataset_name)

        if intent == "count_distinct":
            if matched_column:
                if probed_entity and probed_entity_col:
                    return (
                        f"{m} WHERE toLower(toString(r.`{probed_entity_col}`)) CONTAINS toLower($entity) "
                        f"RETURN COUNT(DISTINCT r.`{matched_column}`) AS total",
                        {**bp, "entity": probed_entity},
                    )
                return (
                    f"{m} RETURN COUNT(DISTINCT r.`{matched_column}`) AS total",
                    {**bp},
                )
            intent = "count_all" # fallback to count_all if no col

        if intent == "count_all":
            if probed_entity and probed_entity_col:
                return (
                    f"{m} WHERE toLower(toString(r.`{probed_entity_col}`)) CONTAINS toLower($entity) "
                    f"RETURN count(r) AS total",
                    {**bp, "entity": probed_entity},
                )
            return (f"{m} RETURN count(r) AS total", {**bp})

        if intent == "average":
            col = matched_column or _first_numeric_column(columns)
            if not col:
                return None, {}
            return (
                f"{m} WHERE r.`{col}` IS NOT NULL "
                f"RETURN AVG(toFloat(r.`{col}`)) AS result",
                {**bp},
            )

        if intent == "sum":
            col = matched_column or _first_numeric_column(columns)
            if not col:
                return None, {}
            return (
                f"{m} WHERE r.`{col}` IS NOT NULL "
                f"RETURN SUM(toFloat(r.`{col}`)) AS result",
                {**bp},
            )

        if intent == "maximum":
            col = matched_column or _first_numeric_column(columns)
            if not col:
                return None, {}
            return (
                f"{m} WHERE r.`{col}` IS NOT NULL "
                f"RETURN MAX(toFloat(r.`{col}`)) AS result",
                {**bp},
            )

        if intent == "minimum":
            col = matched_column or _first_numeric_column(columns)
            if not col:
                return None, {}
            return (
                f"{m} WHERE r.`{col}` IS NOT NULL "
                f"RETURN MIN(toFloat(r.`{col}`)) AS result",
                {**bp},
            )

        if intent == "list_distinct":
            col = matched_column or columns[0]
            return (
                f"{m} RETURN DISTINCT r.`{col}` AS `{col}` ORDER BY `{col}`",
                {**bp},
            )

        if intent == "lookup" or intent == "filter":
            if probed_entity and probed_entity_col:
                if matched_column and matched_column != probed_entity_col:
                    limit_clause = " LIMIT 1" if intent == "lookup" else ""
                    return (
                        f"{m} WHERE toLower(toString(r.`{probed_entity_col}`)) CONTAINS toLower($entity) "
                        f"RETURN r.`{matched_column}` AS `{matched_column}`{limit_clause}",
                        {**bp, "entity": probed_entity},
                    )
                else:
                    props = ", ".join(f"r.`{c}` AS `{c}`" for c in columns)
                    return (
                        f"{m} WHERE toLower(toString(r.`{probed_entity_col}`)) CONTAINS toLower($entity) "
                        f"RETURN {props}",
                        {**bp, "entity": probed_entity},
                    )

            if intent == "lookup":
                return None, {}

            if matched_column and filter_value:
                props = ", ".join(f"r.`{c}` AS `{c}`" for c in columns)
                return (
                    f"{m} WHERE toLower(toString(r.`{matched_column}`)) CONTAINS toLower($value) "
                    f"RETURN {props}",
                    {**bp, "value": filter_value},
                )
            if matched_column:
                return (
                    f"{m} RETURN DISTINCT r.`{matched_column}` AS `{matched_column}` "
                    f"ORDER BY `{matched_column}`",
                    {**bp},
                )
            return self._list_all(m, columns, bp)

        if intent == "list_all":
            if matched_column:
                return (
                    f"{m} RETURN DISTINCT r.`{matched_column}` AS `{matched_column}` "
                    f"ORDER BY `{matched_column}`",
                    {**bp},
                )
            return self._list_all(m, columns, bp)

        return None, {}

    @staticmethod
    def _list_all(match: str, columns: List[str], base_params: Dict) -> Tuple[str, Dict]:
        props = ", ".join(f"r.`{c}` AS `{c}`" for c in columns)
        return f"{match} RETURN {props}", {**base_params}


# ---------------------------------------------------------------------------
# Query Executor
# ---------------------------------------------------------------------------

class QueryExecutor:
    """Runs a Cypher query and formats a natural-language answer."""

    def execute(
        self,
        driver: Driver,
        cypher: str,
        params: Dict[str, Any],
        intent: str,
        matched_column: Optional[str],
        filter_value: Optional[str],
        columns: List[str],
        probed_entity: Optional[str] = None,
        probed_entity_col: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], str, bool]:
        try:
            with driver.session() as session:
                result = session.run(cypher, **params)
                records = [dict(r) for r in result]
        except Exception as e:
            logger.error(f"Neo4j query failed: {e}")
            return [], UNKNOWN_ANSWER, False

        if not records:
            if probed_entity:
                return [], f"No matching record for '{probed_entity}' was found in the uploaded dataset.", False
            return [], UNKNOWN_ANSWER, False

        answer = self._format_answer(records, intent, matched_column, filter_value, columns, probed_entity, probed_entity_col)
        return records, answer, True

    def _format_answer(
        self,
        records: List[Dict[str, Any]],
        intent: str,
        matched_column: Optional[str],
        filter_value: Optional[str],
        columns: List[str],
        probed_entity: Optional[str] = None,
        probed_entity_col: Optional[str] = None,
    ) -> str:
        col = matched_column or (columns[0] if columns else "value")

        if intent in ("count_distinct", "count_all"):
            total = records[0].get("total", 0)
            if matched_column and intent == "count_distinct":
                return f"There are **{total}** distinct **{matched_column}** values in the dataset."
            return f"There are **{total}** records in the dataset."

        if intent == "average":
            val = records[0].get("result")
            if val is None:
                return UNKNOWN_ANSWER
            return f"The average **{col}** is **{float(val):,.2f}**."

        if intent == "sum":
            val = records[0].get("result")
            if val is None:
                return UNKNOWN_ANSWER
            return f"The total **{col}** is **{float(val):,.2f}**."

        if intent == "maximum":
            val = records[0].get("result")
            if val is None:
                return UNKNOWN_ANSWER
            return f"The highest **{col}** is **{float(val):,.2f}**."

        if intent == "minimum":
            val = records[0].get("result")
            if val is None:
                return UNKNOWN_ANSWER
            return f"The lowest **{col}** is **{float(val):,.2f}**."

        if intent == "list_distinct":
            vals = self._extract_col_vals(records, col)
            if not vals:
                return UNKNOWN_ANSWER
            if len(vals) <= 15:
                return f"The distinct **{col}** values are: {', '.join(vals)}."
            return (
                f"Found **{len(vals)}** distinct **{col}** values. "
                f"First 15: {', '.join(vals[:15])}…"
            )

        if intent == "lookup" or intent == "filter":
            if intent == "lookup" and matched_column and len(records) == 1:
                val = list(records[0].values())[0]
                return f"The {matched_column} for {probed_entity or 'that record'} is **{val}**."

            name_col = self._pick_name_col(columns, records)
            names = [str(r.get(name_col, "")) for r in records if r.get(name_col)]
            
            if names:
                if (filter_value and matched_column) or (probed_entity and probed_entity_col):
                    listed = self._oxford_list(names[:20])
                    suffix = f" and {len(names) - 20} more" if len(names) > 20 else ""
                    filter_display = probed_entity or filter_value
                    col_display = probed_entity_col or matched_column
                    return f"{listed}{suffix} — **{col_display}**: {filter_display}."
                return f"Found **{len(records)}** record(s): {', '.join(names[:20])}."
            
            row = records[0]
            summary = ", ".join(f"{k}: {v}" for k, v in list(row.items())[:5])
            return f"Found **{len(records)}** record(s). Example — {summary}."

        if intent == "list_all":
            if matched_column:
                vals = self._extract_col_vals(records, matched_column)
                if not vals:
                    return UNKNOWN_ANSWER
                if len(vals) <= 20:
                    return f"The distinct **{matched_column}** values are: {', '.join(vals)}."
                return (
                    f"Found **{len(vals)}** distinct **{matched_column}** values. "
                    f"First 20: {', '.join(vals[:20])}…"
                )
            name_col = self._pick_name_col(columns, records)
            names = [str(r.get(name_col, "")) for r in records if r.get(name_col)]
            if names:
                if len(names) <= 20:
                    return f"Found **{len(records)}** record(s): {', '.join(names)}."
                return (
                    f"Found **{len(records)}** record(s). "
                    f"First 20: {', '.join(names[:20])}…"
                )
            row = records[0]
            summary = ", ".join(f"{k}: {v}" for k, v in list(row.items())[:5])
            return f"Found **{len(records)}** record(s). Example — {summary}."

        return f"Found **{len(records)}** result(s)."

    @staticmethod
    def _extract_col_vals(records: List[Dict[str, Any]], col: str) -> List[str]:
        vals: List[str] = []
        for r in records:
            v = r.get(col) or r.get(f"`{col}`")
            if v is not None and str(v).strip():
                vals.append(str(v))
        return vals

    @staticmethod
    def _pick_name_col(columns: List[str], records: List[Dict[str, Any]]) -> Optional[str]:
        name_hints = [
            "name", "employee", "person", "staff", "user", "member",
            "title", "label", "first", "last", "full", "id", "product",
        ]
        for hint in name_hints:
            for col in columns:
                if hint in col.lower():
                    return col
        return columns[0] if columns else None

    @staticmethod
    def _oxford_list(items: List[str]) -> str:
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + f", and {items[-1]}"


# ---------------------------------------------------------------------------
# Schema helpers (also used by main.py endpoints)
# ---------------------------------------------------------------------------

def get_dataset_columns(driver: Driver, dataset_name: Optional[str] = None) -> List[str]:
    """Return property keys from Row nodes, scoped to a dataset if given."""
    excluded = {"id", "elementId", "labels"}
    try:
        with driver.session() as session:
            if dataset_name:
                result = session.run(
                    "MATCH (d:Dataset {name: $ds})-[:HAS_ROW]->(r:Row) "
                    "RETURN keys(r) AS cols LIMIT 1",
                    ds=dataset_name,
                )
            else:
                result = session.run("MATCH (r:Row) RETURN keys(r) AS cols LIMIT 1")
            record = result.single()
            if record:
                return [c for c in record["cols"] if c not in excluded]
    except Exception as e:
        logger.error(f"Column discovery failed: {e}")
    return []


def get_all_datasets(driver: Driver) -> List[str]:
    """Return names of all Dataset nodes."""
    try:
        with driver.session() as session:
            result = session.run("MATCH (d:Dataset) RETURN d.name AS name ORDER BY d.name")
            return [r["name"] for r in result]
    except Exception as e:
        logger.error(f"Dataset discovery failed: {e}")
        return []


def get_dataset_row_count(driver: Driver, dataset_name: str) -> int:
    """Return the number of Row nodes for a specific dataset."""
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (d:Dataset {name: $ds})-[:HAS_ROW]->(r:Row) RETURN count(r) AS total",
                ds=dataset_name,
            )
            record = result.single()
            return record["total"] if record else 0
    except Exception as e:
        logger.error(f"Row count failed for {dataset_name}: {e}")
        return 0


def compute_column_stat(
    driver: Driver,
    dataset_name: str,
    col: str,
    numeric: bool,
) -> Dict[str, Any]:
    """
    Compute statistical summary for one column of a dataset.
    Returns a dict compatible with ColumnStat.
    """
    stat: Dict[str, Any] = {
        "name": col,
        "col_type": "numeric" if numeric else "categorical",
        "distinct_count": 0,
        "top_values": [],
        "min_val": None,
        "max_val": None,
        "avg_val": None,
        "sum_val": None,
    }
    try:
        with driver.session() as session:
            # Distinct count
            res = session.run(
                "MATCH (d:Dataset {name: $ds})-[:HAS_ROW]->(r:Row) "
                f"RETURN COUNT(DISTINCT r.`{col}`) AS dc",
                ds=dataset_name,
            )
            rec = res.single()
            if rec:
                stat["distinct_count"] = rec["dc"] or 0

            if numeric:
                res2 = session.run(
                    "MATCH (d:Dataset {name: $ds})-[:HAS_ROW]->(r:Row) "
                    f"WHERE r.`{col}` IS NOT NULL "
                    f"RETURN MIN(toFloat(r.`{col}`)) AS mn, "
                    f"MAX(toFloat(r.`{col}`)) AS mx, "
                    f"AVG(toFloat(r.`{col}`)) AS av, "
                    f"SUM(toFloat(r.`{col}`)) AS sm",
                    ds=dataset_name,
                )
                rec2 = res2.single()
                if rec2:
                    def _f(v):
                        try:
                            return round(float(v), 2) if v is not None else None
                        except (TypeError, ValueError):
                            return None
                    stat["min_val"] = _f(rec2["mn"])
                    stat["max_val"] = _f(rec2["mx"])
                    stat["avg_val"] = _f(rec2["av"])
                    stat["sum_val"] = _f(rec2["sm"])
            else:
                res3 = session.run(
                    "MATCH (d:Dataset {name: $ds})-[:HAS_ROW]->(r:Row) "
                    f"WHERE r.`{col}` IS NOT NULL AND r.`{col}` <> '' "
                    f"RETURN r.`{col}` AS value, COUNT(r) AS cnt "
                    f"ORDER BY cnt DESC LIMIT 10",
                    ds=dataset_name,
                )
                stat["top_values"] = [
                    {"value": str(r["value"]), "count": r["cnt"]}
                    for r in res3
                ]
    except Exception as e:
        logger.error(f"Column stat failed for {col}: {e}")
    return stat


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def answer_question(
    driver: Driver,
    question: str,
    dataset_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full pipeline: question → schema (scoped) → column match → intent → cypher → neo4j → answer.
    dataset_name scopes all queries to the specified Dataset node.
    """
    empty = {
        "question": question,
        "cypher": None,
        "results": None,
        "answer": UNKNOWN_ANSWER,
        "grounded": False,
        "dataset_used": dataset_name,
    }

    if not question or not question.strip():
        return empty

    # 1 ── Schema discovery (scoped) ───────────────────────────────────────────
    columns = get_dataset_columns(driver, dataset_name)
    if not columns:
        msg = (
            f"No data found for dataset '{dataset_name}'."
            if dataset_name
            else "No dataset has been loaded yet. Please upload a CSV file first."
        )
        return {**empty, "answer": msg}

    # 2 ── Column matching ─────────────────────────────────────────────────────
    matched_column = find_column_in_question(question, columns)
    logger.info(f"[{dataset_name}] Column match → '{matched_column}' | Q: '{question}'")

    # 2.5 ── Entity Probing ───────────────────────────────────────────────────
    probed_entity = None
    probed_entity_col = None
    candidates = extract_candidate_entities(question, columns, matched_column)
    for cand in candidates:
        if cand.lower() in [c.lower() for c in columns]:
            continue
        found_col = probe_entity_column(driver, dataset_name, cand)
        if found_col:
            probed_entity = cand
            probed_entity_col = found_col
            logger.info(f"[{dataset_name}] Entity match → '{probed_entity}' found in '{probed_entity_col}'")
            break

    # 3 ── Intent ─────────────────────────────────────────────────────────────
    intent = classify_intent(question)
    
    # Auto-fallback intent if an entity is found but intent remains unknown or is just list_all
    if intent in ("unknown", "list_all") and probed_entity:
        intent = "filter"
    elif intent == "count_distinct" and probed_entity:
        intent = "count_all"
        
    logger.info(f"[{dataset_name}] Intent → '{intent}'")

    # 4 ── Column-required guard ───────────────────────────────────────────────
    if intent in _COLUMN_REQUIRED and matched_column is None:
        col_list = ", ".join(columns)
        q_words = re.findall(r"\b[a-zA-Z]{3,}\b", question.lower())
        skip = {
            "how", "many", "what", "are", "the", "all", "list", "show",
            "find", "give", "tell", "count", "total", "average", "mean",
            "sum", "max", "min", "distinct", "unique", "number", "much",
        }
        candidates = [w for w in q_words if w not in skip]
        asked = candidates[0] if candidates else "that column"
        return {
            **empty,
            "answer": (
                f"I couldn't find a column matching **'{asked}'**. "
                f"Available columns are: {col_list}."
            ),
        }

    # 5 ── Filter value ────────────────────────────────────────────────────────
    filter_value = extract_filter_value(question, columns)

    # 6 ── Generate Cypher ─────────────────────────────────────────────────────
    generator = CypherGenerator()
    cypher, params = generator.generate(
        intent=intent,
        columns=columns,
        matched_column=matched_column,
        filter_value=filter_value,
        dataset_name=dataset_name,
        probed_entity=probed_entity,
        probed_entity_col=probed_entity_col,
    )

    if cypher is None or intent == "unknown":
        return empty

    logger.info(f"[{dataset_name}] Cypher → {cypher} | params: {params}")

    # 7 ── Execute ─────────────────────────────────────────────────────────────
    executor = QueryExecutor()
    results, answer, grounded = executor.execute(
        driver=driver,
        cypher=cypher,
        params=params,
        intent=intent,
        matched_column=matched_column,
        filter_value=filter_value,
        columns=columns,
        probed_entity=probed_entity,
        probed_entity_col=probed_entity_col,
    )

    return {
        "question": question,
        "cypher": cypher,
        "results": results,
        "answer": answer,
        "grounded": grounded,
        "dataset_used": dataset_name,
    }
