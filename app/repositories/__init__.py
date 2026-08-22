"""Repository layer: the only place that issues SQLAlchemy queries.

Services never touch the ORM/session directly — they depend on a repository
interface. This keeps persistence concerns (batching, chunking, upserts)
out of ingestion logic and makes services unit-testable with in-memory
fakes.
"""
