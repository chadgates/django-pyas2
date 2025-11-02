"""
Profiling utilities for django-pyas2 async operations.

This module provides decorators and tools to profile async operations
and identify performance bottlenecks in the AS2 message processing pipeline.
"""
import asyncio
import functools
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, List, Optional

logger = logging.getLogger("pyas2.profiling")


class OperationTimer:
    """
    Context manager for timing operations and collecting statistics.

    Usage:
        timer = OperationTimer()

        # Sync context
        with timer.time("database_query"):
            # ... do work

        # Async context
        async with timer.atime("file_io"):
            # ... do async work

        # Get results
        print(timer.get_stats())
    """

    def __init__(self):
        self.timings: Dict[str, List[float]] = defaultdict(list)
        self.current_operation: Optional[str] = None
        self.operation_start: Optional[float] = None

    @contextmanager
    def time(self, operation_name: str):
        """Synchronous timing context manager"""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.timings[operation_name].append(duration * 1000)  # Convert to ms

    @asynccontextmanager
    async def atime(self, operation_name: str):
        """Asynchronous timing context manager"""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.timings[operation_name].append(duration * 1000)  # Convert to ms

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get timing statistics for all operations.

        Returns:
            Dictionary with operation names as keys and stats as values:
            {
                "operation_name": {
                    "count": 5,
                    "total": 150.5,  # ms
                    "mean": 30.1,    # ms
                    "min": 25.0,     # ms
                    "max": 35.2,     # ms
                }
            }
        """
        stats = {}
        for operation, times in self.timings.items():
            if times:
                stats[operation] = {
                    "count": len(times),
                    "total": sum(times),
                    "mean": sum(times) / len(times),
                    "min": min(times),
                    "max": max(times),
                }
        return stats

    def print_report(self, title: str = "Performance Report"):
        """Print a formatted report of timing statistics"""
        stats = self.get_stats()
        if not stats:
            logger.info(f"{title}: No timing data collected")
            return

        total_time = sum(s["total"] for s in stats.values())

        print(f"\n{'=' * 80}")
        print(f"{title}")
        print(f"{'=' * 80}")
        print(f"{'Operation':<30} {'Count':>8} {'Total':>10} {'Mean':>10} {'Min':>10} {'Max':>10} {'%':>6}")
        print(f"{'-' * 80}")

        # Sort by total time descending
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]["total"], reverse=True)

        for operation, data in sorted_stats:
            percentage = (data["total"] / total_time * 100) if total_time > 0 else 0
            print(
                f"{operation:<30} "
                f"{data['count']:>8} "
                f"{data['total']:>9.2f}ms "
                f"{data['mean']:>9.2f}ms "
                f"{data['min']:>9.2f}ms "
                f"{data['max']:>9.2f}ms "
                f"{percentage:>5.1f}%"
            )

        print(f"{'-' * 80}")
        print(f"{'TOTAL':<30} {sum(s['count'] for s in stats.values()):>8} {total_time:>9.2f}ms")
        print(f"{'=' * 80}\n")

    def reset(self):
        """Reset all timing data"""
        self.timings.clear()


def profile_async(operation_name: Optional[str] = None):
    """
    Decorator to profile async functions.

    Usage:
        @profile_async("process_message")
        async def process_message(msg):
            # ... processing logic
    """
    def decorator(func):
        name = operation_name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = (time.perf_counter() - start) * 1000  # ms
                logger.info(f"[PROFILE] {name}: {duration:.2f}ms")

        return wrapper
    return decorator


def profile_sync(operation_name: Optional[str] = None):
    """
    Decorator to profile synchronous functions.

    Usage:
        @profile_sync("encrypt_payload")
        def encrypt_payload(data):
            # ... encryption logic
    """
    def decorator(func):
        name = operation_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = (time.perf_counter() - start) * 1000  # ms
                logger.info(f"[PROFILE] {name}: {duration:.2f}ms")

        return wrapper
    return decorator


class AsyncProfiler:
    """
    Comprehensive profiler for async AS2 message processing.

    Tracks:
    - Database queries
    - File I/O operations
    - Network operations
    - Cryptographic operations
    - Cache hits/misses
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.timer = OperationTimer()
        self.cache_stats = {"hits": 0, "misses": 0}

    def record_cache_hit(self):
        """Record a cache hit"""
        self.cache_stats["hits"] += 1

    def record_cache_miss(self):
        """Record a cache miss"""
        self.cache_stats["misses"] += 1

    @asynccontextmanager
    async def profile(self, operation_name: str):
        """Profile an async operation"""
        if self.enabled:
            async with self.timer.atime(operation_name):
                yield
        else:
            yield

    @contextmanager
    def profile_sync(self, operation_name: str):
        """Profile a synchronous operation"""
        if self.enabled:
            with self.timer.time(operation_name):
                yield
        else:
            yield

    def get_report(self) -> Dict:
        """Get a comprehensive profiling report"""
        stats = self.timer.get_stats()

        # Group operations by type
        grouped = {
            "database": {},
            "file_io": {},
            "network": {},
            "crypto": {},
            "cache": {},
            "other": {},
        }

        for operation, data in stats.items():
            if "db_" in operation or "query" in operation:
                grouped["database"][operation] = data
            elif "file_" in operation or "save_" in operation or "read_" in operation:
                grouped["file_io"][operation] = data
            elif "http_" in operation or "network_" in operation or "send_" in operation:
                grouped["network"][operation] = data
            elif "encrypt" in operation or "decrypt" in operation or "sign" in operation:
                grouped["crypto"][operation] = data
            elif "cache_" in operation:
                grouped["cache"][operation] = data
            else:
                grouped["other"][operation] = data

        # Calculate totals per category
        report = {
            "categories": {},
            "cache": self.cache_stats,
            "operations": stats,
        }

        for category, operations in grouped.items():
            if operations:
                total = sum(op["total"] for op in operations.values())
                count = sum(op["count"] for op in operations.values())
                report["categories"][category] = {
                    "total_time": total,
                    "operation_count": count,
                    "operations": operations,
                }

        return report

    def print_detailed_report(self, title: str = "AS2 Message Processing Profile"):
        """Print a detailed profiling report with recommendations"""
        report = self.get_report()

        print(f"\n{'=' * 80}")
        print(f"{title}")
        print(f"{'=' * 80}\n")

        # Cache statistics
        total_cache_ops = self.cache_stats["hits"] + self.cache_stats["misses"]
        if total_cache_ops > 0:
            hit_rate = (self.cache_stats["hits"] / total_cache_ops) * 100
            print(f"Cache Statistics:")
            print(f"  Hits:       {self.cache_stats['hits']:>6} ({hit_rate:.1f}%)")
            print(f"  Misses:     {self.cache_stats['misses']:>6} ({100 - hit_rate:.1f}%)")
            print(f"  Total:      {total_cache_ops:>6}")
            print()

        # Category breakdown
        if report["categories"]:
            print(f"Time Breakdown by Category:")
            print(f"{'-' * 50}")

            total_time = sum(cat["total_time"] for cat in report["categories"].values())

            for category, data in sorted(
                report["categories"].items(),
                key=lambda x: x[1]["total_time"],
                reverse=True
            ):
                percentage = (data["total_time"] / total_time * 100) if total_time > 0 else 0
                print(
                    f"  {category.upper():<15} "
                    f"{data['total_time']:>10.2f}ms "
                    f"({data['operation_count']:>3} ops) "
                    f"{percentage:>5.1f}%"
                )

            print(f"{'-' * 50}")
            print(f"  {'TOTAL':<15} {total_time:>10.2f}ms\n")

        # Detailed operation timings
        self.timer.print_report("Detailed Operation Timings")

        # Recommendations
        self._print_recommendations(report)

    def _print_recommendations(self, report: Dict):
        """Print performance recommendations based on profiling data"""
        print(f"Performance Recommendations:")
        print(f"{'-' * 50}")

        recommendations = []

        # Check cache hit rate
        total_cache = self.cache_stats["hits"] + self.cache_stats["misses"]
        if total_cache > 0:
            hit_rate = (self.cache_stats["hits"] / total_cache) * 100
            if hit_rate < 80:
                recommendations.append(
                    f"⚠️  Cache hit rate is {hit_rate:.1f}%. Consider warming the cache "
                    "or increasing cache TTL."
                )

        # Check database time
        if "database" in report["categories"]:
            db_time = report["categories"]["database"]["total_time"]
            total_time = sum(cat["total_time"] for cat in report["categories"].values())
            db_percentage = (db_time / total_time * 100) if total_time > 0 else 0

            if db_percentage > 30:
                recommendations.append(
                    f"⚠️  Database operations account for {db_percentage:.1f}% of total time. "
                    "Consider adding more caching or optimizing queries."
                )

        # Check file I/O time
        if "file_io" in report["categories"]:
            io_time = report["categories"]["file_io"]["total_time"]
            total_time = sum(cat["total_time"] for cat in report["categories"].values())
            io_percentage = (io_time / total_time * 100) if total_time > 0 else 0

            if io_percentage > 40:
                recommendations.append(
                    f"⚠️  File I/O operations account for {io_percentage:.1f}% of total time. "
                    "Verify sync_to_async is being used correctly."
                )

        # Check for slow operations
        for operation, data in report["operations"].items():
            if data["mean"] > 100:  # Operations taking > 100ms on average
                recommendations.append(
                    f"⚠️  Operation '{operation}' averages {data['mean']:.2f}ms. "
                    "Consider optimization."
                )

        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                print(f"{i}. {rec}\n")
        else:
            print("✅ No significant performance issues detected!\n")

        print(f"{'=' * 80}\n")


# Global profiler instance for easy access
_global_profiler: Optional[AsyncProfiler] = None


def get_profiler(enabled: bool = True) -> AsyncProfiler:
    """Get the global profiler instance"""
    global _global_profiler
    if _global_profiler is None:
        _global_profiler = AsyncProfiler(enabled=enabled)
    return _global_profiler


def reset_profiler():
    """Reset the global profiler"""
    global _global_profiler
    if _global_profiler:
        _global_profiler.timer.reset()
        _global_profiler.cache_stats = {"hits": 0, "misses": 0}