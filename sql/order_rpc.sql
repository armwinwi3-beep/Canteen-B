-- Atomic order placement and status changes.
-- Each function runs in one transaction: either the order, its items, the stock
-- change and the queue number all commit together, or none of them do.
-- Apply once to the Canteen Supabase project before deploying the matching API.
begin;

-- One counter row per store per Bangkok day. The row lock taken by the upsert
-- serialises queue numbers, so two orders can never get the same code.
create table if not exists public.order_counters (
  merchant_id text not null references public.stores(id) on delete cascade,
  order_day date not null,
  last_no integer not null check (last_no > 0),
  primary key (merchant_id, order_day)
);
alter table public.order_counters enable row level security;
revoke all on public.order_counters from public, anon, authenticated;
grant select, insert, update on public.order_counters to service_role;

create or replace function public.place_order(
  p_merchant_id text,
  p_prefix text,
  p_order_type text,
  p_customer_id uuid,
  p_customer_name text,
  p_items jsonb
) returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_day date := (now() at time zone 'Asia/Bangkok')::date;
  v_ids uuid[];
  v_qtys integer[];
  v_found integer;
  v_short text;
  v_total numeric;
  v_no integer;
  v_code text;
  v_order_id uuid := gen_random_uuid();
begin
  if p_order_type not in ('online', 'walk_in') then
    raise exception 'invalid_order_type';
  end if;

  -- Online orders need an open store; walk-in orders only need the store to exist.
  perform 1 from stores
   where id = p_merchant_id and (p_order_type = 'walk_in' or is_open)
   for share;
  if not found then
    raise exception 'store_closed';
  end if;

  -- Merge repeated products in the cart into one line each.
  select array_agg(product_id order by product_id), array_agg(qty order by product_id)
    into v_ids, v_qtys
    from (
      select (e->>'product_id')::uuid as product_id, sum((e->>'qty')::integer)::integer as qty
        from jsonb_array_elements(p_items) e
       group by 1
    ) s;
  if v_ids is null or exists (select 1 from unnest(v_qtys) q where q < 1) then
    raise exception 'product_unavailable';
  end if;

  -- Lock the products (in id order, to avoid deadlocks) before checking stock.
  select count(*) into v_found
    from (select 1 from products p
           where p.id = any(v_ids) and p.merchant_id = p_merchant_id
           order by p.id
           for update) locked;
  if v_found <> cardinality(v_ids) then
    raise exception 'product_unavailable';
  end if;

  select p.name into v_short
    from products p join unnest(v_ids, v_qtys) r(product_id, qty) on r.product_id = p.id
   where coalesce(p.is_tracking, false) and coalesce(p.stock, 0) < r.qty
   order by p.name
   limit 1;
  if found then
    raise exception 'insufficient_stock:%', v_short;
  end if;

  select sum(p.price * r.qty) into v_total
    from products p join unnest(v_ids, v_qtys) r(product_id, qty) on r.product_id = p.id;

  -- Seed today's counter from existing orders so numbering continues after deploy.
  insert into order_counters (merchant_id, order_day, last_no)
  values (
    p_merchant_id, v_day,
    (select count(*) from orders
      where merchant_id = p_merchant_id
        and created_at >= (v_day::timestamp at time zone 'Asia/Bangkok')
        and created_at <  ((v_day + 1)::timestamp at time zone 'Asia/Bangkok')) + 1
  )
  on conflict (merchant_id, order_day) do update set last_no = order_counters.last_no + 1
  returning last_no into v_no;
  v_code := coalesce(nullif(p_prefix, ''), 'Q') || '-' || lpad(v_no::text, 3, '0');

  insert into orders (id, order_code, merchant_id, customer_id, customer_name, order_type, total_price, status)
  values (v_order_id, v_code, p_merchant_id, p_customer_id, p_customer_name, p_order_type, v_total, 'pending');

  insert into order_items (order_id, product_id, name, qty, price, cost)
  select v_order_id, p.id, p.name, r.qty, p.price, coalesce(p.cost, 0)
    from products p join unnest(v_ids, v_qtys) r(product_id, qty) on r.product_id = p.id;

  update products p set stock = coalesce(p.stock, 0) - r.qty
    from unnest(v_ids, v_qtys) r(product_id, qty)
   where p.id = r.product_id and coalesce(p.is_tracking, false);

  return jsonb_build_object(
    'id', v_order_id, 'order_code', v_code, 'customer_id', p_customer_id,
    'customer_name', p_customer_name, 'total_price', v_total, 'status', 'pending'
  );
end;
$$;

-- Changes status under a row lock. Cancelling returns tracked stock exactly once;
-- a cancelled order is final so stock can never be returned twice.
create or replace function public.set_order_status(
  p_order_id uuid,
  p_merchant_id text,
  p_status text
) returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_old text;
  v_order orders%rowtype;
begin
  if p_status not in ('pending', 'cooking', 'completed', 'cancelled') then
    raise exception 'invalid_status';
  end if;

  select status into v_old from orders
   where id = p_order_id and merchant_id = p_merchant_id
   for update;
  if not found then
    raise exception 'order_not_found';
  end if;

  if v_old = p_status then
    select * into v_order from orders where id = p_order_id;
    return jsonb_build_object('changed', false, 'order', to_jsonb(v_order));
  end if;
  if v_old = 'cancelled' then
    raise exception 'order_cancelled';
  end if;

  update orders set status = p_status where id = p_order_id returning * into v_order;

  if p_status = 'cancelled' then
    update products p set stock = coalesce(p.stock, 0) + i.qty
      from (select product_id, sum(qty)::integer as qty
              from order_items where order_id = p_order_id and product_id is not null
             group by product_id) i
     where p.id = i.product_id and p.merchant_id = p_merchant_id and coalesce(p.is_tracking, false);
  end if;

  return jsonb_build_object('changed', true, 'order', to_jsonb(v_order));
end;
$$;

-- Only the backend (service role) may call these; never the browser.
revoke all on function public.place_order(text, text, text, uuid, text, jsonb) from public, anon, authenticated;
revoke all on function public.set_order_status(uuid, text, text) from public, anon, authenticated;
grant execute on function public.place_order(text, text, text, uuid, text, jsonb) to service_role;
grant execute on function public.set_order_status(uuid, text, text) to service_role;

commit;
