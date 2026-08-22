"""AI Search Graph v1 — relational projection of the graph (Milestone 4D).

No graph database: nodes are existing rows (projects, prompts, ai_models,
ai_responses, brand/competitor mentions, claims, citations, source pages,
source domains) and edges are the foreign keys and entity tables between
them. `queries.py` answers the graph questions with SQL and returns bounded
node/edge sets. See docs/ai-search-graph.md for the migration path.
"""

GRAPH_VERSION = "ai-search-graph/v1"
