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
# `upgrade` first: the base image trails Debian's security updates between
# its own rebuilds (the image scan in security.yml is what notices).
# `age` encrypts every backup archive (v0.30.0): Debian's package, so its
# version is the one this image was built with, and Trivy scans it.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libpq5 liblz4-1 libzstd1 libxxhash0 age \
    && rm -rf /var/lib/apt/lists/* \
    && for tool in /usr/local/lib/pgclient/*/pg_*; do "$tool" --version || exit 1; done \
    && age --version && age-keygen --version

# The unprivileged user the entrypoint drops to, and data directories it
# owns. A new named volume inherits that ownership from the image.
RUN groupadd --gid 1000 cabinet \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin cabinet \
    && mkdir -p /data/photos /data/state /data/backups /data/documents \
    && chown -R cabinet:cabinet /data
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Exactly the versions in the lockfile, verified by hash; regenerate it with
# the command in docs/security.md when pyproject.toml's dependencies change.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
# pip goes last: nothing installs at runtime, and the libraries it bundles
# (msgpack, setuptools) would otherwise sit in the image unpatched.
RUN pip install --no-cache-dir --no-deps . \
    && python -m pip uninstall -y pip

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
