import os
import asyncio
import datetime
import logging
from quart import Quart, request, jsonify
import cognee
from datetime import datetime, timedelta, timezone
import uuid
from sqlalchemy import create_engine, text
from cognee.modules.data.methods import delete_data 
import traceback
import asyncpg

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Quart(__name__)

@app.before_serving
async def startup():
    """Initialize Cognee on startup"""
    try:
        print("Initializing Cognee...")
        
        # REMOVED: os.environ settings. 
        # These are now handled by Docker, ensuring Cognee picks them up 
        # immediately upon import.

        # If your version of Cognee requires explicit pruning/creation of tables:
        # await cognee.prune() # Be careful, this deletes data!
        # await cognee.add(...) # Initial setup if needed
        
        print(f"Cognee initialized. DB Provider: {os.getenv('DB_PROVIDER', 'unknown')}")
        
    except Exception as e:
        print(f"Error initializing Cognee: {e}")

@app.route('/health', methods=['GET'])
async def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "services": {
                "postgres": "connected",
                "cognee": "initialized"
            }
        }
        return jsonify(health_status)
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

@app.route('/add', methods=['POST'])
async def add_memory():
    try:
        payload = await request.get_json()
        text_data = payload.get('data')
        category = payload.get('category', 'general')
        user_id = payload.get('user_id')

        if not text_data or not user_id:
            return jsonify({"error": "Both 'data' and 'user_id' are required"}), 400

        logger.info(f"Adding memory for user: {user_id}")

        composite_dataset_name = f"{user_id}_{category}"

        await cognee.add(text_data, dataset_name=composite_dataset_name)
        await cognee.cognify()

        return jsonify({"status": "success"})

    except Exception as e:
        logger.error(f"Error in /add: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['POST'])
async def search_memory():
    try:
        payload = await request.get_json()
        query = payload.get('query')
        category = payload.get('category')
        user_id = payload.get('user_id')

        if not query or not user_id or not category:
            return jsonify({"error": "Query, user_id, and category are required"}), 400

        logger.info(f"Searching for user: {user_id} in category: {category}")

        # Perform semantic search

        logger.info(f"Searching for user: {user_id}")

        composite_dataset_name = f"{user_id}_{category}"

        results = await cognee.search(query, datasets=[composite_dataset_name])

        return jsonify({"results": results})

    except Exception as e:
        logger.error(f"Error in /search: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

async def get_db_connection():
    return await asyncpg.connect(
        user=os.getenv('DB_USERNAME', 'cognee'),
        password=os.getenv('DB_PASSWORD', 'cognee_password'),
        database=os.getenv('DB_NAME', 'cognee_db'),
        # CHANGE: Use the env var DB_HOST, defaulting to 'cognee_db' for Docker
        host=os.getenv('DB_HOST', 'cognee_db'), 
        port=os.getenv('DB_PORT', 5432)
    )

@app.route('/delete', methods=['POST'])
async def delete_old_data():
    conn = None
    try:
        payload = await request.get_json()
        user_id = payload.get('user_id')
        categories = payload.get('categories') # Expecting a list, e.g., ["personal", "work"]
        days = payload.get('days')

        # Input validation
        if not user_id or not categories or days is None:
            return jsonify({"error": "user_id, categories (list), and days (int) are required"}), 400
        
        if not isinstance(categories, list):
            return jsonify({"error": "categories must be a list"}), 400

        # Calculate the cutoff date (UTC)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=int(days))
        
        # Construct composite names
        composite_names = [f"{user_id}_{cat}" for cat in categories]

        conn = await get_db_connection()

        async with conn.transaction():
            # 1. Get IDs of the datasets matching the user_id + categories
            dataset_rows = await conn.fetch(
                'SELECT id, name FROM datasets WHERE name = ANY($1::text[])',
                composite_names
            )
            
            if not dataset_rows:
                return jsonify({"status": "not_found", "message": "No matching datasets found."}), 404

            dataset_ids = [row['id'] for row in dataset_rows]

            # 2. Find IDs of data entries within these datasets that are older than the cutoff
            # We join dataset_data to ensure we only look at data in the target datasets
            old_data_rows = await conn.fetch(
                '''
                SELECT d.id 
                FROM data d
                JOIN dataset_data dd ON d.id = dd.data_id
                WHERE dd.dataset_id = ANY($1::uuid[])
                AND d.updated_at < $2
                ''',
                dataset_ids,
                cutoff_date
            )
            
            old_data_ids = [row['id'] for row in old_data_rows]
            deleted_count = len(old_data_ids)

            if deleted_count > 0:
                # 3. Delete the links in dataset_data
                await conn.execute(
                    'DELETE FROM dataset_data WHERE data_id = ANY($1::uuid[]) AND dataset_id = ANY($2::uuid[])',
                    old_data_ids,
                    dataset_ids
                )

                # 4. Delete the actual data rows
                # Note: This deletes the data record entirely. If this data is shared across 
                # multiple datasets (rare in this schema but possible), you might want to check 
                # if it's orphaned before deleting. Assuming 1:1 or 1:N ownership here:
                await conn.execute(
                    'DELETE FROM data WHERE id = ANY($1::uuid[])',
                    old_data_ids
                )

            # 5. Cleanup: Check for datasets that are now empty (orphaned)
            # We look at the original target dataset_ids and count their remaining items
            empty_dataset_rows = await conn.fetch(
                '''
                SELECT d.id 
                FROM datasets d
                LEFT JOIN dataset_data dd ON d.id = dd.dataset_id
                WHERE d.id = ANY($1::uuid[])
                GROUP BY d.id
                HAVING COUNT(dd.data_id) = 0
                ''',
                dataset_ids
            )
            
            empty_dataset_ids = [row['id'] for row in empty_dataset_rows]
            datasets_removed_count = len(empty_dataset_ids)

            if empty_dataset_ids:
                # Delete dependencies for empty datasets
                await conn.execute('DELETE FROM acls WHERE dataset_id = ANY($1::uuid[])', empty_dataset_ids)
                await conn.execute('DELETE FROM dataset_database WHERE dataset_id = ANY($1::uuid[])', empty_dataset_ids)
                await conn.execute('DELETE FROM pipeline_runs WHERE dataset_id = ANY($1::uuid[])', empty_dataset_ids)
                
                # Delete the empty datasets themselves
                await conn.execute('DELETE FROM datasets WHERE id = ANY($1::uuid[])', empty_dataset_ids)

            return jsonify({
                "status": "success", 
                "message": f"Processed cleanup.",
                "details": {
                    "data_entries_deleted": deleted_count,
                    "empty_datasets_removed": datasets_removed_count,
                    "cutoff_date": cutoff_date.isoformat()
                }
            }), 200

    except Exception as e:
        # logger.error(f"Error in /delete: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            await conn.close()

@app.route('/config', methods=['GET'])
async def get_config():
    """Get current Cognee configuration"""
    config = {
        "llm_model": os.getenv("LLM_MODEL"),
        "vector_store": os.getenv("VECTOR_STORE"),
        "cache_enabled": os.getenv("CACHE_ENABLED"),
        "embedding_model": os.getenv("EMBEDDING_MODEL"),
        "has_postgres": "DATABASE_URL" in os.environ
    }
    return jsonify(config)

if __name__ == '__main__':
    config = Config()
    config.bind = ["0.0.0.0:8002"]
    config.use_reloader = True
    
    asyncio.run(serve(app, config))