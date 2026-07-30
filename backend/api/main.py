import csv
import hashlib
import os
import sqlite3
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json

from backend.common.logging_config import get_logger
from backend.common.schemas import (
    IngestResponse, KafkaMessage, ChatRequest, ChatResponse,
    StatusResponse, DatasetInfo, DatasetSummary, ColumnStat,
)
from backend.api.chat import (
    answer_question, get_dataset_columns, get_all_datasets,
    get_dataset_row_count, compute_column_stat, is_numeric_column,
)

# Initialize logging
logger = get_logger("api_service")

app = FastAPI(
    title="RAALE Graph Chatbot API",
    description="CSV ingestion + rule-based Neo4j graph chatbot. No external LLM.",
    version="2.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "csv_rows")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")
DB_PATH = os.path.join(UPLOAD_DIR, "metadata.db")

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
producer = None      # Kafka Producer
neo4j_driver = None  # Neo4j Driver


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def init_neo4j_driver():
    global neo4j_driver
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        neo4j_driver = driver
        logger.info(f"Neo4j driver initialized and connected to {NEO4J_URI}")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j driver: {e}")
        neo4j_driver = None


def get_neo4j_driver():
    """Return the live driver, attempting reconnect once if needed."""
    global neo4j_driver
    if neo4j_driver is None:
        init_neo4j_driver()
    return neo4j_driver


def neo4j_ping() -> bool:
    """Return True if Neo4j is reachable right now."""
    driver = get_neo4j_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run("RETURN 1")
        return True
    except Exception as e:
        logger.warning(f"Neo4j ping failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Kafka helpers
# ---------------------------------------------------------------------------

def init_kafka_producer():
    global producer
    try:
        from confluent_kafka import Producer
        conf = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'client.id': 'csv-ingestion-api',
            'retries': 5,
            'retry.backoff.ms': 500,
        }
        producer = Producer(conf)
        logger.info(f"Kafka Producer initialized pointing to {KAFKA_BOOTSTRAP_SERVERS}")
    except Exception as e:
        logger.error(f"Failed to initialize Kafka Producer: {e}")
        producer = None


def kafka_ping() -> bool:
    """Return True if the Kafka broker is reachable right now."""
    if producer is None:
        return False
    try:
        producer.list_topics(timeout=2.0)
        return True
    except Exception as e:
        logger.warning(f"Kafka ping failed: {e}")
        return False


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_hash TEXT NOT NULL UNIQUE,
            dataset_name TEXT NOT NULL UNIQUE,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"Metadata SQLite DB initialized at {DB_PATH}")


def calculate_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_duplicate(file_hash: str, dataset_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM uploads WHERE file_hash = ?", (file_hash,))
    if cursor.fetchone():
        conn.close()
        return "hash_conflict"
    cursor.execute("SELECT filename FROM uploads WHERE dataset_name = ?", (dataset_name,))
    if cursor.fetchone():
        conn.close()
        return "name_conflict"
    conn.close()
    return None


def register_upload(filename: str, file_hash: str, dataset_name: str, row_count: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO uploads (filename, file_hash, dataset_name, row_count) VALUES (?, ?, ?, ?)",
        (filename, file_hash, dataset_name, row_count)
    )
    conn.commit()
    conn.close()
    logger.info(f"Registered upload in metadata DB: {dataset_name} ({row_count} rows)")


def get_upload_stats() -> Dict[str, Any]:
    """Return aggregated upload metadata from SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(row_count) FROM uploads")
        row = cursor.fetchone()
        conn.close()
        dataset_count = row[0] or 0
        total_rows = row[1] or 0
        return {"datasets": dataset_count, "rows_loaded": total_rows}
    except Exception as e:
        logger.error(f"Failed to read upload stats from SQLite: {e}")
        return {"datasets": 0, "rows_loaded": 0}


def get_active_dataset() -> Optional[str]:
    """Read the active dataset name from the settings table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'active_dataset'")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to read active_dataset: {e}")
        return None


def set_active_dataset(name: str) -> None:
    """Persist the active dataset name in the settings table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('active_dataset', ?)",
            (name,)
        )
        conn.commit()
        conn.close()
        logger.info(f"Active dataset set to '{name}'")
    except Exception as e:
        logger.error(f"Failed to set active_dataset: {e}")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup_event():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()
    init_kafka_producer()
    init_neo4j_driver()


# ---------------------------------------------------------------------------
# Delivery report callback
# ---------------------------------------------------------------------------

def delivery_report(err, msg):
    if err is not None:
        logger.error(f"Message delivery failed: {err}")


# ---------------------------------------------------------------------------
# GET /health — real connectivity checks
# ---------------------------------------------------------------------------

@app.get("/health", summary="Liveness check with real service connectivity")
def health_check():
    """
    Verifies connectivity to both Kafka and Neo4j before reporting healthy.
    Returns HTTP 503 if either dependency is unavailable.
    """
    kafka_ok = kafka_ping()
    neo4j_ok = neo4j_ping()

    overall = "healthy" if (kafka_ok and neo4j_ok) else "degraded"
    status_code = 200 if overall == "healthy" else 503

    payload = {
        "status": overall,
        "services": {
            "api":   "healthy",
            "kafka": "healthy" if kafka_ok  else "unavailable",
            "neo4j": "healthy" if neo4j_ok  else "unavailable",
        },
    }

    if status_code == 503:
        from fastapi.responses import JSONResponse
        return JSONResponse(content=payload, status_code=503)

    return payload


# ---------------------------------------------------------------------------
# GET /status — live dataset & row statistics
# ---------------------------------------------------------------------------

@app.get("/status", response_model=StatusResponse, summary="Live system diagnostics")
def get_status():
    """
    Returns real counts from Neo4j (datasets, rows) and live connectivity
    flags for Neo4j and Kafka. rows_failed is derived from SQLite vs Neo4j
    discrepancy when possible.
    """
    stats = get_upload_stats()
    kafka_ok  = kafka_ping()
    neo4j_ok  = neo4j_ping()

    # Count Row nodes actually in Neo4j
    neo4j_rows = 0
    neo4j_datasets = 0
    if neo4j_ok:
        try:
            driver = get_neo4j_driver()
            with driver.session() as session:
                res = session.run("MATCH (r:Row) RETURN count(r) AS total")
                neo4j_rows = res.single()["total"] or 0
                res2 = session.run("MATCH (d:Dataset) RETURN count(d) AS total")
                neo4j_datasets = res2.single()["total"] or 0
        except Exception as e:
            logger.error(f"Status Neo4j count failed: {e}")

    # rows_failed = rows accepted by API but not yet confirmed in Neo4j
    rows_failed = max(0, stats["rows_loaded"] - neo4j_rows)

    return StatusResponse(
        datasets=neo4j_datasets,
        rows_loaded=neo4j_rows,
        rows_failed=rows_failed,
        neo4j_connected=neo4j_ok,
        kafka_connected=kafka_ok,
    )


# ---------------------------------------------------------------------------
# GET /uploads — list all upload records from SQLite
# ---------------------------------------------------------------------------

@app.get("/uploads", summary="List all upload records from metadata DB")
def list_uploads():
    """
    Returns all upload records from the SQLite metadata database,
    ordered by most-recent first. Used by the Report page.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT filename, dataset_name, uploaded_at, row_count "
            "FROM uploads ORDER BY uploaded_at DESC"
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "filename": r[0],
                "dataset_name": r[1],
                "uploaded_at": r[2],
                "row_count": r[3],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Failed to read uploads from SQLite: {e}")
        return []


# ---------------------------------------------------------------------------
# GET /schema — scoped schema for the frontend
# ---------------------------------------------------------------------------

@app.get("/schema", summary="Get column names for a dataset")
def get_schema(dataset: Optional[str] = None):
    """
    Returns column names and numeric-column classification for a dataset.
    If dataset is omitted, uses the active dataset from settings.
    """
    driver = get_neo4j_driver()
    if driver is None:
        return {"columns": [], "datasets": [], "numeric_columns": [], "active_dataset": None}

    ds = dataset or get_active_dataset()
    columns = get_dataset_columns(driver, ds)
    datasets = get_all_datasets(driver)
    numeric_columns = [c for c in columns if is_numeric_column(c)]

    return {
        "columns": columns,
        "datasets": datasets,
        "numeric_columns": numeric_columns,
        "active_dataset": ds,
    }


# ---------------------------------------------------------------------------
# GET /datasets — full dataset list with metadata
# ---------------------------------------------------------------------------

@app.get("/datasets", summary="List all datasets with metadata")
def list_datasets_full():
    """
    Returns every dataset that has been uploaded, enriched with column info
    from Neo4j and an is_active flag.
    """
    driver = get_neo4j_driver()
    active = get_active_dataset()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT filename, dataset_name, uploaded_at, row_count "
            "FROM uploads ORDER BY uploaded_at DESC"
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to read uploads: {e}")
        return []

    result = []
    for r in rows:
        filename, ds_name, uploaded_at, row_count = r
        columns: List[str] = []
        numeric_columns: List[str] = []
        if driver:
            try:
                columns = get_dataset_columns(driver, ds_name)
                numeric_columns = [c for c in columns if is_numeric_column(c)]
            except Exception:
                pass
        result.append(
            DatasetInfo(
                name=ds_name,
                filename=filename,
                uploaded_at=uploaded_at,
                row_count=row_count,
                columns=columns,
                numeric_columns=numeric_columns,
                is_active=(ds_name == active),
            ).model_dump()
        )
    return result


# ---------------------------------------------------------------------------
# GET /datasets/current — active dataset
# ---------------------------------------------------------------------------

@app.get("/datasets/current", summary="Get the currently active dataset")
def get_current_dataset():
    """
    Returns the metadata for the active dataset.
    If no active dataset is set, returns the most recently uploaded one.
    """
    active = get_active_dataset()
    driver = get_neo4j_driver()

    # Fallback: auto-select the most recently uploaded dataset
    if not active:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT dataset_name FROM uploads ORDER BY uploaded_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                active = row[0]
                set_active_dataset(active)
        except Exception:
            pass

    if not active:
        return {"name": None, "columns": [], "numeric_columns": [], "row_count": 0}

    columns: List[str] = []
    numeric_columns: List[str] = []
    row_count = 0
    filename = ""
    uploaded_at = ""

    if driver:
        try:
            columns = get_dataset_columns(driver, active)
            numeric_columns = [c for c in columns if is_numeric_column(c)]
            row_count = get_dataset_row_count(driver, active)
        except Exception:
            pass

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT filename, uploaded_at, row_count FROM uploads WHERE dataset_name = ?",
            (active,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            filename, uploaded_at, row_count = row[0], row[1], row[2]
    except Exception:
        pass

    return DatasetInfo(
        name=active,
        filename=filename,
        uploaded_at=uploaded_at,
        row_count=row_count,
        columns=columns,
        numeric_columns=numeric_columns,
        is_active=True,
    ).model_dump()


# ---------------------------------------------------------------------------
# POST /datasets/{name}/activate — set active dataset
# ---------------------------------------------------------------------------

@app.post("/datasets/{name}/activate", summary="Set the active dataset")
def activate_dataset(name: str):
    """
    Marks the specified dataset as active. Subsequent chat and schema requests
    will be scoped to this dataset unless overridden in the request.
    """
    # Verify the dataset exists in SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM uploads WHERE dataset_name = ?", (name,))
        exists = cursor.fetchone()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{name}' not found. Upload it first."
        )

    set_active_dataset(name)
    return {"status": "activated", "dataset": name}


# ---------------------------------------------------------------------------
# GET /datasets/{name}/summary — column statistics
# ---------------------------------------------------------------------------

@app.get("/datasets/{name}/summary", summary="Column statistics for a dataset")
def dataset_summary(name: str):
    """
    Returns per-column statistical summaries (top values for categoricals,
    min/max/avg/sum for numerics). Used by Dashboard and Report pages.
    Processes up to the first 20 columns to avoid timeouts on wide datasets.
    """
    driver = get_neo4j_driver()
    if driver is None:
        raise HTTPException(status_code=503, detail="Neo4j unavailable")

    columns = get_dataset_columns(driver, name)
    if not columns:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{name}' not found or has no data."
        )

    row_count = get_dataset_row_count(driver, name)
    col_stats = []
    for col in columns[:20]:  # cap at 20 to avoid long-running requests
        numeric = is_numeric_column(col)
        stat = compute_column_stat(driver, name, col, numeric)
        col_stats.append(ColumnStat(**stat).model_dump())

    return DatasetSummary(
        name=name,
        row_count=row_count,
        column_stats=col_stats,
    ).model_dump()


# ---------------------------------------------------------------------------
# POST /chat — rule-based graph chatbot (dataset-scoped)
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse, summary="Ask a question answered from Neo4j")
def chat(request: ChatRequest):
    """
    Accepts a natural language question and an optional dataset_name.
    If dataset_name is omitted, uses the active dataset.
    Generates a parameterized Cypher query scoped to that dataset,
    executes it against Neo4j, and returns a grounded answer.

    No external LLM — all answers come exclusively from graph data.
    """
    logger.info(f"Chat: '{request.question}' | dataset: {request.dataset_name}")

    driver = get_neo4j_driver()
    if driver is None:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is currently unavailable. Please try again shortly."
        )

    # Resolve the dataset to query
    dataset_name = request.dataset_name or get_active_dataset()
    if not dataset_name:
        # Last resort: pick the most recently uploaded
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT dataset_name FROM uploads ORDER BY uploaded_at DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row:
                dataset_name = row[0]
        except Exception:
            pass

    result = answer_question(driver, request.question, dataset_name)

    logger.info(
        f"Chat: grounded={result['grounded']} | dataset={dataset_name} | "
        f"answer='{result['answer'][:80]}'"
    )

    return ChatResponse(
        question=result["question"],
        cypher=result.get("cypher"),
        results=result.get("results"),
        answer=result["answer"],
        grounded=result["grounded"],
        dataset_used=result.get("dataset_used"),
    )


# ---------------------------------------------------------------------------
# POST /ingest — CSV ingestion (UNCHANGED from Milestone 1)
# ---------------------------------------------------------------------------

@app.post("/ingest", response_model=IngestResponse)
async def ingest_csv(file: UploadFile = File(...)):
    logger.info(f"Received file upload request: {file.filename}")

    if not file.filename:
        logger.error("Upload failed: Missing filename")
        raise HTTPException(status_code=400, detail="Filename cannot be empty")

    if not file.filename.endswith(".csv"):
        logger.error(f"Upload failed: File {file.filename} is not a CSV")
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    try:
        content_bytes = await file.read()
    except Exception as e:
        logger.error(f"Failed to read upload file contents: {e}")
        raise HTTPException(status_code=500, detail="Failed to read uploaded file")

    if not content_bytes or len(content_bytes.strip()) == 0:
        logger.error("Upload failed: CSV file is empty")
        raise HTTPException(status_code=400, detail="Uploaded CSV file is empty")

    file_hash = calculate_sha256(content_bytes)
    dataset_name = os.path.splitext(file.filename)[0].lower()

    conflict = check_duplicate(file_hash, dataset_name)
    if conflict == "hash_conflict":
        logger.warning(f"Duplicate upload blocked: Identical CSV hash already processed.")
        raise HTTPException(
            status_code=409,
            detail="Duplicate upload: This file has already been ingested."
        )
    elif conflict == "name_conflict":
        logger.warning(f"Duplicate upload blocked: Dataset name '{dataset_name}' already exists.")
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate upload: Dataset '{dataset_name}' has already been ingested."
        )

    try:
        content_str = content_bytes.decode('utf-8')
    except UnicodeDecodeError as e:
        logger.error(f"Failed to decode file as UTF-8: {e}")
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded text")

    lines = content_str.splitlines()
    if not lines:
        logger.error("Upload failed: Empty CSV text content")
        raise HTTPException(status_code=400, detail="CSV file has no lines")

    reader = csv.DictReader(lines)

    headers = reader.fieldnames
    if not headers or all(h.strip() == "" for h in headers if h):
        logger.error("Upload failed: CSV headers are missing or empty")
        raise HTTPException(status_code=400, detail="CSV file is missing valid headers")

    headers = [h.strip() for h in headers if h]

    rows: List[Dict[str, Any]] = []
    for line_num, row_data in enumerate(reader, start=2):
        if not row_data or all(v is None or v.strip() == "" for v in row_data.values()):
            continue

        cleaned_row = {}
        is_malformed = False

        for k in reader.fieldnames:
            if k is None:
                is_malformed = True
                break
            val = row_data.get(k)
            if val is None:
                is_malformed = True
                break
            cleaned_row[k.strip()] = val.strip()

        if is_malformed:
            logger.error(f"Upload failed: Malformed row on line {line_num}")
            raise HTTPException(
                status_code=400,
                detail=f"Malformed CSV: Row on line {line_num} does not match header columns"
            )

        rows.append(cleaned_row)

    if not rows:
        logger.error("Upload failed: CSV contains no rows of data")
        raise HTTPException(status_code=400, detail="CSV must contain at least one row of data")

    global producer
    if producer is None:
        init_kafka_producer()
        if producer is None:
            logger.error("Ingestion failed: Kafka broker is unavailable")
            raise HTTPException(status_code=503, detail="Kafka messaging queue is currently unavailable")

    logger.info(f"CSV validated. {len(rows)} rows parsed. Publishing to Kafka topic '{KAFKA_TOPIC}'...")

    try:
        for idx, row in enumerate(rows, start=1):
            message = KafkaMessage(dataset=dataset_name, row=row)
            producer.produce(
                KAFKA_TOPIC,
                key=dataset_name,
                value=message.model_dump_json().encode('utf-8'),
                callback=delivery_report
            )
            if idx % 100 == 0:
                producer.poll(0)

        delivered = producer.flush(timeout=5.0)
        if delivered > 0:
            logger.warning(f"{delivered} messages did not receive delivery confirmations in time")

        logger.info(f"Successfully published {len(rows)} messages to Kafka topic '{KAFKA_TOPIC}'")
    except Exception as e:
        logger.error(f"Failed to publish to Kafka: {e}")
        producer = None
        raise HTTPException(status_code=500, detail=f"Failed to stream rows to messaging broker: {str(e)}")

    try:
        saved_file_path = os.path.join(UPLOAD_DIR, f"{dataset_name}_{file_hash[:8]}.csv")
        with open(saved_file_path, "wb") as f:
            f.write(content_bytes)
        logger.info(f"Saved uploaded CSV copy to disk: {saved_file_path}")
    except Exception as e:
        logger.error(f"Failed to save CSV copy to disk: {e}")

    register_upload(file.filename, file_hash, dataset_name, len(rows))
    set_active_dataset(dataset_name)

    return IngestResponse(status="accepted", rows=len(rows))
