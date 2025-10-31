# -*- coding: utf-8 -*-
import logging
import os
from string import Template

logger = logging.getLogger("pyas2")


def run_post_send(message):
    """Execute command after successful send, can be used to notify
    successful sends"""

    command = message.partner.cmd_send
    if command:
        logger.debug(f"Execute post successful send command {command}")
        # Create command template and replace variables in the command
        command = Template(command)
        variables = {
            "filename": os.path.basename(message.payload.name),
            "sender": message.organization.as2_name,
            "receiver": message.partner.as2_name,
            "messageid": message.message_id,
        }
        variables.update(message.get_as2message().headers)

        # Execute the command
        os.system(command.safe_substitute(variables))


def run_post_receive(message, full_filename, org_as2id, partner_as2id):
    """Execute command after successful receive, can be used to call the
    edi program for further processing"""

    if org_as2id and partner_as2id:
        from pyas2.caching import get_cached_partners_by_as2_name
        partner = get_cached_partners_by_as2_name(partner_as2id)
    else:
        from pyas2.caching import get_cached_organizations_by_as2_name, get_cached_partners_by_as2_name
        partner = get_cached_partners_by_as2_name(message.partner_id)
        partner_as2id = message.partner_id
        org_as2id = message.organization_id
    command = partner.get("cmd_receive")

    if command:
        logger.debug(f"Execute post successful receive command {command}")

        # Create command template and replace variables in the command
        command = Template(command)
        variables = {
            "filename": os.path.basename(full_filename),
            "fullfilename": full_filename,
            "sender": partner_as2id,
            "receiver": org_as2id,
            "messageid": message.message_id,
        }
        variables.update(message.get_as2message().headers)

        # Execute the command
        os.system(command.safe_substitute(variables))
