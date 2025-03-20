# Copyright 2024-2025 SURF.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from datetime import timedelta, timezone, datetime
from typing import Any

import structlog

from aura.model import STP, Reservation
from aura.nsi_comm import (
    URN_STP_NAME,
    URN_STP_VLAN,
    generate_provision_xml,
    generate_release_xml,
    generate_reserve_abort_xml,
    generate_reserve_commit_xml,
    generate_reserve_xml,
    generate_terminate_xml,
    nsi_soap_parse_provision_reply,
    nsi_soap_parse_reserve_commit_reply,
    nsi_soap_parse_reserve_reply,
    nsi_util_post_soap,
    nsi_util_xml_to_dict,
    provision_templstr,
    release_templstr,
    reserve_abort_templstr,
    reserve_commit_templstr,
    reserve_templstr,
    terminate_templstr,
)
from aura.settings import settings

logger = structlog.get_logger()


def nsi_send_reserve(reservation: Reservation, source_stp: STP, dest_stp: STP) -> dict[str, str]:
    log = logger.bind(
        reservationId=reservation.id,
        globalReservationId=str(reservation.globalReservationId),
        correlationId=str(reservation.correlationId),
    )
    log.info("send reserve to nsi provider")
    reserve_xml = generate_reserve_xml(
        reserve_templstr,
        reservation.correlationId,
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",
        reservation.description,
        reservation.globalReservationId.urn,
        reservation.startTime.replace(tzinfo=timezone.utc) if reservation.startTime else datetime.now(timezone.utc),
        # start time, TODO: proper timezone handling
        (
            reservation.endTime.replace(tzinfo=timezone.utc)
            if reservation.endTime
            else datetime.now(timezone.utc) + timedelta(weeks=1040)
        ),  # end time
        {URN_STP_NAME: source_stp.urn_base, URN_STP_VLAN: reservation.sourceVlan},
        {URN_STP_NAME: dest_stp.urn_base, URN_STP_VLAN: reservation.destVlan},
        settings.PROVIDER_NSA_ID,
    )
    soap_xml = nsi_util_post_soap(settings.PROVIDER_NSA_URL, reserve_xml)
    retdict = nsi_soap_parse_reserve_reply(soap_xml)  # TODO: need error handling post soap failure
    log.info("reserve successfully sent", connectionId=str(retdict["connectionId"]))
    return retdict


def nsi_send_reserve_commit(reservation: Reservation) -> dict[str, str]:
    log = logger.bind(
        reservationId=reservation.id,
        correlationId=str(reservation.correlationId),
        connectionId=str(reservation.connectionId),
    )
    log.info("send reserve commit to nsi provider")
    soap_xml = generate_reserve_commit_xml(
        reserve_commit_templstr,
        reservation.correlationId,
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",
        str(reservation.connectionId),
        settings.PROVIDER_NSA_ID,
    )
    soap_xml = nsi_util_post_soap(settings.PROVIDER_NSA_URL, soap_xml)
    retdict = nsi_soap_parse_reserve_commit_reply(soap_xml)  # TODO: need error handling on failed post soap
    log.info("reserve commit successful sent")
    return retdict


def nsi_send_provision(reservation: Reservation) -> dict[str, str]:
    log = logger.bind(
        reservationId=reservation.id,
        correlationId=str(reservation.correlationId),
        connectionId=str(reservation.connectionId),
    )
    log.info("send provision to nsi provider")
    soap_xml = generate_provision_xml(
        provision_templstr,
        reservation.correlationId,
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",
        str(reservation.connectionId),
        settings.PROVIDER_NSA_ID,
    )
    soap_xml = nsi_util_post_soap(settings.PROVIDER_NSA_URL, soap_xml)
    retdict = nsi_soap_parse_provision_reply(soap_xml)  # TODO: need error handling on failed post soap
    log.info("provision successful sent")
    return retdict


def nsi_send_reserve_abort(reservation: Reservation) -> dict[str, Any]:
    soap_xml = generate_reserve_abort_xml(
        reserve_abort_templstr,
        reservation.correlationId,
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",
        str(reservation.connectionId),
        settings.PROVIDER_NSA_ID,
    )
    soap_xml = nsi_util_post_soap(settings.PROVIDER_NSA_URL, soap_xml)
    return nsi_util_xml_to_dict(soap_xml)


def nsi_send_release(reservation: Reservation) -> dict[str, Any]:
    soap_xml = generate_release_xml(
        release_templstr,
        reservation.correlationId,
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",
        str(reservation.connectionId),
        settings.PROVIDER_NSA_ID,
    )
    soap_xml = nsi_util_post_soap(settings.PROVIDER_NSA_URL, soap_xml)
    return nsi_util_xml_to_dict(soap_xml)


def nsi_send_terminate(reservation: Reservation) -> dict[str, Any]:
    soap_xml = generate_terminate_xml(
        terminate_templstr,
        reservation.correlationId,
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",
        str(reservation.connectionId),
        settings.PROVIDER_NSA_ID,
    )
    soap_xml = nsi_util_post_soap(settings.PROVIDER_NSA_URL, soap_xml)
    return nsi_util_xml_to_dict(soap_xml)
