-- Private, versioned source workbooks. The public API does not expose this schema.
create schema if not exists packsense_private;

create table if not exists packsense_private.reference_bundles (
    bundle_id text primary key check (bundle_id ~ '^[0-9a-f]{64}$'),
    food_sha256 text not null check (food_sha256 ~ '^[0-9a-f]{64}$'),
    material_sha256 text not null check (material_sha256 ~ '^[0-9a-f]{64}$'),
    food_data bytea not null check (octet_length(food_data) between 1 and 10485760),
    material_data bytea not null check (octet_length(material_data) between 1 and 10485760),
    food_rows integer not null check (food_rows > 0),
    material_rows integer not null check (material_rows > 0),
    created_at timestamptz not null default now()
);

create table if not exists packsense_private.active_reference_bundle (
    singleton boolean primary key default true check (singleton),
    bundle_id text not null references packsense_private.reference_bundles(bundle_id),
    activated_at timestamptz not null default now()
);

alter table packsense_private.reference_bundles enable row level security;
alter table packsense_private.active_reference_bundle enable row level security;
revoke all on schema packsense_private from public;
revoke all on all tables in schema packsense_private from public;
