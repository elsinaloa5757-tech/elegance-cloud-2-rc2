from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EXCLUDED_TABLES = {"sqlite_sequence"}


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def pg_type(sqlite_type: str) -> str:
    value = (sqlite_type or "").upper()
    if "INT" in value:
        return "BIGINT"
    if any(x in value for x in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if "BLOB" in value:
        return "BYTEA"
    if "BOOL" in value:
        return "BOOLEAN"
    return "TEXT"


def normalize(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, float):
        return format(value, ".17g")
    return value


def logical_hash(columns: list[str], rows: Iterable[tuple[Any, ...]]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(columns, ensure_ascii=False, separators=(",", ":")).encode())
    for row in rows:
        digest.update(b"\n")
        digest.update(json.dumps([normalize(v) for v in row], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


def sqlite_manifest(db_path: Path) -> OrderedDict[str, dict[str, Any]]:
    out: OrderedDict[str, dict[str, Any]] = OrderedDict()
    with sqlite3.connect(db_path) as conn:
        tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        for table in tables:
            columns = [r[1] for r in conn.execute(f"pragma table_info({q(table)})")]
            order = ",".join(q(c) for c in columns)
            rows = list(conn.execute(f"select {order} from {q(table)} order by rowid"))
            out[table] = {"columns": columns, "rows": len(rows), "sha256": logical_hash(columns, rows)}
    return out


def create_tables(sqlite_conn: sqlite3.Connection, pg_conn: Any, schema: str) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(f"create schema if not exists {q(schema)}")
        tables = [r[0] for r in sqlite_conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        for table in tables:
            info = list(sqlite_conn.execute(f"pragma table_info({q(table)})"))
            defs = []
            pk_cols = []
            for _, name, type_name, notnull, default, pk in info:
                part = f"{q(name)} {pg_type(type_name)}"
                if notnull:
                    part += " not null"
                if default is not None and str(default).upper() not in {"CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"}:
                    # SQLite defaults are not always PostgreSQL-compatible; data is copied explicitly.
                    pass
                defs.append(part)
                if pk:
                    pk_cols.append((pk, name))
            if pk_cols:
                ordered = ", ".join(q(name) for _, name in sorted(pk_cols))
                defs.append(f"primary key ({ordered})")
            cur.execute(f"create table if not exists {q(schema)}.{q(table)} ({', '.join(defs)})")
    pg_conn.commit()


def copy_tables(sqlite_conn: sqlite3.Connection, pg_conn: Any, schema: str, truncate: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = [r[0] for r in sqlite_conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    for table in tables:
        info = list(sqlite_conn.execute(f"pragma table_info({q(table)})"))
        columns = [r[1] for r in info]
        rows = list(sqlite_conn.execute(f"select {','.join(q(c) for c in columns)} from {q(table)} order by rowid"))
        with pg_conn.cursor() as cur:
            if truncate:
                cur.execute(f"truncate table {q(schema)}.{q(table)} cascade")
            if rows:
                placeholders = ",".join(["%s"] * len(columns))
                statement = f"insert into {q(schema)}.{q(table)} ({','.join(q(c) for c in columns)}) values ({placeholders}) on conflict do nothing"
                cur.executemany(statement, rows)
        pg_conn.commit()
        counts[table] = len(rows)
    return counts


def postgres_manifest(pg_conn: Any, schema: str, source: OrderedDict[str, dict[str, Any]]) -> OrderedDict[str, dict[str, Any]]:
    out: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for table, expected in source.items():
        columns = expected["columns"]
        with pg_conn.cursor() as cur:
            cur.execute(f"select {','.join(q(c) for c in columns)} from {q(schema)}.{q(table)}")
            rows = cur.fetchall()
        # PostgreSQL has no SQLite rowid. Sort canonicalized rows for stable verification.
        rows = sorted(rows, key=lambda row: json.dumps([normalize(v) for v in row], ensure_ascii=False, sort_keys=True, default=str))
        source_hash_rows = sorted(
            _read_sqlite_rows(Path(os.environ["ELEGANCE_SQLITE_SOURCE"]), table, columns),
            key=lambda row: json.dumps([normalize(v) for v in row], ensure_ascii=False, sort_keys=True, default=str),
        )
        out[table] = {
            "columns": columns,
            "rows": len(rows),
            "sha256": logical_hash(columns, rows),
            "sourceCanonicalSha256": logical_hash(columns, source_hash_rows),
        }
    return out


def _read_sqlite_rows(path: Path, table: str, columns: list[str]) -> list[tuple[Any, ...]]:
    with sqlite3.connect(path) as conn:
        return list(conn.execute(f"select {','.join(q(c) for c in columns)} from {q(table)}"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Migra Elegance SQLite a PostgreSQL de forma repetible y verificable.")
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--schema", default=os.getenv("ELEGANCE_DB_SCHEMA", "elegance"))
    parser.add_argument("--truncate", action="store_true", help="Vacía las tablas destino antes de copiar.")
    parser.add_argument("--manifest", type=Path, default=Path("migration_report.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = args.sqlite.resolve()
    if not source.exists():
        raise SystemExit(f"SQLite no encontrado: {source}")
    source_manifest = sqlite_manifest(source)
    report: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "schema": args.schema,
        "tables": len(source_manifest),
        "sourceManifest": source_manifest,
        "dryRun": args.dry_run,
    }
    if args.dry_run:
        args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "dryRun": True, "tables": len(source_manifest), "manifest": str(args.manifest)}, ensure_ascii=False))
        return 0
    if not args.database_url:
        raise SystemExit("DATABASE_URL es obligatoria salvo en --dry-run.")
    import psycopg
    os.environ["ELEGANCE_SQLITE_SOURCE"] = str(source)
    with sqlite3.connect(source) as sqlite_conn, psycopg.connect(args.database_url) as pg_conn:
        create_tables(sqlite_conn, pg_conn, args.schema)
        report["copiedRows"] = copy_tables(sqlite_conn, pg_conn, args.schema, args.truncate)
        destination = postgres_manifest(pg_conn, args.schema, source_manifest)
    report["destinationManifest"] = destination
    mismatches = []
    for table, src in source_manifest.items():
        dst = destination[table]
        if src["rows"] != dst["rows"] or dst["sha256"] != dst["sourceCanonicalSha256"]:
            mismatches.append({"table": table, "sourceRows": src["rows"], "destinationRows": dst["rows"], "sourceHash": dst["sourceCanonicalSha256"], "destinationHash": dst["sha256"]})
    report["verified"] = not mismatches
    report["mismatches"] = mismatches
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok" if not mismatches else "mismatch", "verified": not mismatches, "tables": len(source_manifest), "manifest": str(args.manifest)}, ensure_ascii=False))
    return 0 if not mismatches else 2


if __name__ == "__main__":
    raise SystemExit(main())
