"""Stage 1 + optional Stage 2 → ParsedResponse."""

from app.intelligence.context import ParseContext
from app.intelligence.deterministic import deterministic_parse
from app.intelligence.interpreter import (
    Interpreter,
    build_request,
    merge,
    needs_interpretation,
    parse_llm_json,
)
from app.intelligence.schema import ParsedResponse


async def parse_response(
    text: str, ctx: ParseContext, interpreter: Interpreter | None = None
) -> ParsedResponse:
    parsed = deterministic_parse(text, ctx)
    if interpreter is None or not needs_interpretation(parsed):
        return parsed
    try:
        raw = await interpreter.interpret(build_request(text, ctx))
        if raw is None:
            parsed.stage2_error = "interpreter returned no output"
            return parsed
        llm = parse_llm_json(raw)
    except ValueError as exc:
        # Malformed or off-schema LLM output never reaches the database.
        parsed.stage2_error = str(exc)[:500]
        return parsed
    return merge(parsed, llm, ctx)
