Testing Guide
=============

Running Tests
-------------

This project contains both synchronous and asynchronous tests. Due to
SQLite’s limitations with concurrent access, async and sync tests should
be run separately.

Run All Sync Tests (Recommended)
--------------------------------

.. code-block:: console

    $ pytest -m "not asyncio"


Run All Async Tests
-------------------

.. code-block:: console

    $ pytest -m asyncio


Run All Tests Together
----------------------

.. code-block:: console

    $ pytest


**Note:** Running all tests together may result in database lock errors
with SQLite. This is a known limitation. For production environments,
consider using PostgreSQL which handles concurrent access better.

Test Categories
---------------

- **Sync Tests** (``test_basic.py``, ``test_advanced.py``, etc.): Test
  synchronous AS2 message processing
- **Async Tests** (``test_async_basic.py``): Test asynchronous AS2
  message processing with Django’s async views

Async View Implementation
-------------------------

The AS2 receive views (``/pyas2/as2receive/`` and ``/pyas2/as2receive``)
use Django 5.2's async view pattern:

- All HTTP methods (``post``, ``get``, ``options``) are defined as ``async def``
- Django automatically handles WSGI/ASGI adaptation
- In WSGI (sync) environments, Django wraps async views with ``async_to_sync``
- In ASGI (async) environments, views run natively async
- All database operations use async ORM methods (``.aget()``, ``.acreate()``, ``.asave()``, etc.)

This ensures backward compatibility while providing full async support.

Test Coverage Report, Linting, and Formatting
---------------------------------------------

To run tests including linting and formatting checks and generate a
coverage report, run:

.. code-block:: console

    pytest -m "not asyncio" --cov-report term --cov-config .coveragerc --cov=pyas2 --color=yes --black --pylama pyas2 --black ./pyas2/tests
