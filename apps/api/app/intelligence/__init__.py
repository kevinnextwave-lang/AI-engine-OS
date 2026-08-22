"""AI response intelligence (Milestone 3D).

Stage 1 (`deterministic.py`) extracts structure, URLs, citations, brand and
competitor strings, list positions and lexical sentiment cues. Stage 2
(`interpreter.py`) optionally asks an LLM for strictly-schematized JSON that
can only *refine* deterministic findings (never add unknown brands or change
application state directly). `pipeline.py` merges both into `ParsedResponse`.
"""

PARSER_VERSION = "response-parser/v1"
