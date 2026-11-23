"""Run independent Supabase queries at the same time instead of one after another."""
from concurrent.futures import ThreadPoolExecutor

import httpx
from supabase.lib.client_options import SyncClientOptions

_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="db")


def pooled_client_options() -> SyncClientOptions:
    """supabase-py defaults to one HTTP/2 connection, which sends our parallel
    queries one at a time. A pool of HTTP/1.1 keep-alive connections lets them
    really run together (measured: 3 queries 340 ms -> 120 ms)."""
    return SyncClientOptions(httpx_client=httpx.Client(
        http2=False,
        timeout=30,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=32, max_keepalive_connections=32, keepalive_expiry=60),
    ))


def run_parallel(*calls):
    """Call each zero-argument function concurrently; return results in order.
    The first exception raised by any call is re-raised."""
    futures = [_pool.submit(call) for call in calls]
    return [future.result() for future in futures]
