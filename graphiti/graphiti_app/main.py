import os
import time
import logging
import asyncio
from datetime import datetime
from quart import Quart, request, jsonify
from neo4j import GraphDatabase, AsyncGraphDatabase  # Import Async driver

# --- IMPORTS ---
from graphiti_core import Graphiti
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.llm_client import LLMConfig
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.nodes import EpisodeType

# ==============================================================================
# 1. CONFIGURATION & GLOBALS
# ==============================================================================

app = Quart(__name__)
logging.basicConfig(level=logging.INFO)
logger = app.logger

# Environment Variables
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# Global Objects
graphiti = None
async_driver = None  # Global async driver for manual queries

# ==============================================================================
# 2. STARTUP HELPERS (SYNCHRONOUS)
# ==============================================================================

def wait_for_neo4j(max_retries=60):
    """Waits for Neo4j to be ready using a temporary sync driver."""
    print(f"Waiting for Neo4j at {NEO4J_URI}...")
    for i in range(max_retries):
        try:
            temp_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            temp_driver.verify_connectivity()
            temp_driver.close()
            print("✓ Neo4j is ready!")
            return True
        except Exception as e:
            if i % 5 == 0:
                print(f"Still waiting for Neo4j... ({i+1}/{max_retries})")
            time.sleep(2)
    raise Exception("Neo4j did not become ready in time")

def create_fulltext_index_manually():
    """Manually creates indexes using a temporary sync driver."""
    print("Verifying fulltext indexes...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            result = session.run("SHOW INDEXES")
            indexes = [record["name"] for record in result]
            
            if "node_name_and_summary" not in indexes:
                print("  ℹ️ Creating 'node_name_and_summary' index...")
                session.run("""
                    CREATE FULLTEXT INDEX node_name_and_summary IF NOT EXISTS
                    FOR (n:Entity) ON EACH [n.name, n.summary]
                """)
            
            if "edge_name_and_fact" not in indexes:
                print("  ℹ️ Creating 'edge_name_and_fact' index...")
                session.run("""
                    CREATE FULLTEXT INDEX edge_name_and_fact IF NOT EXISTS
                    FOR ()-[r:RELATES_TO]-() ON EACH [r.name, r.fact]
                """)
            print("✓ Indexes verified.")
    except Exception as e:
        print(f"⚠️ Index setup warning: {e}")
    finally:
        driver.close()

def init_graphiti():
    """Initializes the Graphiti library."""
    global graphiti
    print("Initializing Graphiti Core...")
    
    # Graphiti uses its own internal driver logic
    neo4j_driver = Neo4jDriver(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    
    try:
        neo4j_driver.build_indices_and_constraints()
    except Exception as e:
        print(f"⚠️ Graphiti index build warning: {e}")

    llm_config = LLMConfig(
        api_key=OPENAI_KEY, 
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1"
    )
    llm_client = OpenAIGenericClient(config=llm_config)
    
    graphiti = Graphiti(graph_driver=neo4j_driver, llm_client=llm_client)
    print("✓ Graphiti initialized!")

# ==============================================================================
# 3. LIFECYCLE EVENTS
# ==============================================================================

@app.before_serving
async def startup():
    """Runs before the server starts accepting requests."""
    global async_driver
    
    # 1. Run Sync Checks
    wait_for_neo4j()
    create_fulltext_index_manually()
    init_graphiti()
    
    # 2. Initialize Global Async Driver for API Routes
    # This prevents "Connection Reset" errors by reusing the connection pool
    print("🔌 Connecting global Async Driver...")
    async_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    print("✓ Async Driver connected.")

@app.after_serving
async def shutdown():
    """Runs when the server shuts down."""
    global async_driver
    if async_driver:
        print("🔌 Closing Async Driver...")
        await async_driver.close()
        print("✓ Async Driver closed.")

# ==============================================================================
# 4. API ENDPOINTS
# ==============================================================================

@app.route('/health', methods=['GET'])
async def health_check():
    if graphiti and async_driver:
        return jsonify({"status": "healthy", "message": "System ready"}), 200
    return jsonify({"status": "unhealthy", "message": "Initializing..."}), 503

@app.route('/ingest', methods=['POST'])
async def add_data():
    if not graphiti:
        return jsonify({"status": "error", "message": "Graphiti not initialized"}), 500
        
    payload = await request.get_json()
    text_data = payload.get('data')
    category = payload.get('category', 'general') 
    user_id = payload.get('user_id')

    if not text_data or not user_id:
        return jsonify({"status": "error", "message": "Missing 'data' or 'user_id'"}), 400

    try:
        episode_name = f"User_{user_id}_Ingest_{int(time.time())}"
        
        # Create composite group_id for user + category scoping
        composite_group_id = f"{user_id}_{category}"
        
        print(f"📥 Ingesting for User {user_id}, Category: {category} (Group: {composite_group_id})")
        
        # Store with composite group_id for automatic scoping
        await graphiti.add_episode(
            name=episode_name,
            episode_body=text_data,
            source=EpisodeType.text, 
            source_description=f"user:{user_id}|category:{category}",
            reference_time=datetime.now(),
            group_id=composite_group_id  # <-- Composite group_id!
        )
        
        return jsonify({
            "status": "success", 
            "message": f"Ingested for user {user_id}, category {category}",
            "episode_name": episode_name,
            "group_id": composite_group_id
        }), 201
    except Exception as e:
        logger.error(f"Ingest error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/strict_search', methods=['POST'])
async def strict_search():
    """
    Optimized Hybrid Search using Graphiti:
    - Uses composite group_id (user:category) for automatic scoping
    - No need for source_description filtering
    """
    payload = await request.get_json()
    query = payload.get('query')
    category = payload.get('category')
    user_id = payload.get('user_id')

    if not query or not category or not user_id:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        # Create the same composite group_id for searching
        composite_group_id = f"{user_id}_{category}"
        
        # Execute search scoped to the specific user:category namespace
        results = await graphiti.search(
            query,  # Just the original query - no category prepending needed!
            group_ids=[composite_group_id]  # Automatic user+category scoping
        )

        data = []
        
        for r in results:
            # Check if the result is an Edge/Fact
            if hasattr(r, 'fact'):
                data.append({
                    "type": "graph_match",
                    "entity": getattr(r, 'source_node_name', 'Unknown Entity'), 
                    "summary": getattr(r, 'fact', ''),
                    "entity_id": getattr(r, 'source_node_uuid', None),
                    "category": category,
                    "user_id": user_id,
                    "facts": [{
                        "fact": r.fact,
                        "type": getattr(r, 'edge_name', 'related'),
                        "target": getattr(r, 'target_node_name', 'Unknown')
                    }]
                })
            
            # Check if result is an Episode/Chunk
            elif hasattr(r, 'content'):
                data.append({
                    "type": "text_match",
                    "entity": "Source Text",
                    "summary": r.content[:200] + "...",
                    "category": category,
                    "user_id": user_id,
                    "facts": []
                })

        return jsonify({
            "status": "success", 
            "count": len(data), 
            "results": data,
            "scoped_to": composite_group_id
        })

    except Exception as e:
        logger.error(f"Graphiti Search error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/delete_old', methods=['POST'])
async def delete_old_data():
    payload = await request.get_json()
    user_id = payload.get('user_id')
    
    if not user_id:
        return jsonify({"status": "error", "message": "Missing 'user_id'"}), 400

    days_to_keep = 90
    cutoff_time = int(time.time()) - (days_to_keep * 24 * 60 * 60)
    user_prefix = f"User_{user_id}_Ingest_"
    
    print(f"🧹 Cleanup for User {user_id} older than {datetime.fromtimestamp(cutoff_time)}")

    try:
        async with async_driver.session() as session:
            # Delete old episodes
            del_query = """
            MATCH (e:Episodic)
            WHERE e.name STARTS WITH $user_prefix
            AND toInteger(split(e.name, '_')[3]) < $cutoff
            DETACH DELETE e
            RETURN count(e) as deleted_count
            """
            result = await session.run(del_query, user_prefix=user_prefix, cutoff=cutoff_time)
            record = await result.single()
            deleted_episodes = record["deleted_count"]

            # Cleanup orphans
            orphan_query = """
            MATCH (n) WHERE NOT (n)--() DELETE n RETURN count(n) as deleted_nodes
            """
            result_orphan = await session.run(orphan_query)
            record_orphan = await result_orphan.single()
            deleted_nodes = record_orphan["deleted_nodes"]
        
        return jsonify({
            "status": "success", 
            "message": f"Removed {deleted_episodes} episodes and {deleted_nodes} orphaned nodes."
        }), 200
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("✓ Starting Quart API server...")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8001)