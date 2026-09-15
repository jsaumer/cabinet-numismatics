# pg_dump/pg_restore for in-app backups, from the PostgreSQL apt repository.
# Each dump uses the client matching the server's major version: a newer
# pg_dump writes settings (e.g. transaction_timeout) that an older server
# rejects on restore. Only the binaries and libpq are carried over; the full
# client packages drag in perl (~50 MB) for wrapper scripts Cabinet never uses.
ARG PG_CLIENT_MAJORS="14 15 16 17 18"

FROM python:3.14-slim AS pgclient
ARG PG_CLIENT_MAJORS
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && for major in $PG_CLIENT_MAJORS; do \
         apt-get install -y --no-install-recommends "postgresql-client-$major" \
         && mkdir -p "/pgclient/$major" \
         && cp "/usr/lib/postgresql/$major/bin/pg_dump" \
               "/usr/lib/postgresql/$major/bin/pg_restore" "/pgclient/$major/" \
         || exit 1; \
       done

FROM python:3.14-slim
COPY --from=pgclient /etc/apt/sources.list.d/pgdg.sources /etc/apt/sources.list.d/
COPY --from=pgclient /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
     /usr/share/postgresql-common/pgdg/
COPY --from=pgclient /pgclient/ /usr/local/lib/pgclient/
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 liblz4-1 libzstd1 libxxhash0 \
    && rm -rf /var/lib/apt/lists/* \
    && for tool in /usr/local/lib/pgclient/*/pg_*; do "$tool" --version || exit 1; done

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
