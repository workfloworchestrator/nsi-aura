#  Copyright 2025 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import utc

from aura import state
from aura.models import STP, Reservation
from aura.nsi_comm import (
    NSI_RESERVE_TEMPLATE_XMLFILE,
    URN_STP_NAME,
    URN_STP_VLAN,
    generate_reserve_xml,
    nsi_soap_parse_reserve_reply,
    nsi_util_post_soap,
)
from aura.settings import settings

# Advanced Python Scheduler
# scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop(), timezone=utc)
scheduler = BackgroundScheduler(timezone=utc)
scheduler.start()

logger = structlog.get_logger()


def nsi_send_reserve_job(reservation_id: int) -> None:
    from aura.db import Session

    log = logger.bind(module=__name__, job=nsi_send_reserve_job.__name__, reservation_id=reservation_id)
    log.info("start nsi send reserve")
    reserve_templpath = os.path.join(os.path.join(os.getcwd(), "static"), NSI_RESERVE_TEMPLATE_XMLFILE)
    with open(reserve_templpath) as reserve_templfile:
        reserve_templstr = reserve_templfile.read()
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
        source_stp = session.query(STP).filter(STP.id == reservation.sourceSTP).one()  # TODO: replace with relation
        dest_stp = session.query(STP).filter(STP.id == reservation.destSTP).one()  # TODO: replace with relation
    # correlation_id = uuid4()
    log = log.bind(globalReservationId=reservation.globalReservationId, correlationId=reservation.correlationId)
    reserve_xml = generate_reserve_xml(
        reserve_templstr,  # SOAP reserve template
        reservation.correlationId,  # correlation id
        str(settings.NSA_BASE_URL) + "api/nsi/callback/",  # reply-to url
        reservation.description,  # reservation description
        reservation.globalReservationId,  # global reservation id
        reservation.startTime.replace(tzinfo=timezone.utc) if reservation.startTime else datetime.now(timezone.utc),
        # start time, TODO: proper timezone handling
        (
            reservation.endTime.replace(tzinfo=timezone.utc)
            if reservation.endTime
            else datetime.now(timezone.utc) + timedelta(weeks=1040)
        ),  # end time
        {URN_STP_NAME: source_stp.urn_base, URN_STP_VLAN: reservation.sourceVlan},  # source stp dict
        {URN_STP_NAME: dest_stp.urn_base, URN_STP_VLAN: reservation.destVlan},  # destination stp dict
        state.global_provider_nsa_id,  # provider nsa id
    )
    soap_xml = nsi_util_post_soap(state.global_soap_provider_url, reserve_xml)
    retdict = nsi_soap_parse_reserve_reply(soap_xml)
    with Session.begin() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
        reservation.connectionId = retdict["connectionId"]
    log.info("nsi reserve successful", connectionId=retdict["connectionId"])
