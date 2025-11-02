# Django-pyas2 Performance Profiling Guide

This guide explains how to profile your django-pyas2 application to identify performance bottlenecks and optimize async operations.

## Quick Start

### 1. Run Basic Profiling Test

```bash
# From project root
python -m pyas2.profile_test
```

This will profile:
- Cache performance
- Database query performance
- Message receiving workflow
- Message sending workflow

### 2. Enable Production Profiling

Set environment variable before starting your server:

```bash
export PYAS2_ENABLE_PROFILING=1
python manage.py runserver
```

Or in your production environment, set in your deployment configuration.

### 3. View Profiling Output

Profiling results are printed to stdout/logs after each request. Look for lines starting with `[PROFILE]`.

## Profiling Tools

### OperationTimer

Use for granular timing of specific operations:

```python
from pyas2.profiling import OperationTimer

timer = OperationTimer()

# Synchronous operation
with timer.time("database_query"):
    # ... do work
    pass

# Asynchronous operation
async with timer.atime("file_io"):
    # ... do async work
    pass

# Get results
timer.print_report("My Operation Profile")
```

### AsyncProfiler

Comprehensive profiler with category grouping:

```python
from pyas2.profiling import AsyncProfiler

profiler = AsyncProfiler(enabled=True)

async with profiler.profile("db_query_users"):
    users = await User.objects.all().acount()

async with profiler.profile("file_save_payload"):
    await sync_to_async(save_file)(payload)

# Track cache hits/misses
profiler.record_cache_hit()
profiler.record_cache_miss()

# Generate report
profiler.print_detailed_report("Message Processing")
```

### Decorators

Profile entire functions:

```python
from pyas2.profiling import profile_async, profile_sync

@profile_async("process_message")
async def process_message(msg):
    # ... processing logic
    pass

@profile_sync("encrypt_payload")
def encrypt_payload(data):
    # ... encryption logic
    pass
```

## Integration with Your Code

### Option 1: Add to Views (Recommended for Development)

```python
from pyas2.profiling import get_profiler

class ReceiveAs2Message(View):
    async def post(self, request, *args, **kwargs):
        profiler = get_profiler(enabled=True)

        async with profiler.profile("parse_request"):
            # ... parse request
            pass

        async with profiler.profile("process_message"):
            # ... process message
            pass

        # Print report
        profiler.print_detailed_report("AS2 Message Receive")

        return HttpResponse("OK")
```

### Option 2: Use Middleware (Recommended for Production)

Add to `settings.py`:

```python
MIDDLEWARE = [
    ...
    'pyas2.profiling_integration_example.AS2ProfilingMiddleware',
    ...
]
```

### Option 3: Environment Variable Control

Only enable profiling when needed:

```python
import os
from pyas2.profiling import get_profiler

PROFILING_ENABLED = os.environ.get('PYAS2_ENABLE_PROFILING', '0') == '1'

profiler = get_profiler(enabled=PROFILING_ENABLED)
```

## Understanding Profile Reports

### Sample Output

```
================================================================================
Message Receive Workflow Profile
================================================================================

Cache Statistics:
  Hits:          15 (88.2%)
  Misses:         2 (11.8%)
  Total:         17

Time Breakdown by Category:
--------------------------------------------------
  FILE_IO         75.50ms (  3 ops)  45.3%
  DATABASE        35.20ms (  5 ops)  21.1%
  NETWORK        150.30ms (  1 ops)  30.2%
  CRYPTO          40.50ms (  2 ops)   8.4%
--------------------------------------------------
  TOTAL          301.50ms

Detailed Operation Timings
================================================================================
Operation                      Count      Total       Mean        Min        Max      %
--------------------------------------------------------------------------------
network_send_http_post             1    150.30ms    150.30ms    150.30ms    150.30ms  49.9%
file_io_save_payload               1     25.00ms     25.00ms     25.00ms     25.00ms  14.5%
crypto_encrypt_message             1     40.00ms     40.00ms     40.00ms     40.00ms  13.3%
file_io_save_inbox                 1     20.00ms     20.00ms     20.00ms     20.00ms  11.6%
db_create_message                  1     15.00ms     15.00ms     15.00ms     15.00ms   8.7%
--------------------------------------------------------------------------------
TOTAL                              5    301.50ms

Performance Recommendations:
--------------------------------------------------
✅ No significant performance issues detected!

================================================================================
```

### Key Metrics to Watch

1. **Cache Hit Rate**: Should be >80%
   - If low: Increase cache TTL or warm cache on startup

2. **Database Time**: Should be <30% of total
   - If high: Add indexes, use select_related(), increase caching

3. **File I/O Time**: Should be <40% of total
   - If high: Verify sync_to_async is used, check disk performance

4. **Network Time**: Typically 100-300ms per request
   - If high: Check partner response times, network latency

5. **Crypto Time**: Typically 20-50ms for sign/encrypt
   - If high: Consider hardware acceleration

## Advanced Profiling

### Using py-spy for Production

For live production profiling without code changes:

```bash
# Install py-spy
pip install py-spy

# Profile running process
py-spy top --pid <process_id>

# Generate flamegraph
py-spy record -o profile.svg --pid <process_id> --duration 60
```

### Using django-silk

For request/response profiling in development:

```bash
pip install django-silk

# Add to INSTALLED_APPS
INSTALLED_APPS = [
    ...
    'silk',
]

# Add to MIDDLEWARE
MIDDLEWARE = [
    'silk.middleware.SilkyMiddleware',
    ...
]

# Add to urls.py
urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]
```

Visit `/silk/` to see detailed profiling.

### Using cProfile for Deep Analysis

For function-level profiling:

```bash
python -m cProfile -o profile.stats manage.py runserver

# Analyze with snakeviz
pip install snakeviz
snakeviz profile.stats
```

## Common Performance Issues

### Issue 1: Low Cache Hit Rate

**Symptom**: Cache hit rate <60%

**Solutions**:
- Increase cache TTL in `caching.py`
- Warm cache on application startup
- Review cache key generation logic

### Issue 2: High Database Time

**Symptom**: Database operations >40% of total time

**Solutions**:
- Add `select_related()` and `prefetch_related()`
- Ensure indexes on frequently queried fields
- Consider denormalization for read-heavy tables

### Issue 3: Blocking File I/O

**Symptom**: File operations taking >100ms

**Solutions**:
- Verify `sync_to_async` is wrapping FileField operations
- Check disk I/O performance
- Consider using faster storage (SSD, NVMe)

### Issue 4: Slow Network Operations

**Symptom**: Network requests >500ms

**Solutions**:
- Check partner server response times
- Implement connection pooling
- Consider async retries with exponential backoff

## Profiling Best Practices

1. **Profile in Production-Like Environment**
   - Use production data volumes
   - Match production hardware specs
   - Test under realistic load

2. **Profile Multiple Scenarios**
   - Small messages vs large messages
   - Encrypted vs unencrypted
   - Cached vs uncached

3. **Establish Baselines**
   - Record performance before changes
   - Compare after optimizations
   - Track trends over time

4. **Focus on the Biggest Bottlenecks**
   - Optimize operations taking >30% of time first
   - Don't micro-optimize <1% operations

5. **Load Testing**
   - Use tools like `locust` or `ab` for load testing
   - Profile under different concurrency levels
   - Find your throughput limits

## Example Load Test

Using `locust` for load testing:

```python
# locustfile.py
from locust import HttpUser, task, between

class AS2User(HttpUser):
    wait_time = between(1, 3)

    @task
    def send_message(self):
        with open('test_message.as2', 'rb') as f:
            self.client.post(
                '/pyas2/as2receive',
                data=f.read(),
                headers={
                    'Content-Type': 'application/pkcs7-mime',
                    'AS2-From': 'test-org',
                    'AS2-To': 'test-partner',
                }
            )
```

Run with:
```bash
locust -f locustfile.py --host http://localhost:8000
```

## Monitoring in Production

Set up continuous monitoring:

1. **Application Performance Monitoring (APM)**
   - New Relic
   - DataDog
   - Sentry Performance

2. **Custom Metrics**
   - Export profiling data to StatsD/Prometheus
   - Create dashboards in Grafana
   - Set up alerts for anomalies

3. **Log Analysis**
   - Aggregate `[PROFILE]` logs
   - Calculate percentiles (p50, p95, p99)
   - Track performance regressions

## Support

For profiling assistance:
- GitHub Issues: https://github.com/abhishek-ram/django-pyas2/issues
- Documentation: https://django-pyas2.readthedocs.io/

## Next Steps

1. Run `python -m pyas2.profile_test` to get baseline metrics
2. Enable profiling in development: `export PYAS2_ENABLE_PROFILING=1`
3. Identify your top 3 bottlenecks
4. Optimize and re-profile
5. Set up production monitoring