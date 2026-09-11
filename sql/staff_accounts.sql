begin;

create table if not exists public.staff_accounts (
  user_id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique,
  email text not null unique,
  role text not null check (role in ('admin', 'merchant')),
  store_id text unique references public.stores(id) on delete cascade,
  created_at timestamptz not null default now(),
  check ((role = 'admin' and store_id is null) or (role = 'merchant' and store_id is not null))
);

alter table public.staff_accounts enable row level security;
revoke all on public.staff_accounts from public, anon, authenticated;
grant select, insert, update, delete on public.staff_accounts to service_role;

commit;
