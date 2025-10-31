"""
Custom async-aware storage backend for django-pyas2.

This module provides an AsyncFileSystemStorage class that overrides Django's
FileSystemStorage to use aiofiles for true async file I/O operations in a thread pool.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import aiofiles
import aiofiles.os
from django.core.files.storage import FileSystemStorage
from django.core.files.base import File


class AsyncFileSystemStorage(FileSystemStorage):
    """
    Async-aware FileSystemStorage that uses aiofiles for non-blocking I/O.

    This storage backend overrides the _save() method to use aiofiles with operations
    run in a thread pool executor. This prevents blocking the event loop during file I/O.

    Usage in settings.py:
        STORAGES = {
            "as2files": {
                "BACKEND": "pyas2.storage.AsyncFileSystemStorage",
                "OPTIONS": {
                    "location": "data",
                },
            },
        }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create a thread pool executor for file operations
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="async_storage")

    def _save(self, name, content):
        """
        Override the internal _save method to use aiofiles in a thread pool.

        This is called by save() after the filename has been determined.
        We run aiofiles operations in a separate thread pool to avoid blocking.
        """
        import asyncio

        full_path = self.path(name)
        directory = os.path.dirname(full_path)

        # Check if we're in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in async context - create a task that runs in thread pool
            import concurrent.futures
            future = self._executor.submit(
                self._sync_write_with_aiofiles, full_path, directory, content
            )
            return future.result()
        except RuntimeError:
            # Not in async context, just run it synchronously in thread pool
            future = self._executor.submit(
                self._sync_write_with_aiofiles, full_path, directory, content
            )
            return future.result()

    def _sync_write_with_aiofiles(self, full_path, directory, content):
        """
        Synchronous wrapper that creates an event loop and runs aiofiles.
        This is executed in a thread pool.
        """
        import asyncio
        return asyncio.run(self._async_write_file(full_path, directory, content))

    async def _async_write_file(self, full_path, directory, content):
        """
        Async file writing using aiofiles.

        Args:
            full_path: Full path where the file will be saved
            directory: Directory path (will be created if it doesn't exist)
            content: File content to write

        Returns:
            The relative filename from storage root that was saved
        """
        # Create directory if it doesn't exist
        # Match Django's behavior: pass mode to makedirs() which only applies
        # permissions to newly created directories, not existing ones
        if directory:
            try:
                if self.directory_permissions_mode is not None:
                    # Reset umask for consistency with file_permissions_mode behavior
                    # (Django does this to ensure the mode is applied exactly as specified)
                    old_umask = os.umask(0)
                    try:
                        await aiofiles.os.makedirs(
                            directory, mode=self.directory_permissions_mode, exist_ok=True
                        )
                    finally:
                        os.umask(old_umask)
                else:
                    # No directory permissions specified, use default
                    await aiofiles.os.makedirs(directory, exist_ok=True)
            except FileExistsError:
                # Another thread/coroutine created it, that's fine
                pass

        # Write the file using aiofiles
        async with aiofiles.open(full_path, 'wb') as f:
            # If content is a File object, read it in chunks
            if isinstance(content, File):
                content.seek(0)  # Ensure we're at the beginning
                while True:
                    chunk = content.read(64 * 1024)  # Read 64KB at a time
                    if not chunk:
                        break
                    # Encode string chunks to bytes if necessary
                    if isinstance(chunk, str):
                        chunk = chunk.encode('utf-8')
                    await f.write(chunk)
            else:
                # Assume content is bytes or has a read() method
                if hasattr(content, 'read'):
                    content.seek(0)
                    data = content.read()
                else:
                    data = content
                # Encode string data to bytes if necessary
                if isinstance(data, str):
                    data = data.encode('utf-8')
                await f.write(data)

        # Set file permissions
        if self.file_permissions_mode is not None:
            # Use os module directly for chmod since aiofiles doesn't have async chmod
            os.chmod(full_path, self.file_permissions_mode)

        # Return the relative path from storage root (not just basename)
        # This is needed so Django can locate the file later
        return os.path.relpath(full_path, self.location)

    def delete(self, name):
        """
        Delete the file referenced by name.

        Uses aiofiles in a thread pool for non-blocking deletion.
        """
        if not name:
            return

        full_path = self.path(name)
        # Run deletion in thread pool
        future = self._executor.submit(
            self._sync_delete_with_aiofiles, full_path
        )
        future.result()

    def _sync_delete_with_aiofiles(self, full_path):
        """
        Synchronous wrapper that creates an event loop and runs aiofiles deletion.
        This is executed in a thread pool.
        """
        import asyncio
        return asyncio.run(self._async_delete(full_path))

    async def _async_delete(self, full_path):
        """Async file deletion using aiofiles."""
        # Check if file exists using stat
        try:
            await aiofiles.os.stat(full_path)
            # File exists, delete it
            await aiofiles.os.remove(full_path)
        except FileNotFoundError:
            # File doesn't exist, nothing to delete
            pass
