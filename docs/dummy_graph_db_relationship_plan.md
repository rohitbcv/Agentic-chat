# Dummy DB Graph Relationship Plan

This document explains how to create graph relationships from the dummy relational DB.

## Current POC Status

The POC now implements a local derived graph read model inside the dummy DB:

- nodes live in `entity.entity`
- edges live in `entity.entity_relationship`
- the offline builder is `scripts/create_relationship_graph.py`
- the runtime route is `relationship_lookup` through the Access and Relationship Agent

This keeps the same graph semantics without introducing an external graph service yet. A future Neo4j, Memgraph, or Kuzu layer can be generated from the same source tables.

## Recommendation

Use the relational dummy DB as the source of truth and build the graph as a derived read model.

Good local graph choices:

- Neo4j Desktop or Neo4j Docker
- Memgraph
- Kuzu for embedded/local graph experiments

For this app, start with Neo4j or Kuzu.

Important rule:

- agents should only read the graph
- graph nodes/edges should be created by an offline ETL script
- no live agent should create, update, or delete graph data

## Core Node Types

| Node label | Source table | Key |
| --- | --- | --- |
| `Client` | `clients.clients` | `client_id` |
| `Organization` | `organizations.organizations` | `organization_id` |
| `User` | `users.users` | `user_id` |
| `City` | `world.cities` | `world_city_id` |
| `Event` | `general.events` | `event_id` |
| `ContentTopic` | `content.content_topic` | `topic_id` |
| `Post` | `content.content_topic_post` | `post_id` |
| `Media` | `media.media` | `media_id` |
| `MediaAnalysis` | `media.media_analysis_ai` | `media_analysis_id` |
| `Interaction` | `jx_bridge.interactions` | `interaction_id` |
| `Message` | `jx_bridge.messages` | `message_id` |
| `MetricSnapshot` | `analytics.social_media_post` | `analytics_id` |
| `KnowledgeChunk` | `general.knowledge_embeddings` | `embedding_id` |
| `MetricChunk` | `analytics.metric_embeddings` | `embedding_id` |
| `Client` comparable target | `clients.client_marketing_settings` + `clients.clients` | `client_id` |

## Core Edge Types

| Edge | From | To | Relational source |
| --- | --- | --- | --- |
| `BELONGS_TO_ORG` | `Client` | `Organization` | `clients.clients.organization_id` |
| `LOCATED_IN` | `Client` | `City` | `clients.clients.world_city_id` |
| `HAS_COLLABORATOR` | `Client` | `User` | `clients.clients_collaborators` |
| `MEMBER_OF_ORG` | `User` | `Organization` | `organizations.organization_users` |
| `HAS_TOPIC` | `Client` | `ContentTopic` | `content.content_topic.client_id` |
| `HAS_POST` | `ContentTopic` | `Post` | `content.content_topic_post.content_topic_id` |
| `PUBLISHED_ON` | `Post` | `MetricSnapshot` | `content.content_topic_post.network_post_ref` to `analytics.social_media_post.post_ref` |
| `USES_MEDIA` | `Post` | `Media` | `content.content_topic_post_media` |
| `HAS_ANALYSIS` | `Media` | `MediaAnalysis` | `media.media_analysis_ai.media_id` |
| `HAS_INTERACTION` | `Client` | `Interaction` | `jx_bridge.interactions.client_id` |
| `HAS_MESSAGE` | `Interaction` | `Message` | `jx_bridge.messages.interaction_id` |
| `HAS_EVENT_NEARBY` | `Client` | `Event` | client city to event city |
| `HAS_KNOWLEDGE_CHUNK` | `Client` | `KnowledgeChunk` | `general.knowledge_embeddings.client_id` |
| `HAS_METRIC_CHUNK` | `Client` | `MetricChunk` | `analytics.metric_embeddings.client_id` |
| `CHUNK_DERIVED_FROM` | `KnowledgeChunk` | source node | `source_table` and `source_pk` |
| `METRIC_CHUNK_DERIVED_FROM` | `MetricChunk` | `MetricSnapshot` | `source_table` and `source_pk` |
| `HAS_COMPARABLE_CLIENT` | `Client` | `Client` | inferred from same city, property type, average default rate band, and client marketing settings |

## Example Questions Graph Helps With

Graph DB is most useful when the question needs multiple hops:

- Which collaborators can see the client whose latest post used this media?
- Which events are near clients with family-traveler audiences?
- Which posts used media whose semantic analysis matches dining and also have engagement snapshots?
- Which clients in the same city have similar content themes?
- Who are likely competitors or comparable hotels for this client?
- What is connected to this client across organization, city, events, posts, media, inbox, and knowledge?

## Example Neo4j Cypher Shape

Create uniqueness constraints first:

```cypher
CREATE CONSTRAINT client_id IF NOT EXISTS FOR (n:Client) REQUIRE n.client_id IS UNIQUE;
CREATE CONSTRAINT user_id IF NOT EXISTS FOR (n:User) REQUIRE n.user_id IS UNIQUE;
CREATE CONSTRAINT org_id IF NOT EXISTS FOR (n:Organization) REQUIRE n.organization_id IS UNIQUE;
CREATE CONSTRAINT post_id IF NOT EXISTS FOR (n:Post) REQUIRE n.post_id IS UNIQUE;
CREATE CONSTRAINT media_id IF NOT EXISTS FOR (n:Media) REQUIRE n.media_id IS UNIQUE;
```

Create client-to-post path:

```cypher
MERGE (c:Client {client_id: $client_id})
SET c.name = $client_name
MERGE (t:ContentTopic {topic_id: $topic_id})
SET t.name = $topic_name
MERGE (p:Post {post_id: $post_id})
SET p.post_text = $post_text,
    p.post_datetime = $post_datetime,
    p.social_network = $social_network
MERGE (c)-[:HAS_TOPIC]->(t)
MERGE (t)-[:HAS_POST]->(p)
```

Create post-to-media path:

```cypher
MERGE (p:Post {post_id: $post_id})
MERGE (m:Media {media_id: $media_id})
SET m.name = $media_name
MERGE (p)-[:USES_MEDIA]->(m)
```

Create post-to-analytics path:

```cypher
MERGE (p:Post {post_id: $post_id})
MERGE (s:MetricSnapshot {analytics_id: $analytics_id})
SET s.likes = $likes,
    s.comments = $comments,
    s.reactions = $reactions,
    s.shares = $shares
MERGE (p)-[:PUBLISHED_ON]->(s)
```

## Query Example

Question:

`How is my last Instagram post performing and what media was attached?`

Graph query shape:

```cypher
MATCH (c:Client {client_id: $client_id})-[:HAS_TOPIC]->(:ContentTopic)-[:HAS_POST]->(p:Post)
WHERE p.social_network CONTAINS "instagram"
OPTIONAL MATCH (p)-[:PUBLISHED_ON]->(s:MetricSnapshot)
OPTIONAL MATCH (p)-[:USES_MEDIA]->(m:Media)-[:HAS_ANALYSIS]->(a:MediaAnalysis)
RETURN p, s, collect({media: m, analysis: a}) AS media_context
ORDER BY p.post_datetime DESC
LIMIT 1
```

## App Integration Plan

1. Keep SQL templates as the source of truth for exact facts.
2. Use graph only for relationship traversal and multi-hop explanation.
3. Build a nightly or manual ETL job from dummy/live read-only DB into graph.
4. Give the app a read-only graph user.
5. Add a `Graph Retriever` that accepts approved graph query templates only.
6. Add graph source traces with node labels, edge types, and path length.

## Why Not Replace SQL With Graph

Graph is not better for everything.

Use SQL for:

- exact counts
- schedules
- statuses
- approvals
- metric calculations

Use graph for:

- connected entity questions
- multi-hop explanation
- relationship discovery
- source-path visualization
