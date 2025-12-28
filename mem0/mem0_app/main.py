import os
import time
import socket
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from mem0 import Memory

# ==============================================================================
# 1. INITIALIZATION CODE FROM YOUR SCRIPT
# ==============================================================================

def wait_for_qdrant(host, port, max_retries=60):
    print(f"Waiting for Qdrant at {host}:{port}...")
    for i in range(max_retries):
        try:
            with socket.create_connection((host, port), timeout=2):
                print("✓ Qdrant is ready!")
                time.sleep(5)
                return True
        except (socket.timeout, ConnectionRefusedError):
            if i % 5 == 0:
                print(f"Still waiting... ({i+1}/{max_retries})")
            time.sleep(2)
    raise Exception("Qdrant did not become ready in time")

print("=" * 60)
print("Starting Mem0 Application with Qdrant API")
print("=" * 60)

# Initialize Flask App
app = Flask(__name__)

# Initialize Memory object as a global variable
memory = None

try:
    # Get Qdrant connection details
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
    
    # Get DeepSeek API key from environment
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_api_key:
        print("WARNING: DEEPSEEK_API_KEY environment variable not set")
    
    # Wait for Qdrant to be available
    wait_for_qdrant(qdrant_host, qdrant_port)
    
    # Your exact configuration for mem0 with DeepSeek
    config = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "mem0_memories",
                "host": qdrant_host,
                "port": qdrant_port,
            }
        },
        "llm": {
            "provider": "deepseek",
            "config": {
                "model": "deepseek-chat",
                "api_key": deepseek_api_key,
                "deepseek_base_url": "https://api.deepseek.com/v1",
                "temperature": 0.1,
            }
        },
        "embedder": {
            "provider": "openai",  # DeepSeek also provides embeddings
            "config": {
                "model": "text-embedding-3-small",  # You can keep using OpenAI embeddings
                # OR use DeepSeek embeddings if available:
                # "model": "deepseek-embedding",
                # "api_key": deepseek_api_key,
                # "base_url": "https://api.deepseek.com/v1",
            }
        }
    }
    
    print("\nInitializing Memory with Qdrant backend and DeepSeek LLM...")
    memory = Memory.from_config(config)
    print("✓ Memory initialized successfully!")
    
except Exception as e:
    print(f"FATAL ERROR during initialization: {e}")
    # If initialization fails, we keep 'memory' as None

# ==============================================================================
# 2. API ENDPOINTS TO EXPOSE MEM0 FUNCTIONALITY
# ==============================================================================

@app.route('/add', methods=['POST'])
def add_memory():
    if not memory:
        return jsonify({"status": "error", "message": "Memory not initialized"}), 500
        
    payload = request.get_json()
    if not payload or 'data' not in payload or 'user_id' not in payload:
        return jsonify({"status": "error", "message": "Missing 'data' or 'user_id' in request"}), 400

    try:
        # mem0 v0.2.2+ uses a single message string. The 'role' is handled internally.
        memory.add(
            payload['data'], 
            user_id=payload['user_id'],
            metadata={"category": payload.get("category", "general")}
        )
        return jsonify({"status": "success", "message": "Memory added"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/search', methods=['POST'])
def search_memories():
    if not memory:
        return jsonify({
            "status": "error",
            "message": "Memory not initialized"
        }), 500

    payload = request.get_json(silent=True)
    if not payload or 'query' not in payload or 'user_id' not in payload:
        return jsonify({
            "status": "error",
            "message": "Missing 'query' or 'user_id' in request"
        }), 400

    query = payload['query']
    user_id = payload['user_id']
    category = payload.get("category")

    try:
        # --------------------------------------------------
        # 1. Broad recall (playground behavior)
        # --------------------------------------------------
        raw_response = memory.search(
            query=query,
            user_id=user_id,
            limit=20,        # wide net
            threshold=0.55   # 0.55–0.6 for exploratory recall, keep 0.7 only for rules / constraints
        )

        # --------------------------------------------------
        # 2. Normalize Mem0 response shape
        # --------------------------------------------------
        if isinstance(raw_response, dict):
            candidates = raw_response.get("results", [])
        elif isinstance(raw_response, list):
            candidates = raw_response
        else:
            candidates = []

        # --------------------------------------------------
        # 3. Soft category preference (NOT hard filter)
        # --------------------------------------------------
        if category and candidates:
            preferred = [
                m for m in candidates
                if m.get("metadata", {}).get("category") == category
            ]
            if preferred:
                candidates = preferred

        # --------------------------------------------------
        # 4. Final trim
        # --------------------------------------------------
        results = candidates[:5]

        return jsonify({
            "status": "success",
            "results": results
        }), 200

    except Exception as e:
        # Log full traceback inside container
        app.logger.exception("Mem0 search failed")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/delete_old', methods=['POST'])
def delete_old_memories():
    if not memory:
        return jsonify({"status": "error", "message": "Memory not initialized"}), 500

    payload = request.get_json()
    if not payload or 'user_id' not in payload:
        return jsonify({"status": "error", "message": "Missing 'user_id' in request"}), 400

    user_id = payload['user_id']
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
    deleted_count = 0
    errors = []

    try:
        # Get the dictionary containing all memories for the user.
        get_all_response = memory.get_all(user_id=user_id)
        
        # THE FIX IS HERE: Extract the list from the dictionary.
        user_memories = get_all_response.get('results', [])
        
        for mem in user_memories:
            created_at_str = mem.get('created_at')
            if not created_at_str:
                continue

            memory_date = datetime.fromisoformat(created_at_str)
            if memory_date < cutoff_date:
                try:
                    memory.delete(memory_id=mem['id'])
                    deleted_count += 1
                except Exception as e:
                    errors.append(f"Could not delete memory {mem['id']}: {str(e)}")
        
        if errors:
            return jsonify({"status": "partial_success", "deleted_count": deleted_count, "errors": errors}), 207
        
        return jsonify({"status": "success", "deleted_count": deleted_count}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================================================================
# 3. RUN THE FLASK APP
# ==============================================================================

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("✓ Starting Flask API server for Mem0...")
    print("=" * 60)
    # Listens on 0.0.0.0 to be accessible from other Docker containers
    app.run(host='0.0.0.0', port=8000)