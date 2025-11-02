"""
Test script to profile AS2 message processing operations.

Usage:
    python -m pyas2.profile_test

This script will:
1. Profile a complete message receiving workflow
2. Profile a message sending workflow
3. Generate performance reports with recommendations
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

import django
django.setup()

from pyas2.profiling import AsyncProfiler, get_profiler
from pyas2.models import Message, Organization, Partner, Partnership
from pyas2.caching import (
    aget_cached_organizations_by_as2_name,
    aget_cached_partnerships_by_as2_name,
)


async def profile_message_receive_workflow():
    """
    Profile the entire message receiving workflow.
    This simulates what happens in ReceiveAs2Message.post()
    """
    profiler = get_profiler(enabled=True)

    print("\n" + "=" * 80)
    print("PROFILING: Message Receive Workflow")
    print("=" * 80 + "\n")

    # Simulate parsing MDN first
    async with profiler.profile("1_parse_mdn"):
        await asyncio.sleep(0.005)  # Simulate parsing time (5ms)

    # Simulate finding message in database
    async with profiler.profile("2_db_query_find_message"):
        try:
            message = await Message.objects.select_related(
                "organization", "partner"
            ).afirst()
        except:
            message = None

    if not message:
        print("No messages found in database. Skipping workflow profile.")
        return

    # Simulate parsing AS2 message
    async with profiler.profile("3_parse_as2_message"):
        await asyncio.sleep(0.010)  # Simulate parsing time (10ms)

    # Check cache for organization
    async with profiler.profile("4_cache_lookup_organization"):
        org_data = await aget_cached_organizations_by_as2_name(message.organization_id)
        if org_data:
            profiler.record_cache_hit()
        else:
            profiler.record_cache_miss()

    # Check cache for partnership
    async with profiler.profile("5_cache_lookup_partnership"):
        partnership_data = await aget_cached_partnerships_by_as2_name(
            message.organization_id, message.partner_id
        )
        if partnership_data:
            profiler.record_cache_hit()
        else:
            profiler.record_cache_miss()

    # Simulate checking for duplicates
    async with profiler.profile("6_db_query_check_duplicates"):
        exists = await Message.objects.filter(
            message_id=message.message_id,
            partner_id=message.partner_id,
            status__in=("S", "P"),
        ).aexists()

    # Simulate creating message from AS2
    async with profiler.profile("7_db_create_message"):
        await asyncio.sleep(0.003)  # Simulate database insert time

    # Simulate file operations (headers)
    async with profiler.profile("8_file_io_save_headers"):
        await asyncio.sleep(0.015)  # Simulate file write time (15ms)

    # Simulate file operations (payload)
    async with profiler.profile("9_file_io_save_payload"):
        await asyncio.sleep(0.025)  # Simulate file write time (25ms)

    # Simulate saving to inbox folder
    async with profiler.profile("10_file_io_save_inbox"):
        await asyncio.sleep(0.020)  # Simulate file write time (20ms)

    # Simulate post-receive command
    async with profiler.profile("11_post_receive_command"):
        await asyncio.sleep(0.008)  # Simulate command execution

    # Print report
    profiler.print_detailed_report("Message Receive Workflow Profile")

    return profiler


async def profile_message_send_workflow():
    """
    Profile the entire message sending workflow.
    This simulates what happens in Message.asend_message()
    """
    profiler = AsyncProfiler(enabled=True)

    print("\n" + "=" * 80)
    print("PROFILING: Message Send Workflow")
    print("=" * 80 + "\n")

    # Get a message to send
    async with profiler.profile("1_db_query_get_message"):
        try:
            message = await Message.objects.select_related(
                "organization", "partner"
            ).filter(direction="OUT").afirst()
        except:
            message = None

    if not message:
        print("No outbound messages found. Skipping send workflow profile.")
        return

    # Load organization and partner
    async with profiler.profile("2_db_query_load_org_partner"):
        if message.organization_id and message.partner_id:
            org = await Organization.objects.aget(as2_name=message.organization_id)
            partner = await Partner.objects.aget(as2_name=message.partner_id)

    # Build AS2 message
    async with profiler.profile("3_build_as2_message"):
        await asyncio.sleep(0.005)  # Simulate message building

    # Cryptographic operations
    async with profiler.profile("4_crypto_sign_message"):
        await asyncio.sleep(0.030)  # Simulate signing (30ms)

    async with profiler.profile("5_crypto_encrypt_message"):
        await asyncio.sleep(0.040)  # Simulate encryption (40ms)

    # HTTP POST to partner
    async with profiler.profile("6_network_send_http_post"):
        await asyncio.sleep(0.150)  # Simulate network round trip (150ms)

    # Parse MDN response
    async with profiler.profile("7_parse_mdn_response"):
        await asyncio.sleep(0.008)  # Simulate parsing

    # Verify MDN signature
    async with profiler.profile("8_crypto_verify_mdn"):
        await asyncio.sleep(0.025)  # Simulate signature verification

    # Update message status
    async with profiler.profile("9_db_update_message_status"):
        await asyncio.sleep(0.003)  # Simulate database update

    # Create MDN record
    async with profiler.profile("10_db_create_mdn"):
        await asyncio.sleep(0.005)  # Simulate database insert

    # Save MDN files
    async with profiler.profile("11_file_io_save_mdn"):
        await asyncio.sleep(0.015)  # Simulate file write

    # Post-send command
    async with profiler.profile("12_post_send_command"):
        await asyncio.sleep(0.010)  # Simulate command execution

    # Print report
    profiler.print_detailed_report("Message Send Workflow Profile")

    return profiler


async def profile_cache_performance():
    """Profile cache lookup performance"""
    profiler = AsyncProfiler(enabled=True)

    print("\n" + "=" * 80)
    print("PROFILING: Cache Performance")
    print("=" * 80 + "\n")

    # Get some test data
    try:
        org = await Organization.objects.afirst()
        partner = await Partner.objects.afirst()

        if not org or not partner:
            print("No organizations or partners found. Skipping cache profile.")
            return
    except:
        print("Error accessing database. Skipping cache profile.")
        return

    # Warm up cache
    await aget_cached_organizations_by_as2_name(org.as2_name)
    await aget_cached_partnerships_by_as2_name(org.as2_name, partner.as2_name)

    # Test cache hits (should be fast)
    for i in range(10):
        async with profiler.profile("cache_hit_organization"):
            data = await aget_cached_organizations_by_as2_name(org.as2_name)
            if data:
                profiler.record_cache_hit()

        async with profiler.profile("cache_hit_partnership"):
            data = await aget_cached_partnerships_by_as2_name(
                org.as2_name, partner.as2_name
            )
            if data:
                profiler.record_cache_hit()

    # Test cache misses (will hit database)
    for i in range(3):
        fake_name = f"nonexistent_{i}"
        async with profiler.profile("cache_miss_organization"):
            data = await aget_cached_organizations_by_as2_name(fake_name)
            if not data:
                profiler.record_cache_miss()

    profiler.print_detailed_report("Cache Performance Profile")

    return profiler


async def profile_database_queries():
    """Profile database query performance"""
    profiler = AsyncProfiler(enabled=True)

    print("\n" + "=" * 80)
    print("PROFILING: Database Query Performance")
    print("=" * 80 + "\n")

    # Query without select_related
    async with profiler.profile("db_query_without_select_related"):
        try:
            message = await Message.objects.filter(direction="IN").afirst()
        except:
            message = None

    # Query with select_related
    async with profiler.profile("db_query_with_select_related"):
        try:
            message = await Message.objects.select_related(
                "organization", "partner"
            ).filter(direction="IN").afirst()
        except:
            message = None

    # Multiple queries in parallel
    async with profiler.profile("db_query_parallel_execution"):
        try:
            results = await asyncio.gather(
                Message.objects.filter(direction="IN").acount(),
                Message.objects.filter(direction="OUT").acount(),
                Organization.objects.acount(),
                Partner.objects.acount(),
            )
        except:
            pass

    # Exists check (should be fast)
    async with profiler.profile("db_query_exists_check"):
        try:
            exists = await Message.objects.filter(status="S").aexists()
        except:
            pass

    profiler.print_detailed_report("Database Query Performance Profile")

    return profiler


async def main():
    """Run all profiling tests"""
    print("\n" + "=" * 80)
    print("AS2 MESSAGE PROCESSING - COMPREHENSIVE PERFORMANCE PROFILE")
    print("=" * 80)

    try:
        # Profile each workflow
        await profile_cache_performance()
        await profile_database_queries()
        await profile_message_receive_workflow()
        await profile_message_send_workflow()

        print("\n" + "=" * 80)
        print("PROFILING COMPLETE")
        print("=" * 80 + "\n")

        print("Summary of Findings:")
        print("-" * 80)
        print("""
Based on the profiling results above, here are the key takeaways:

1. **Cache Performance**: Check the cache hit rate. Aim for >80% hit rate.
   - If low, consider warming the cache on startup or increasing TTL.

2. **Database Queries**: Look for queries taking >20ms.
   - Use select_related() and prefetch_related() where possible.
   - Ensure proper indexes exist on frequently queried fields.

3. **File I/O**: Should be <30ms per operation with sync_to_async.
   - If higher, check disk performance or consider async storage.

4. **Network Operations**: Typically 100-300ms depending on partner response time.
   - This is usually out of your control but monitor for anomalies.

5. **Cryptographic Operations**: Signing/encryption typically 20-50ms.
   - Consider hardware acceleration if this becomes a bottleneck.

For production profiling, consider:
- Using py-spy for sampling profiling: `py-spy top --pid <PID>`
- Using django-silk for request/response profiling
- Setting up application performance monitoring (APM) tools
        """)

    except Exception as e:
        print(f"Error during profiling: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())