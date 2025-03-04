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

from uuid import UUID, uuid4

import structlog
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import utc

from aura.db import Session
from aura.model import STP, Reservation
from aura.nsi_comm import nsi_send_provision, nsi_send_reserve, nsi_send_reserve_commit, nsi_send_terminate

# Advanced Python Scheduler
# scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop(), timezone=utc)
scheduler = BackgroundScheduler(
    jobstores={"default": MemoryJobStore()},
    executors={"default": ThreadPoolExecutor(max_workers=10)},
    job_defaults={"coalesce": False, "max_instances": 1, "misfire_grace_time": None},
    timezone=utc,
)
scheduler.start()


logger = structlog.get_logger()


def new_correlation_id_on_reservation(reservation_id: int) -> None:
    with Session.begin() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
        reservation.correlationId = uuid4()


def nsi_send_reserve_job(reservation_id: int) -> None:
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
        source_stp = session.query(STP).filter(STP.id == reservation.sourceStpId).one()  # TODO: replace with relation
        dest_stp = session.query(STP).filter(STP.id == reservation.destStpId).one()  # TODO: replace with relation
    retdict = nsi_send_reserve(reservation, source_stp, dest_stp)  # TODO: need error handling post soap failure
    with Session.begin() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
        reservation.connectionId = UUID(retdict["connectionId"])  # TODO: make nsi_comm return a UUID


def nsi_send_reserve_commit_job(reservation_id: int) -> None:
    new_correlation_id_on_reservation(reservation_id)
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
    retdict = nsi_send_reserve_commit(reservation)  # TODO: need error handling on failed post soap


def nsi_send_provision_job(reservation_id: int) -> None:
    new_correlation_id_on_reservation(reservation_id)
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
    retdict = nsi_send_provision(reservation)  # TODO: need error handling on failed post soap


def gui_terminate_connection_job(reservation_id: int) -> None:
    new_correlation_id_on_reservation(reservation_id)
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
    log = logger.bind(
        module=__name__,
        job=nsi_send_provision.__name__,
        reservationId=reservation.id,
        correlationId=str(reservation.correlationId),
        connectionId=str(reservation.connectionId),
    )
    log.info("send terminate")
    reply_dict = nsi_send_terminate(reservation)  # TODO: need error handling on failed post soap
    if "Fault" in reply_dict["Body"]:
        se = reply_dict["Body"]["Fault"]["detail"]["serviceException"]
        log.warning("send terminate failed", nsaId=se["nsaId"], errorId=se["errorId"], text=se["text"])
    else:
        log.info("send terminate successful")
