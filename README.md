# RAALE - End-to-End CSV Graph Ingestion Pipeline

A production-grade, containerized CSV ingestion pipeline built for high engineering quality. This project parses uploaded CSV files, streams rows individually into a Kafka broker, and processes them asynchronously using a Loader daemon to write structured dataset and row nodes into a Neo4j Graph Database.

## Architecture Flow

```
   [User Uploads CSV]
           │
           ▼
     [Next.js 15 UI]
           │ (POST /ingest)
           ▼
   [FastAPI Ingest API]
           │ (Checks SQLite duplicate, parses CSV)
           ▼
     [Apache Kafka] (Topic: `csv_rows`)
           │
           ▼
    [Python Loader] (Subscribed to consumer)
           │
           ▼
     [Neo4j Database] (Graph: Dataset -> HAS_ROW -> Row)
```

## Tech Stack
- **Frontend**: Next.js 15, TypeScript, React, TailwindCSS.
- **Backend**: Python 3.11, FastAPI, Pydantic v2, confluent-kafka, neo4j driver.
- **Messaging**: Apache Kafka (KRaft mode, no Zookeeper required).
- **Database**: Neo4j Community v5.19.0.
- **Orchestration**: Docker & Docker Compose.

## Project Structure
```
frontend/                 # Next.js frontend code
backend/
    api/                  # FastAPI web server
    loader/               # Kafka consumer & Neo4j inserter
    common/               # Shared logic, schemas, and logging
docker/                   # Infrastructure configurations
uploads/                  # Saved CSV storage and SQLite metadata database
docker-compose.yml        # Multi-service container orchestration
README.md                 # Project guide
```

## Setup & Running

To run the entire pipeline end-to-end, execute the following command in the root folder:

```bash
docker compose up --build
```

This will automatically format the Kafka storage, spin up the Neo4j instance, launch the FastAPI server, run the loader daemon, and build/start the Next.js frontend.

### Service Ports
- **Frontend UI**: `http://localhost:3000`
- **FastAPI API**: `http://localhost:8000`
- **Neo4j Browser**: `http://localhost:7474` (Auth: `neo4j` / `password123`)

---

## Verification & Testing

### 1. Verification of Active Endpoints
Ensure that the API is up and has established connection to Kafka:
```bash
curl http://localhost:8000/health
```
Response:
```json
{"status": "healthy", "services": {"api": "healthy", "kafka": "healthy"}}
```

### 2. Stream a Sample CSV
Submit a file to the `/ingest` API (you can use `employees.csv` in the root):
```bash
curl -F "file=@employees.csv" http://localhost:8000/ingest
```
Response:
```json
{"status": "accepted", "rows": 250}
```

### 3. Check Neo4j Graph
Log into the Neo4j Browser at `http://localhost:7474` (Neo4j user: `neo4j`, password: `password123`) and run:
```cypher
MATCH (d:Dataset)-[r:HAS_ROW]->(row:Row) RETURN d, r, row LIMIT 50
```
This query displays the parent `Dataset` node linked to each ingested `Row` node containing the columns as properties.
