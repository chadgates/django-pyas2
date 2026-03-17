# django-pyas2 Performance Analysis

Date: 2026-03-17
Branch: feature/perf-query-optimization (based on cargoo)

## Production Problem

Sentry traces from production (`as2.cargoo.com`) showed AS2 receive requests
taking **15-21 seconds**, with 11-15 seconds spent in database operations.
The server runs on Kubernetes with gunicorn (3 workers, gevent, 300 connections)
against Azure managed PostgreSQL.

## Root Cause Analysis

Three Sentry traces were analyzed. All showed the same pattern:

### 1. No connection pooling (2-4s per request)

Every request established a new TCP connection to Azure PostgreSQL:

```
connect ── 1,663ms to 4,338ms per request
```

**Cause:** Django's default behavior creates a new connection per request.
Azure managed PG adds TLS negotiation overhead on each connect.

### 2. update_or_create generates excessive savepoints (5-8s per request)

Django's `update_or_create()` internally uses:
- `SAVEPOINT` (round-trip)
- `SELECT ... FOR UPDATE` (round-trip)
- Nested `SAVEPOINT` (round-trip)
- `INSERT` or `UPDATE` (round-trip)
- `RELEASE SAVEPOINT` (round-trip)
- `RELEASE SAVEPOINT` (round-trip)

With Azure PG network latency of 300-1000ms per round-trip, this pattern
consumed 5-8 seconds per message+MDN creation.

**Sentry trace example (message creation):**
```
SAVEPOINT x1 ────── 1,013ms
SELECT FOR UPDATE ─   192ms
SAVEPOINT x2 ──────   660ms
INSERT message ────   490ms
RELEASE x2 ────────   502ms
RELEASE x1 ────────   421ms
                    ────────
                    3,278ms for one INSERT
```

### 3. Separate UPDATE after INSERT (0.5-1s wasted)

After `update_or_create`, file paths were saved with `save=False` and then
`message.save()` was called, generating a separate `UPDATE` query:

```
INSERT message ──── (via update_or_create)
... file I/O ...
UPDATE message ──── 303ms  ← unnecessary second write
```

### 4. Cache thundering herd on expiry

Cache TTL is 24 hours. When expired, every concurrent request triggered
a full reload of all partners/organizations/partnerships from the database.
Under load, this meant N simultaneous full-table scans.

## Fixes Applied

### Fix 1: Connection pooling

Added Django 5.1+ native connection pooling via `psycopg_pool`:

```python
# example/settings.py
'OPTIONS': {
    'pool': True,  # requires psycopg[binary,pool]
}
```

**Impact:** Eliminates 2-4s connect per request.

### Fix 2: Create-first pattern (replaces update_or_create)

```python
# Before: update_or_create (6 round-trips with savepoints)
message, _ = self.update_or_create(
    message_id=..., partner_id=..., organization_id=...,
    defaults=dict(direction=..., status=..., ...),
)
message.headers.save(..., save=False)
message.payload.save(..., save=False)
message.save()  # separate UPDATE

# After: create-first (1 round-trip for common case)
try:
    with transaction.atomic():
        message = self.model(message_id=..., partner_id=..., ...)
        message.headers.save(..., save=False)  # attach files
        message.payload.save(..., save=False)
        message.save(force_insert=True)  # single INSERT with files
except IntegrityError:
    # Rare: duplicate message, fall back to update
    message = self.get(message_id=..., partner_id=...)
    ...
    message.save()
```

**Impact:** Reduces 16 DB round-trips to ~6 per request. Eliminates
`SELECT FOR UPDATE` and nested savepoints. Combines file paths into INSERT.

### Fix 3: Cache reload locking

```python
_partner_lock = threading.Lock()

def _reload_partners_if_needed(as2_name):
    with _partner_lock:
        result = cache.get(key)  # double-check after lock
        if result is None:
            load_partner_cache()  # only one thread reloads
            result = cache.get(key)
    return result
```

**Impact:** On cache expiry, 1 thread reloads while others wait.
Prevents N concurrent full-table scans.

## Gunicorn Worker Class Recommendation

Production uses `--worker-class=gevent`. This is problematic because:

- gevent uses cooperative greenlets (coroutines)
- Crypto operations (OpenSSL via C extension) **do not yield** to gevent
- During decryption/signature verification (~20-50ms), the entire worker is frozen
- All 300 `worker-connections` are blocked during crypto

**Recommendation:** Switch to `gthread`:

```
# Before:
--worker-class=gevent --worker-connections=300

# After:
--worker-class=gthread --threads=8
```

With `gthread`, each connection gets a real OS thread. Crypto in one thread
does not block other threads. Combined with connection pooling, this gives
proper concurrency.

## Load Test Results

All tests: 500KB EDI payload, encrypted + signed AS2 messages (weighted 50%),
PostgreSQL 16, 4 workers, 30-second runs, 0% failure rate.

### Baseline: Cargoo branch (WSGI/gunicorn gevent, no fixes)

| Users | Requests | Req/s | Median | p95    | Max    |
|-------|----------|-------|--------|--------|--------|
| 10    | 888      | 29.5  | 330ms  | 400ms  | 721ms  |
| 25    | 616      | 20.4  | 1100ms | 2000ms | 2235ms |
| 50    | 726      | 24.1  | 2000ms | 2500ms | 2614ms |

### After fixes: Cargoo + pool + create-first (WSGI/gunicorn gthread)

| Users | Requests | Req/s | Median | p95    | Max    |
|-------|----------|-------|--------|--------|--------|
| 10    | 1596     | 53.0  | 180ms  | 280ms  | 482ms  |
| 25    | 1456     | 48.3  | 510ms  | 690ms  | 901ms  |
| 50    | 1087     | 36.0  | 1300ms | 1900ms | 2899ms |
| 100   | 1252     | 41.4  | 1400ms | 5500ms | 5923ms |

### Improvement

| Users | Req/s   | Median    | Total Requests |
|-------|---------|-----------|----------------|
| 10    | **+80%**  | **-45%**  | **+80%**       |
| 25    | **+137%** | **-54%**  | **+136%**      |
| 50    | **+49%**  | **-35%**  | **+50%**       |

### Per-request profiling (from test suite instrumentation)

Phase breakdown for message receive (36 samples, mixed scenarios):

| Phase                    | Avg     | Median  | What                              |
|--------------------------|---------|---------|-----------------------------------|
| Header extraction        | 0.37ms  | 0.29ms  | Parse MIME, extract AS2 IDs       |
| DB/cache lookup          | 8.77ms  | 8.56ms  | Org, partner, duplicate check     |
| Crypto (ThreadPool)      | 25.90ms | 26.14ms | Decrypt, verify signature         |
| Save message (file I/O)  | 5.58ms  | 5.60ms  | Headers + payload to disk         |
| Save MDN (file I/O)      | 5.54ms  | 5.07ms  | MDN headers + payload to disk     |
| **Total**                | **52.93ms** | **50.62ms** |                           |

- Plain messages (no crypto): ~16ms total
- Encrypted + signed messages: ~55ms total

### Estimated production impact (based on Sentry traces)

| Component           | Before     | After        | Saving     |
|---------------------|------------|--------------|------------|
| DB connect          | 2-4s       | ~0ms (pool)  | 2-4s       |
| SAVEPOINT overhead  | 5-8s       | ~1s          | 4-7s       |
| Separate UPDATE     | 0.5-1s     | 0ms          | 0.5-1s     |
| Crypto + I/O        | 2-3s       | ~same        | 0s         |
| **Total**           | **15-21s** | **3-5s**     | **10-16s** |

## How to Run Load Tests

### Prerequisites

```bash
pip install locust
pip install "psycopg[binary,pool]"
```

### Setup

```bash
# Set up PostgreSQL database
export USE_POSTGRES=True
export POSTGRES_DB=pyas2_loadtest
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432

python manage.py migrate
python manage.py setup_loadtest
```

### Start server

```bash
# With gthread (recommended):
gunicorn example.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --worker-class=gthread \
    --threads=8

# With gevent (baseline comparison):
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
gunicorn example.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --worker-class=gevent \
    --worker-connections=300
```

### Run locust

```bash
# Headless (quick test):
locust -f performance/locustfile.py \
    --host http://localhost:8000 \
    --users 25 --spawn-rate 25 \
    --run-time 30s --headless

# With web UI:
locust -f performance/locustfile.py \
    --host http://localhost:8000
# Then open http://localhost:8089

# Custom payload size (default 500KB):
PAYLOAD_SIZE_KB=1000 locust -f performance/locustfile.py \
    --host http://localhost:8000 \
    --users 10 --spawn-rate 10 \
    --run-time 30s --headless
```

### What the load test does

The locustfile pre-builds AS2 messages at startup using test certificates
(`pyas2/tests/fixtures/`), then sends them as HTTP POSTs to `/pyas2/as2receive/`.

Traffic mix (weighted):
- 50% encrypted + signed (heaviest, most realistic)
- 20% encrypted only
- 20% signed only
- 10% plain

Each request uses a unique `message-id` header.

## Files

- `performance/locustfile.py` - Locust load test configuration
- `performance/PERFORMANCE_ANALYSIS.md` - This document
- `pyas2/management/commands/setup_loadtest.py` - Management command to create test data