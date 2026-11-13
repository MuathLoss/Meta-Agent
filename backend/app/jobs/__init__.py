"""Background jobs run by the RQ worker (spec v1.2, T07).

Redis holds the queue only. Anything that must survive (billing, usage, document status)
lives in PostgreSQL; a job reads and writes it there.
"""
