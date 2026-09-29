-- The hosted Python runtime reads the active pair but cannot import or activate bundles.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'packsense_reader') then
        create role packsense_reader nologin;
    end if;
end
$$;

grant usage on schema packsense_private to packsense_reader;
grant select on packsense_private.reference_bundles to packsense_reader;
grant select on packsense_private.active_reference_bundle to packsense_reader;

create policy reference_bundles_read on packsense_private.reference_bundles
    for select to packsense_reader using (true);
create policy active_reference_bundle_read on packsense_private.active_reference_bundle
    for select to packsense_reader using (true);
