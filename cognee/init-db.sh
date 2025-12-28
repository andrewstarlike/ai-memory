#!/bin/bash
set -e

echo "Initializing PostgreSQL database with pgvector..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create vector extension
    CREATE EXTENSION IF NOT EXISTS vector;
    
    -- Optional: Create pg_stat_statements for monitoring
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
    
    -- Drop existing tables if needed (uncomment if you want a fresh start)
    -- DROP TABLE IF EXISTS documents CASCADE;
    -- DROP TABLE IF EXISTS nodes CASCADE;
    -- DROP TABLE IF EXISTS edges CASCADE;
    
    -- Create documents table (for vector search)
    CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        content TEXT,
        embedding vector(1536),
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Create nodes table (for knowledge graph)
    CREATE TABLE IF NOT EXISTS nodes (
        id VARCHAR(255) PRIMARY KEY,
        node_type VARCHAR(100),
        data JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Create edges table (for knowledge graph relationships)
    CREATE TABLE IF NOT EXISTS edges (
        id SERIAL PRIMARY KEY,
        from_node VARCHAR(255) REFERENCES nodes(id) ON DELETE CASCADE,
        to_node VARCHAR(255) REFERENCES nodes(id) ON DELETE CASCADE,
        relationship VARCHAR(100),
        data JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(from_node, to_node, relationship)
    );
    
    -- Create indexes
    CREATE INDEX IF NOT EXISTS idx_documents_embedding 
    ON documents USING ivfflat (embedding vector_cosine_ops);
    
    CREATE INDEX IF NOT EXISTS idx_nodes_type 
    ON nodes(node_type);
    
    CREATE INDEX IF NOT EXISTS idx_edges_from 
    ON edges(from_node);
    
    CREATE INDEX IF NOT EXISTS idx_edges_to 
    ON edges(to_node);
    
    CREATE INDEX IF NOT EXISTS idx_edges_relationship 
    ON edges(relationship);
    
    -- Create vector index for better performance
    CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw 
    ON documents USING hnsw (embedding vector_cosine_ops);
    
    -- Grant permissions
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO cognee;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO cognee;
    
    -- Update statistics
    ANALYZE;
EOSQL

echo "Database initialized successfully!"
echo "- Created vector extension"
echo "- Created documents table for vector search"
echo "- Created nodes and edges tables for knowledge graph"
echo "- Created all necessary indexes"