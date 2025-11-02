"""
Example integration of profiling into django-pyas2 views and models.

This file demonstrates how to add profiling to your existing code
without significantly modifying the implementation.

To enable profiling:
1. Set environment variable: PYAS2_ENABLE_PROFILING=1
2. Set log level to INFO to see profiling output
3. Add profiling decorators or context managers to critical paths
"""
import os
from functools import wraps

from django.http import HttpResponse
from pyas2.profiling import get_profiler, AsyncProfiler


# Enable profiling via environment variable
PROFILING_ENABLED = os.environ.get("PYAS2_ENABLE_PROFILING", "0") == "1"


def profile_view(view_name: str = None):
    """
    Decorator to profile Django async views.

    Usage:
        @profile_view("receive_as2_message")
        async def post(self, request, *args, **kwargs):
            # ... view logic
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not PROFILING_ENABLED:
                return await func(*args, **kwargs)

            profiler = get_profiler(enabled=True)
            name = view_name or func.__name__

            async with profiler.profile(f"view_{name}"):
                result = await func(*args, **kwargs)

            # Print report after view completes
            profiler.print_detailed_report(f"View: {name}")
            profiler.timer.reset()  # Reset for next request

            return result

        return wrapper
    return decorator


# Example: Instrumented ReceiveAs2Message view
class ProfiledReceiveAs2Message:
    """
    Example of how to add profiling to ReceiveAs2Message view.

    Replace the imports in views.py:
        from pyas2.profiling_integration import ProfiledReceiveAs2Message as ReceiveAs2Message
    """

    @profile_view("receive_as2_message")
    async def post(self, request, *args, **kwargs):
        """
        This is a simplified example showing where to add profiling.
        In your actual implementation, add profiler.profile() context managers
        around key operations.
        """
        profiler = get_profiler(enabled=PROFILING_ENABLED)

        # Extract headers
        async with profiler.profile("1_extract_headers"):
            as2headers = ""
            for key in request.META:
                if key.startswith("HTTP") or key.startswith("CONTENT"):
                    as2headers += (
                        f'{key.replace("HTTP_", "").replace("_", "-").lower()}: '
                        f"{request.META[key]}\n"
                    )

            request_body = as2headers.encode() + b"\r\n" + request.body

        # Parse MDN
        async with profiler.profile("2_parse_mdn"):
            from pyas2lib import Mdn as As2Mdn
            as2mdn = As2Mdn()
            status, detailed_status = await as2mdn.aparse(
                request_body, self.afind_message
            )

        # If not MDN, parse as message
        if detailed_status == "mdn-not-found":
            async with profiler.profile("3_parse_as2_message"):
                from pyas2lib import Message as As2Message
                as2message = As2Message()
                status, exception, as2mdn = await as2message.aparse(
                    request_body,
                    find_org_partner_cb=self.afind_partnership,
                    find_message_cb=self.acheck_success_message_exists,
                )

            # Create message
            async with profiler.profile("4_create_message"):
                from pyas2.models import Message
                message, full_fn = await Message.objects.acreate_from_as2message(
                    as2message=as2message,
                    filename=as2message.payload.get_filename(),
                    payload=as2message.content,
                    direction="IN",
                    status="S" if status == "processed" else "E",
                )

            # Post-receive processing
            async with profiler.profile("5_post_receive"):
                from asgiref.sync import sync_to_async
                from pyas2.utils import run_post_receive

                if status == "processed":
                    await sync_to_async(run_post_receive)(
                        message, full_fn,
                        as2message.headers.get("as2-to"),
                        as2message.headers.get("as2-from"),
                    )

        return HttpResponse("AS2 message has been received")


# Example: Instrumented model manager methods
class ProfiledMessageManager:
    """
    Example of how to add profiling to model manager methods.
    """

    async def acreate_from_as2message(
        self,
        as2message,
        payload,
        direction,
        status,
        filename=None,
        detailed_status=None,
    ):
        """
        Instrumented version of acreate_from_as2message with profiling.
        """
        profiler = get_profiler(enabled=PROFILING_ENABLED)

        # Database operations
        async with profiler.profile("db_create_message"):
            # Extract org/partner names
            if direction == "IN":
                organization = as2message.receiver.as2_name if as2message.receiver else None
                partner = as2message.sender.as2_name if as2message.sender else None
            else:
                partner = as2message.receiver.as2_name if as2message.receiver else None
                organization = as2message.sender.as2_name if as2message.sender else None

            # Create message
            message, created = await self.aupdate_or_create(
                message_id=as2message.message_id,
                partner_id=partner,
                organization_id=organization,
                defaults=dict(
                    direction=direction,
                    status=status,
                    compressed=as2message.compressed,
                    encrypted=as2message.encrypted,
                    signed=as2message.signed,
                    detailed_status=detailed_status,
                ),
            )

        # File operations
        from asgiref.sync import sync_to_async
        from django.core.files.base import ContentFile
        from uuid import uuid4

        if not filename:
            filename = f"{uuid4()}.msg"

        async with profiler.profile("file_save_headers_and_payload"):
            await sync_to_async(self._save_message_files)(
                message, filename, as2message.headers_str, payload
            )

        async with profiler.profile("db_save_message"):
            await message.asave()

        # Save to inbox
        full_filename = None
        if direction == "IN" and status == "S":
            import os
            import posixpath
            from pyas2.models import as2files_storage, Partner

            dirname = os.path.join("messages", organization, "inbox", partner)

            async with profiler.profile("db_query_partner_settings"):
                partner_obj = await Partner.objects.only('keep_filename').aget(as2_name=partner)

            if not partner_obj.keep_filename or not filename:
                filename = f"{message.message_id}.msg"

            full_filename = as2files_storage.generate_filename(
                posixpath.join(dirname, filename)
            )

            async with profiler.profile("file_save_inbox"):
                await sync_to_async(as2files_storage.save)(
                    name=full_filename, content=ContentFile(payload)
                )

        return message, full_filename


# Example: Instrumented cache functions
async def profiled_aget_cached_partnerships_by_as2_name(org_name: str, partner_name: str):
    """
    Example of profiled cache lookup function.
    """
    profiler = get_profiler(enabled=PROFILING_ENABLED)

    async with profiler.profile("cache_lookup_partnership"):
        from pyas2.caching import aget_cached_partnerships_by_as2_name
        result = await aget_cached_partnerships_by_as2_name(org_name, partner_name)

        if result:
            profiler.record_cache_hit()
        else:
            profiler.record_cache_miss()

        return result


# Middleware for automatic profiling
class AS2ProfilingMiddleware:
    """
    Django middleware to automatically profile all AS2 requests.

    Add to MIDDLEWARE in settings.py:
        MIDDLEWARE = [
            ...
            'pyas2.profiling_integration.AS2ProfilingMiddleware',
            ...
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.profiling_enabled = PROFILING_ENABLED

    async def __call__(self, request):
        if not self.profiling_enabled or not request.path.startswith('/pyas2/'):
            return await self.get_response(request)

        profiler = AsyncProfiler(enabled=True)

        # Profile the entire request
        async with profiler.profile("total_request_time"):
            response = await self.get_response(request)

        # Log profiling results
        profiler.print_detailed_report(f"Request: {request.method} {request.path}")

        return response


# CLI command for profiling
def run_profiling_test():
    """
    Run profiling test from command line:
        python -m pyas2.profiling_integration_example
    """
    import asyncio
    from pyas2.profile_test import main

    print("Starting AS2 profiling test...")
    print("=" * 80)
    print()

    asyncio.run(main())


if __name__ == "__main__":
    run_profiling_test()
