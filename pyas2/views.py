import logging
import os

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.shortcuts import Http404, HttpResponse, get_object_or_404
from django.urls import reverse_lazy
from django.utils.crypto import get_random_string
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import FormView
from pyas2lib import Mdn as As2Mdn
from pyas2lib import Message as As2Message
from pyas2lib import Organization as As2Organization
from pyas2lib import Partner as As2Partner
from pyas2lib.exceptions import DecryptionError, DuplicateDocument, IntegrityError

from pyas2 import settings
from pyas2.caching import (
    aget_cached_organizations_by_as2_name,
    aget_cached_partners_by_as2_name,
    aget_cached_partnerships_by_as2_name,
    get_cached_organizations_by_as2_name,
    get_cached_partners_by_as2_name,
    get_cached_partnerships_by_as2_name,
)
from pyas2.forms import SendAs2MessageForm
from pyas2.models import (
    Mdn,
    Message,
    Partner,
    Partnership,
    PrivateKey,
    PublicCertificate,
)
from pyas2.utils import run_post_receive, run_post_send

logger = logging.getLogger("pyas2")


@method_decorator(csrf_exempt, name="dispatch")
class ReceiveAs2Message(View):
    """
    Class receives AS2 requests from partners.
    Checks whether its an AS2 message or an MDN and acts accordingly.
    Supports both sync (WSGI) and async (ASGI) execution.
    """

    @staticmethod
    def find_message(message_id, partner_id):
        """Find the message using the message_id and return its pyas2 type"""
        message = Message.objects.filter(
            message_id=message_id, partner_id=partner_id.strip()
        ).first()
        if message:
            return message.get_as2message()
        return None

    @staticmethod
    async def afind_message(message_id, partner_id):
        """Async version: Find the message using the message_id and return its pyas2 type"""
        message = await Message.objects.filter(
            message_id=message_id, partner_id=partner_id.strip()
        ).afirst()
        if message:
            return await message.aget_as2message()
        return None

    @staticmethod
    def check_success_message_exists(message_id, partner_id):
        """Check if the message already exists in the system"""
        if settings.ERROR_ON_DUPLICATE:
            return Message.objects.filter(
                message_id=message_id,
                partner_id=partner_id.strip(),
                status__in=("S", "P"),
            ).exists()
        else:
            return False

    @staticmethod
    async def acheck_success_message_exists(message_id, partner_id):
        """Async version: Check if the message already exists in the system"""
        if settings.ERROR_ON_DUPLICATE:
            return await Message.objects.filter(
                message_id=message_id,
                partner_id=partner_id.strip(),
                status__in=("S", "P"),
            ).aexists()
        else:
            return False

    @staticmethod
    def check_same_message_exists(message_id, partner_id):
        """Check if the message already exists in the system"""
        return Message.objects.filter(
            message_id=message_id, partner_id=partner_id.strip()
        ).exists()

    @staticmethod
    async def acheck_same_message_exists(message_id, partner_id):
        """Async version: Check if the message already exists in the system"""
        return await Message.objects.filter(
            message_id=message_id, partner_id=partner_id.strip()
        ).aexists()

    @staticmethod
    def find_organization(org_id):
        """Find the org using the As2 Id and return its pyas2 type"""

        org_data = get_cached_organizations_by_as2_name(org_id)
        if org_data:
            # Return the computed as2org representation from the cached dictionary.
            return As2Organization(**org_data.get("as2org_params"))
        return None

    @staticmethod
    def find_partner(partner_id):
        """
        Find the partner by its as2_name using the cache.
        The cached data is stored as a dictionary keyed by the partner's as2_name.
        """
        partner_data = get_cached_partners_by_as2_name(partner_id)
        if partner_data:
            return As2Partner(**partner_data.get("as2partner_params"))
        return None

    @staticmethod
    def find_partnership(org_id, partner_id):
        """
        Find the partnership by its as2_name using the cache.
        """
        partnership_data = get_cached_partnerships_by_as2_name(org_id, partner_id)
        if partnership_data:
            return As2Organization(**partnership_data.get("as2org_params")), As2Partner(
                **partnership_data.get("as2partner_params")
            )

        return ReceiveAs2Message.find_organization(
            org_id
        ), ReceiveAs2Message.find_partner(partner_id)

        # return org.as2org if org else None, partner.as2partner if partner else None

    @staticmethod
    async def afind_organization(org_id):
        """Async version: Find the org using the As2 Id and return its pyas2 type"""
        org_data = await aget_cached_organizations_by_as2_name(org_id)
        if org_data:
            # Return the computed as2org representation from the cached dictionary.
            return As2Organization(**org_data.get("as2org_params"))
        return None

    @staticmethod
    async def afind_partner(partner_id):
        """
        Async version: Find the partner by its as2_name using the cache.
        The cached data is stored as a dictionary keyed by the partner's as2_name.
        """
        partner_data = await aget_cached_partners_by_as2_name(partner_id)
        if partner_data:
            return As2Partner(**partner_data.get("as2partner_params"))
        return None

    @staticmethod
    async def afind_partnership(org_id, partner_id):
        """
        Async version: Find the partnership by its as2_name using the cache.
        """
        partnership_data = await aget_cached_partnerships_by_as2_name(org_id, partner_id)
        if partnership_data:
            return As2Organization(**partnership_data.get("as2org_params")), As2Partner(
                **partnership_data.get("as2partner_params")
            )

        return await ReceiveAs2Message.afind_organization(
            org_id
        ), await ReceiveAs2Message.afind_partner(partner_id)

    @staticmethod
    def find_alternative_partnership(org_id, partner_id):
        org, partner = Partnership.objects.get_as2_org_partner_swap(
            as2_name_org=org_id, as2_name_partner=partner_id
        )
        return org.as2org if org else None, partner.as2partner if partner else None

    @staticmethod
    async def afind_alternative_partnership(org_id, partner_id):
        """Async version: Find alternative partnership using swapped keys"""
        org, partner = await Partnership.objects.aget_as2_org_partner_swap(
            as2_name_org=org_id, as2_name_partner=partner_id
        )
        return (
            await sync_to_async(lambda: org.as2org)() if org else None,
            await sync_to_async(lambda: partner.as2partner)() if partner else None,
        )

    @xframe_options_exempt
    @csrf_exempt
    async def post(self, request, *args, **kwargs):
        """
        Handle POST requests to the AS2 server.
        This async method works in both WSGI (sync) and ASGI (async) environments.
        Django automatically wraps it with async_to_sync in WSGI contexts.
        """
        # extract the  headers from the http request
        as2headers = ""
        for key in request.META:
            if key.startswith("HTTP") or key.startswith("CONTENT"):
                as2headers += (
                    f'{key.replace("HTTP_", "").replace("_", "-").lower()}: '
                    f"{request.META[key]}\n"
                )

        # build the body along with the headers
        request_body = as2headers.encode() + b"\r\n" + request.body
        logger.debug(
            f'Received an HTTP POST from {request.META["REMOTE_ADDR"]} '
            f"with payload :\n{request_body}"
        )

        # First try to see if this is an MDN
        logger.debug("Check to see if payload is an Asynchronous MDN.")
        as2mdn = As2Mdn()

        # Parse the mdn and get the message status
        # Note: as2mdn.parse is sync and expects sync callbacks, so we use find_message (not afind_message)
        status, detailed_status = await as2mdn.aparse(
            request_body, self.afind_message
        )

        if not detailed_status == "mdn-not-found":
            if detailed_status == "original-message-not-found":
                logger.warning(
                    f"Asynchronous MDN received, but referenced AS2 message {as2mdn.message_id} "
                    f"could not be found."
                )
                return HttpResponse(
                    _("AS2 ASYNC MDN has been received for unknown message.")
                )

            message = await Message.objects.select_related(
                "organization", "partner"
            ).aget(message_id=as2mdn.orig_message_id, direction="OUT")
            logger.info(
                f"Asynchronous MDN received for AS2 message {as2mdn.message_id} to organization "
                f"{message.organization.as2_name} from partner {message.partner.as2_name}"
            )

            # Update the message status and return the response
            if status == "processed":
                message.status = "S"
                await sync_to_async(run_post_send)(message)
            else:
                message.status = "E"
                message.detailed_status = (
                    f"Partner failed to process message: {detailed_status}"
                )
            # Save the message and create the mdn
            await message.asave()
            await Mdn.objects.acreate_from_as2mdn(
                as2mdn=as2mdn, message=message, status="R"
            )

            return HttpResponse(_("AS2 ASYNC MDN has been received"))

        else:
            logger.debug("Payload is not an MDN parse it as an AS2 Message")
            as2message = As2Message()

            status, exception, as2mdn = await as2message.aparse(
                request_body,
                find_org_partner_cb=self.afind_partnership,
                find_message_cb=self.acheck_success_message_exists,
            )

            if isinstance(exception[0], DecryptionError) or isinstance(
                exception[0], IntegrityError
            ):
                status, exception, as2mdn = await as2message.aparse(
                    request_body,
                    find_org_partner_cb=self.afind_alternative_partnership,
                    find_message_cb=self.acheck_success_message_exists,
                )

            logger.info(
                f'Received an AS2 message with id {as2message.headers.get("message-id")} for '
                f'organization {as2message.headers.get("as2-to")} from '
                f'partner {as2message.headers.get("as2-from")}.'
            )

            # In case of duplicates update message id
            if isinstance(exception[0], DuplicateDocument) or (
                not settings.ERROR_ON_DUPLICATE
                and await self.acheck_same_message_exists(
                    message_id=as2message.message_id,
                    partner_id=as2message.headers.get("as2-from"),
                )
            ):
                as2message.message_id += "_duplicate_" + get_random_string(5)

            # Create the Message and MDN objects
            message, full_fn = await Message.objects.acreate_from_as2message(
                as2message=as2message,
                filename=as2message.payload.get_filename(),
                payload=as2message.content,
                direction="IN",
                status="S" if status == "processed" else "E",
                detailed_status=exception[1],
            )

            # run post receive command on success
            if status == "processed":
                await sync_to_async(run_post_receive)(
                    message,
                    full_fn,
                    as2message.headers.get("as2-to"),
                    as2message.headers.get("as2-from"),
                )

            # Return the mdn in case of sync else return text message
            if as2mdn and as2mdn.mdn_mode == "SYNC":
                message.mdn = await Mdn.objects.acreate_from_as2mdn(
                    as2mdn=as2mdn, message=message, status="S"
                )
                response = HttpResponse(as2mdn.content)
                for key, value in as2mdn.headers.items():
                    response[key] = value
                return response

            elif as2mdn and as2mdn.mdn_mode == "ASYNC":
                await Mdn.objects.acreate_from_as2mdn(
                    as2mdn=as2mdn,
                    message=message,
                    status="P",
                    return_url=as2mdn.mdn_url,
                )
            return HttpResponse(_("AS2 message has been received"))

    async def get(self, request, *args, **kwargs):
        """
        Handle GET requests to the AS2 server.
        This async method works in both WSGI (sync) and ASGI (async) environments.
        """
        return HttpResponse(
            _("To submit an AS2 message, you must POST the message to this URL")
        )

    async def options(self, request, *args, **kwargs):
        """
        Handle OPTIONS requests to the AS2 server.
        This async method works in both WSGI (sync) and ASGI (async) environments.
        """
        response = HttpResponse()
        response["allow"] = ",".join(["POST", "GET"])
        return response


class SendAs2Message(FormView):
    """View for sending AS2 messages to a partner."""

    # pylint: disable=W0212
    template_name = "pyas2/send_as2_message.html"
    form_class = SendAs2MessageForm
    success_url = reverse_lazy(
        f"admin:{Message._meta.app_label}_{Message._meta.model_name}_changelist"
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "opts": Partner._meta,
                "change": True,
                "is_popup": False,
                "save_as": False,
                "has_delete_permission": False,
                "has_add_permission": False,
                "has_change_permission": False,
            }
        )
        return context

    def form_valid(self, form):
        # Send the file to the partner
        payload = form.cleaned_data["file"].read()
        org, partner = Partnership.objects.get_as2_org_partner(
            form.cleaned_data["organization"].as2_name,
            form.cleaned_data["partner"].as2_name,
        )
        as2message = As2Message(
            sender=org.as2org,
            receiver=partner.as2partner,
        )
        logger.debug(
            f'Building message from {form.cleaned_data["file"].name} to send to partner '
            f"{as2message.receiver.as2_name} from org {as2message.sender.as2_name}."
        )
        as2message.build(
            payload,
            filename=form.cleaned_data["file"].name,
            subject=form.cleaned_data["partner"].subject,
            content_type=form.cleaned_data["partner"].content_type,
            disposition_notification_to=form.cleaned_data["organization"].email_address
            or "no-reply@pyas2.com",
        )

        message, _ = Message.objects.create_from_as2message(
            as2message=as2message,
            payload=payload,
            filename=form.cleaned_data["file"].name,
            direction="OUT",
            status="P",
        )
        message.send_message(as2message.headers, as2message.content)
        if message.status in ["S", "P"]:
            messages.success(
                self.request, "Message has been successfully send to Partner."
            )
        else:
            messages.error(
                self.request,
                "Message transmission failed, check Messages tab for details.",
            )
        return super().form_valid(form)


class DownloadFile(View):
    """A generic view for downloading files such as payload, certificates..."""

    def get(self, request, obj_type, obj_id, *args, **kwargs):
        """Return the requested file bytes as a response."""
        filename = ""
        file_content = ""
        # Get the file content based
        if obj_type == "message_payload":
            obj = get_object_or_404(Message, pk=obj_id)
            filename = os.path.basename(obj.payload.name)
            file_content = obj.payload.read()

        elif obj_type == "mdn_payload":
            obj = get_object_or_404(Mdn, pk=obj_id)
            filename = os.path.basename(obj.payload.name)
            file_content = obj.payload.read()

        elif obj_type == "public_cert":
            obj = get_object_or_404(PublicCertificate, pk=obj_id)
            filename = obj.name
            file_content = obj.certificate

        elif obj_type == "private_key":
            obj = get_object_or_404(PrivateKey, pk=obj_id)
            filename = obj.name
            file_content = obj.key

        # Return the file contents as attachment
        if filename and file_content:
            response = HttpResponse(content_type="application/x-pem-file")
            disposition_type = "attachment"
            response["Content-Disposition"] = (
                disposition_type + "; filename=" + filename
            )
            response.write(bytes(file_content))
            return response
        else:
            raise Http404()
