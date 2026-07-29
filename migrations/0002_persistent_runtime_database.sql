begin;

create table if not exists elegance_private.runtime_databases (
  id text primary key,
  revision bigint not null default 0 check (revision >= 0),
  sqlite_blob bytea not null,
  sha256 text not null check (length(sha256) = 64),
  size_bytes bigint not null check (size_bytes >= 0),
  source text not null default 'vercel',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table elegance_private.runtime_databases enable row level security;
revoke all on elegance_private.runtime_databases from public, anon, authenticated;
grant select, insert, update on elegance_private.runtime_databases to service_role;

commit;
