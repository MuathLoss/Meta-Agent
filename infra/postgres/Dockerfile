# PostgreSQL 16 with pgvector (spec v1.2, T05).
#
# Built on the official image rather than pgvector/pgvector because the official one runs on
# Debian trixie (glibc 2.41). Existing databases were created there, and moving them to an
# image with a different glibc changes text sort order ("collation version mismatch"), which
# can silently corrupt indexes on Arabic and other non-ASCII text. Keep base and data aligned.
FROM postgres:16.15-trixie
# pgvector from the PostgreSQL project's own apt repository, already configured in this image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends 'postgresql-16-pgvector=0.8.*' \
    && rm -rf /var/lib/apt/lists/*
