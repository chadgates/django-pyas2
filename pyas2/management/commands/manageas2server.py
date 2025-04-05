import gc
import os
import tempfile
from datetime import timedelta
from email.parser import BytesHeaderParser

import psutil
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from pyas2lib import Message as AS2Message
from pyas2lib import Mdn as As2Mdn
from pyas2.utils import run_post_send

from pyas2 import settings
from pyas2.models import Mdn, Message, Partnership


def handle_pid_file(pid_file, stdout):
    """Handles the creation, validation, and cleanup of a PID file in a cross-platform way."""
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            try:
                pid = int(f.read().strip())
                if psutil.pid_exists(pid):
                    stdout.write(
                        f"Another instance of this command is already running (PID: {pid})."
                    )
                    return False
            except ValueError:
                stdout.write("Invalid PID file. Removing it.")
                os.remove(pid_file)

    # Write the current PID to the PID file
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    return True


def cleanup_pid_file(pid_file, stdout):
    """Removes the PID file after processing."""
    if os.path.exists(pid_file):
        os.remove(pid_file)
        stdout.write("Lock released.")


def find_original_message(message, was_signed):
    as2message = message.as2message
    if was_signed and as2message.receiver.mdn_digest_alg:
        as2message.receiver.mdn_digest_alg = None
    return as2message


class Command(BaseCommand):
    """Command to manage the django pyas2 server."""

    help = (
        "Command to manage the as2 server, includes options to cleanup, "
        "handle async mdns and message retries"
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--clean",
            action="store_true",
            dest="clean",
            default=False,
            help="Cleans up all the old messages and archived files.",
        )

        parser.add_argument(
            "--retry",
            action="store_true",
            dest="retry",
            default=False,
            help="Retrying all failed outbound communications.",
        )

        parser.add_argument(
            "--async-mdns",
            action="store_true",
            dest="async_mdns",
            default=False,
            help="Handle sending and receiving of Asynchronous MDNs.",
        )

    def retry(self, retry_msg):
        """Retry sending the message to the partner."""
        # Increase the retry count
        if not retry_msg.retries:
            retry_msg.retries = 1
        else:
            retry_msg.retries += 1

        # if max retries has exceeded then mark message status as error

        if retry_msg.retries > min(settings.MAX_RETRIES, 2) and retry_msg.status == "P":
            retry_msg.detailed_status = (
                "Failed to receive asynchronous MDN within the threshold limit."
            )
            retry_msg.status = "E"
            retry_msg.save()
            return

        if retry_msg.retries > settings.MAX_RETRIES and retry_msg.status == "R":
            retry_msg.detailed_status = "Retry count exceeded the limit."
            retry_msg.status = "E"
            retry_msg.save()
            return

        self.stdout.write("Retry send the message with ID %s" % retry_msg.message_id)

        # Build and resend the AS2 message

        org, partner = Partnership.objects.get_as2_org_partner(
            retry_msg.organization.as2_name, retry_msg.partner.as2_name
        )

        as2message = AS2Message(
            sender=org.as2org,
            receiver=partner.as2partner,
        )
        try:
            as2message.build(
                retry_msg.payload.read(),
                filename=os.path.basename(retry_msg.payload.name),
                subject=retry_msg.partner.subject,
                content_type=retry_msg.partner.content_type,
                message_id = retry_msg.message_id,
            )
        except Exception as e:
            retry_msg.detailed_status = f"Failed to build message, error:\n{str(e)}"
            retry_msg.status = "E"
            retry_msg.save()
            return

        retry_msg.send_message(as2message.headers, as2message.content)


    def reprocess_mdn(self, reprocess_msg):
        """Reprocess the MDN linked to a pending message."""

        headers = reprocess_msg.mdn.headers.read()
        body = reprocess_msg.mdn.payload.read()
        was_signed = reprocess_msg.mdn.signed

        request_body = headers + b"\r\n" + body

        as2mdn = As2Mdn()
        status, detailed_status = as2mdn.parse(request_body, lambda x, y: find_original_message(reprocess_msg, was_signed))

        if status == "processed":
            reprocess_msg.status = "S"
            run_post_send(reprocess_msg)
        else:
            reprocess_msg.status = "E"
            reprocess_msg.detailed_status = (
                f"Partner failed to process message: {detailed_status}"
            )

        reprocess_msg.save()

    def handle(self, *args, **options):
        temp_dir = tempfile.gettempdir()  # Get the temporary directory for the OS

        if options["retry"]:
            pid_file = os.path.join(temp_dir, "retry.pid")
            if not handle_pid_file(pid_file, self.stdout):
                return

            try:
                self.stdout.write("Retrying all failed outbound messages")
                # Get the list of all messages with status retry
                failed_msgs = Message.objects.filter(status="R", direction="OUT")

                for failed_msg in failed_msgs:
                    self.retry(failed_msg)

                self.stdout.write("Processed all failed outbound messages")
            finally:
                cleanup_pid_file(pid_file, self.stdout)

        if options["async_mdns"]:
            pid_file = os.path.join(temp_dir, "async_mdn.pid")
            if not handle_pid_file(pid_file, self.stdout):
                return

            try:
                # First part of script sends asynchronous MDNs for inbound messages
                # received from partners fetch all the pending asynchronous
                # MDN objects
                self.stdout.write("Sending all pending asynchronous MDNs")
                in_pending_mdns = Mdn.objects.filter(status="P", payload__isnull=False)

                for pending_mdn in in_pending_mdns:
                    # Parse the MDN headers from text
                    header_parser = BytesHeaderParser()
                    mdn_headers = header_parser.parsebytes(pending_mdn.headers.read())
                    try:
                        # Set http basic auth if enabled in the partner profile
                        auth = None
                        if (
                            pending_mdn.message.partner
                            and pending_mdn.message.partner.http_auth
                        ):
                            auth = (
                                pending_mdn.message.partner.http_auth_user,
                                pending_mdn.message.partner.http_auth_pass,
                            )

                        # Post the MDN message to the url provided on the
                        # original as2 message
                        requests.post(
                            pending_mdn.return_url,
                            auth=auth,
                            headers=dict(mdn_headers.items()),
                            data=pending_mdn.payload.read(),
                        )
                        pending_mdn.status = "S"
                    except requests.exceptions.RequestException as e:
                        self.stdout.write(
                            'Failed to send MDN "%s", error: %s'
                            % (pending_mdn.mdn_id, e)
                        )

                    finally:
                        pending_mdn.save()

                # Second Part checks if MDNs have been received for outbound
                # messages to partners
                self.stdout.write(
                    'Checking messages waiting for MDNs for more than "%s" '
                    "minutes." % settings.ASYNC_MDN_WAIT
                )

                # Find all messages waiting MDNs for more than the set async m
                # dn wait time
                time_threshold = timezone.now() - timedelta(
                    minutes=settings.ASYNC_MDN_WAIT
                )
                out_pending_msgs = Message.objects.filter(
                    status="P",
                    direction="OUT",
                    timestamp__lt=time_threshold,
                    mdn__isnull=True,
                    payload__isnull=False,
                ).iterator(chunk_size=1000)

                # Retry sending the message if not MDN received.
                for pending_msg in out_pending_msgs:
                    self.retry(pending_msg)

                self.stdout.write("Successfully processed all pending mdns.")

                # Third Part checks if MDNs have been received for outbound
                # messages to partners, but MDN was not applied to the status of the message.

                out_pending_msgs = Message.objects.filter(
                    status="P",
                    direction="OUT",
                    mdn__isnull=False,
                ).iterator(chunk_size=1000)

                # Retry sending the message if not MDN received.
                for pending_msg in out_pending_msgs:
                    self.reprocess_mdn(pending_msg)

                self.stdout.write("Successfully processed all pending mdns.")


            except Exception as e:
                self.stdout.write(f"An error occurred: {e}")

            finally:
                cleanup_pid_file(pid_file, self.stdout)

        if options["clean"]:
            pid_file = os.path.join(temp_dir, "clean.pid")
            if not handle_pid_file(pid_file, self.stdout):
                return

            try:
                self.stdout.write("Cleanup maintenance process started")
                max_archive_dt = timezone.now() - timedelta(days=settings.MAX_ARCH_DAYS)
                self.stdout.write(
                    f"Delete all messages older than {settings.MAX_ARCH_DAYS} days"
                )

                chunk_size = 1000  # Adjust for memory-efficient iterator fetching
                old_messages = (
                    Message.objects.filter(timestamp__lt=max_archive_dt)
                    .order_by("timestamp")
                    .iterator(chunk_size=chunk_size)
                )

                processed_count = 0

                try:
                    for message in old_messages:
                        try:
                            with transaction.atomic():
                                # Delete related payloads and headers
                                message.payload.delete()
                                message.headers.delete()

                                try:
                                    message.mdn.payload.delete()
                                    message.mdn.headers.delete()
                                    message.mdn.delete()
                                except Mdn.DoesNotExist:
                                    pass

                                # Delete the message itself
                                message.delete()

                            processed_count += 1

                            if processed_count % chunk_size == 0:
                                self.stdout.write(
                                    f"Processed {processed_count} messages..."
                                )
                                gc.collect()  # Free memory periodically

                        except KeyboardInterrupt:
                            self.stdout.write("\nProcess interrupted by user.")
                            self.stdout.write(
                                f"Safely committed up to message {processed_count}. Exiting..."
                            )
                            break
                except Exception as e:
                    self.stdout.write(f"An error occurred: {e}")
                finally:
                    self.stdout.write(
                        f"Cleanup maintenance process completed. Total messages processed: {processed_count}"
                    )
            finally:
                cleanup_pid_file(pid_file, self.stdout)
