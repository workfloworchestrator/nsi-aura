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


from apscheduler.schedulers.background import BackgroundScheduler
from pytz import utc

from aura.models import Reservation
from aura.nsi_comm import nsi_send_provision, nsi_send_reserve, nsi_send_reserve_commit

# Advanced Python Scheduler
# scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop(), timezone=utc)
scheduler = BackgroundScheduler(timezone=utc)
scheduler.start()


def nsi_send_reserve_job(reservation_id: int) -> None:
    from aura.db import Session

    retdict = nsi_send_reserve(reservation_id)  # TODO: need error handling post soap failure
    with Session.begin() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()
        reservation.connectionId = retdict["connectionId"]


def nsi_send_reserve_commit_job(reservation_id: int) -> None:
    retdict = nsi_send_reserve_commit(reservation_id)  # TODO: need error handling on failed post soap


def nsi_send_provision_job(reservation_id: int) -> None:
    retdict = nsi_send_provision(reservation_id)  # TODO: need error handling on failed post soap
