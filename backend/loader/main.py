import json
import os
import time
import signal
from confluent_kafka import Consumer
from neo4j import GraphDatabase

from backend.common.logging_config import get_logger

# Initialize logging
logger = get_logger("loader_service")

# Configurations
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "csv_rows")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "neo4j-loader-group")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

running = True
row_counter = 0

def handle_signal(signum, frame):
    global running
    logger.info("Shutdown signal received. Gracefully closing consumers and connections...")
    running = False

# Register signal handlers for clean container shutdown
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def connect_neo4j(max_retries=20, delay=3) -> GraphDatabase:
    retries = 0
    while retries < max_retries:
        try:
            logger.info(f"Connecting to Neo4j at {NEO4J_URI} (attempt {retries+1}/{max_retries})...")
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            # Test connection
            driver.verify_connectivity()
            logger.info("Successfully connected to Neo4j!")
            return driver
        except Exception as e:
            retries += 1
            logger.warn(f"Neo4j connection failed: {e}. Retrying in {delay} seconds...")
            time.sleep(delay)
    raise RuntimeError("Failed to connect to Neo4j after maximum retries.")

def connect_kafka_consumer(max_retries=20, delay=3) -> Consumer:
    retries = 0
    while retries < max_retries:
        try:
            logger.info(f"Connecting Kafka consumer to {KAFKA_BOOTSTRAP_SERVERS} (attempt {retries+1}/{max_retries})...")
            conf = {
                'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
                'group.id': KAFKA_GROUP_ID,
                'auto.offset.reset': 'earliest',
                'enable.auto.commit': False,  # Manual commits for at-least-once delivery
                'session.timeout.ms': 6000,
                'heartbeat.interval.ms': 2000,
            }
            consumer = Consumer(conf)
            # Test connection by requesting metadata
            consumer.list_topics(timeout=2.0)
            logger.info("Successfully connected to Kafka!")
            return consumer
        except Exception as e:
            retries += 1
            logger.warn(f"Kafka consumer connection failed: {e}. Retrying in {delay} seconds...")
            time.sleep(delay)
    raise RuntimeError("Failed to connect to Kafka after maximum retries.")

def setup_constraints(driver):
    """
    Creates uniqueness constraints in Neo4j to prevent duplicate Dataset nodes.
    """
    query = """
    CREATE CONSTRAINT dataset_name_unique IF NOT EXISTS
    FOR (d:Dataset) REQUIRE d.name IS UNIQUE
    """
    try:
        with driver.session() as session:
            session.run(query)
        logger.info("Ensured unique constraint on Dataset(name)")
    except Exception as e:
        logger.error(f"Failed to create Neo4j constraints: {e}")
        raise e

def insert_row_to_neo4j(driver, dataset_name: str, row: dict):
    """
    Executes a Cypher query to:
    1. Merge the parent Dataset node
    2. Create a Row node with all row columns as properties
    3. Link them via a HAS_ROW relationship
    """
    query = """
    MERGE (d:Dataset {name: $dataset_name})
    ON CREATE SET d.uploaded_at = datetime()
    CREATE (r:Row)
    SET r = $row
    CREATE (d)-[:HAS_ROW]->(r)
    """
    with driver.session() as session:
        session.run(query, dataset_name=dataset_name, row=row)

def main():
    global row_counter
    logger.info("Starting CSV Neo4j Loader service...")
    
    # 1. Establish connections
    try:
        driver = connect_neo4j()
        setup_constraints(driver)
        consumer = connect_kafka_consumer()
    except Exception as e:
        logger.critical(f"Initialization failed: {e}")
        return

    # 2. Subscribe to topic
    try:
        consumer.subscribe([KAFKA_TOPIC])
        logger.info(f"Subscribed to Kafka topic '{KAFKA_TOPIC}'. Starting polling loop...")
        
        while running:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"Kafka consumer error: {msg.error()}")
                continue
                
            # Parse message value
            try:
                message_str = msg.value().decode('utf-8')
                message_json = json.loads(message_str)
                
                dataset_name = message_json.get("dataset")
                row = message_json.get("row")
                
                if not dataset_name or not row:
                    logger.warn(f"Malformed message received (missing dataset or row): {message_str}")
                    # Commit malformed message to skip it
                    consumer.commit(message=msg, asynchronous=False)
                    continue
                
                row_counter += 1
                logger.info(f"Consumed row {row_counter}")
                
                # Write to Neo4j
                insert_row_to_neo4j(driver, dataset_name, row)
                logger.info(f"Inserted row {row_counter}")
                
                # Commit offset manually after successful write
                consumer.commit(message=msg, asynchronous=False)
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode message JSON: {e}")
                consumer.commit(message=msg, asynchronous=False)
            except Exception as e:
                logger.error(f"Failed to process and insert row to Neo4j: {e}")
                # Sleep briefly to avoid tight loops on persistent errors (e.g. database disconnect)
                time.sleep(1)
                
    except Exception as e:
        logger.critical(f"Loader service crashed: {e}")
    finally:
        # 3. Clean up resources
        logger.info("Closing Kafka consumer...")
        try:
            consumer.close()
        except:
            pass
        logger.info("Closing Neo4j driver...")
        try:
            driver.close()
        except:
            pass
        logger.info("Loader service stopped.")

if __name__ == "__main__":
    main()
