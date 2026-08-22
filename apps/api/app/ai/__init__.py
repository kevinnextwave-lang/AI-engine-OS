"""AI provider abstraction (Milestone 3A).

Business logic talks to `AIProvider.generate(AIRequest) -> AIResponse` only.
Provider SDK/HTTP details, parameter differences and exception classes stay
inside `app.ai.providers.*` and are normalized here.
"""
