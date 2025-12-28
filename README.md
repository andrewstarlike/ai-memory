# ai-memory
Docker Containers And Python APIS For Mem0, Graphiti and Cognee AI Memory Agents

# Mem0 Installation

1. cd ./mem0
2. mkdir -p qdrant_data mem0_data
3. create .env and add DEEPSEEK_API_KEY and OPENAI_API_KEY.
4. docker compose up -d

## Mem0 Endpoints

Add memory:
```
curl -X POST http://localhost:8000/add \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice_uuid",
    "data": "Alice lives in wonderland and loves wolves",
    "category": "personal"
}'
```
Response
{"message":"Memory added","status":"success"}

Query memory:
```
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice_uuid",
    "query": "Alice lives in wonderland and loves wolves",
    "category": "personal"
}'
```
Response
{
  "results": [
    {
      "created_at": "2025-12-28T15:02:34.241800-08:00",
      "hash": "c9b9ac228ea6032ce7cdfcbc0d700860",
      "id": "f667f910-cfeb-4d1a-b6f9-656b4e733384",
      "memory": "Alice loves wolves",
      "metadata": {
        "category": "personal"
      },
      "score": 0.84836686,
      "updated_at": null,
      "user_id": "alice_uuid"
    },
    {
      "created_at": "2025-12-28T15:02:34.222106-08:00",
      "hash": "51ad810f930ac6263447e38cecc7b62d",
      "id": "f22c30d4-888b-469d-8498-3bbb9aaaaa3a",
      "memory": "Alice lives in wonderland",
      "metadata": {
        "category": "personal"
      },
      "score": 0.83698416,
      "updated_at": null,
      "user_id": "alice_uuid"
    }
  ],
  "status": "success"
}

Delete memories older than 90 days:
```
curl -X POST http://localhost:8000/delete_old \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice_uuid"
}'
```
Response
{"deleted_count":0,"status":"success"}

# Graphiti Installation

1. cd ./graphiti
2. mkdir -p neo4j_data
3. create .env and add OPENAI_API_KEY, NEO4J_USERNAME and NEO4J_PASSWORD.
4. docker compose up -d

## Graphiti Endpoints

Add facts:
```
curl -X POST http://localhost:8001/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_456",
    "data": "The Sun is a G-type main-sequence star located at the center of the Solar System. It is composed primarily of hydrogen and helium with trace amounts of heavier elements such as oxygen, carbon, neon, and iron. Through nuclear fusion in its core, the Sun converts hydrogen into helium, releasing vast amounts of energy that radiate outward and provide light and heat to the planets orbiting it. This energy drives Earth’s climate, weather systems, and ultimately supports life. The Sun’s immense gravitational pull governs the motion of the Solar System, keeping planets, asteroids, and comets in stable orbits.",
    "category": "scientific-technical"
  }'
```
Response:
{"episode_name":"User_user_456_Ingest_1766964011","group_id":"user_456_scientific-technical","message":"Ingested for user user_456, category scientific-technical","status":"success"}

Query facts:
```
curl -X POST http://localhost:8001/strict_search \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_456",
    "query": "The Sun is a G-type main-sequence star located at the center of the Solar System.",
    "category": "scientific-technical"
  }'
```
Response:
{
  "count": 10,
  "results": [
    {
      "category": "scientific-technical",
      "entity": "Unknown Entity",
      "entity_id": "d344bb52-d960-474b-870c-76333a3ab55c",
      "facts": [
        {
          "fact": "The Sun is located at the center of the Solar System.",
          "target": "Unknown",
          "type": "related"
        }
      ],
      "summary": "The Sun is located at the center of the Solar System.",
      "type": "graph_match",
      "user_id": "user_456"
    },
    {
      "category": "scientific-technical",
      "entity": "Unknown Entity",
      "entity_id": "d344bb52-d960-474b-870c-76333a3ab55c",
      "facts": [
        {
          "fact": "The Sun's gravitational pull governs the motion of Planets in the Solar System.",
          "target": "Unknown",
          "type": "related"
        }
      ],
      "summary": "The Sun's gravitational pull governs the motion of Planets in the Solar System.",
      "type": "graph_match",
      "user_id": "user_456"
    },
… 8 more
  ],
  "scoped_to": "user_456_scientific-technical",
  "status": "success"
}

Delete facts older than 90 days:
```
curl -X POST http://localhost:8001/delete_old \
  -H "Content-Type: application/json" \
  -d '{
"user_id": "user_456"
}'
```
Response:
{"message":"Removed 0 episodes and 0 orphaned nodes.","status":"success"}

# Cognee Installation

1. cd ./cognee
2. mkdir -p cognee_postgres_data cognee_data
3. create .env and add DEEPSEEK_API_KEY and OPENAI_API_KEY.
4. docker compose up -d

## Cognee Endpoints

Add cognitive memory:
```
curl -X POST http://127.0.0.1:8002/add \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice",
    "category": "work",
    "data": "The Q3 financial report is due on October 15th. It must include the marketing budget analysis."
  }'
```
Response:
{"status":"success"}

Query cognitive memory:
```
curl -X POST http://127.0.0.1:8002/search \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice",
    "category": "work",
    "query": "What deadlines do I have coming up?"
  }'
```
Response:

{
  "results": [
    {
      "dataset_id": "7833f43d-ddc3-53a5-a1ef-75cd81b17823",
      "dataset_name": "alice_work",
      "dataset_tenant_id": null,
      "search_result": [
        "You have one deadline coming up: The Q3 financial report is due on October 15th."
      ]
    }
  ]
}

Delete cognitive memories older than 90 days:
```
curl -X POST http://127.0.0.1:8002/delete \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice",
    "categories": ["personal", "work", "general"],
    "days": 90
  }'
```
Response

{
  "details": {
    "cutoff_date": "2025-09-29T23:33:25.896418+00:00",
    "data_entries_deleted": 0,
    "empty_datasets_removed": 0
  },
  "message": "Processed cleanup.",
  "status": "success"
}

And this is all. If you like my work please donate at https://andrewstarlike.com/tutorials
