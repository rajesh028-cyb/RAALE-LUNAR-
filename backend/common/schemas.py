from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class KafkaMessage(BaseModel):
    """Single CSV row published to Kafka."""
    dataset: str = Field(..., description="Dataset name (filename without extension)")
    row: Dict[str, Any] = Field(..., description="CSV row as key-value pairs")


class IngestResponse(BaseModel):
    """Successful CSV ingestion response."""
    status: str = Field("accepted")
    rows: int = Field(..., description="Parsed rows sent to Kafka")


class ChatRequest(BaseModel):
    """Chat question with optional dataset scope."""
    question: str = Field(..., description="Natural language question", min_length=1)
    dataset_name: Optional[str] = Field(
        None, description="Dataset to query; omit to use the active dataset"
    )


class ChatResponse(BaseModel):
    """Grounded chat answer."""
    question: str
    cypher: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    answer: str
    grounded: bool
    dataset_used: Optional[str] = Field(None, description="Dataset the answer was drawn from")


class StatusResponse(BaseModel):
    """Live system diagnostics."""
    datasets: int
    rows_loaded: int
    rows_failed: int
    neo4j_connected: bool
    kafka_connected: bool


# ── Dataset management models ─────────────────────────────────────────────────

class DatasetInfo(BaseModel):
    """Metadata for a single uploaded dataset."""
    name: str = Field(..., description="Dataset identifier (filename without .csv)")
    filename: str = Field(..., description="Original uploaded filename")
    uploaded_at: str = Field(..., description="ISO upload timestamp")
    row_count: int = Field(..., description="Rows loaded into Neo4j")
    columns: List[str] = Field(default_factory=list, description="All column names")
    numeric_columns: List[str] = Field(default_factory=list, description="Numeric column names")
    is_active: bool = Field(False, description="True if this is the currently active dataset")


class ColumnStat(BaseModel):
    """Statistical summary for a single column."""
    name: str
    col_type: str = Field(..., description="'numeric' or 'categorical'")
    distinct_count: int = 0
    top_values: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="[{value, count}] for categorical columns, top 10"
    )
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    avg_val: Optional[float] = None
    sum_val: Optional[float] = None


class DatasetSummary(BaseModel):
    """Full statistical summary of a dataset."""
    name: str
    row_count: int
    column_stats: List[ColumnStat]
