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

import structlog

from aura.db import Session
from aura.model import STP

logger = structlog.get_logger(__name__)


def update_service_termination_points_from_dds(stps: dict[str : dict[str, str]]) -> None:
    """Update ServiceTerminationPoint table with topology information from DDS."""
    with Session.begin() as session:
        for stp in stps.keys():
            _, _, _, fqdn, date, *opaque_part = stp.split(":")
            organisationId = fqdn + ":" + date
            networkId = ":".join(opaque_part[:-1])
            localId = opaque_part[-1]
            log = logger.bind(
                organisationId=organisationId,
                networkId=networkId,
                localId=localId,
                vlanRange=stps[stp]["vlanranges"],
                description=stps[stp]["name"],
            )
            existing_stp = (
                session.query(STP)
                .filter(
                    STP.organisationId == organisationId,
                    STP.networkId == networkId,
                    STP.localId == localId,
                )
                .one_or_none()
            )
            if existing_stp is None:
                log.info("add new STP")
                session.add(
                    STP(
                        organisationId=organisationId,
                        networkId=networkId,
                        localId=localId,
                        vlanRange=stps[stp]["vlanranges"],
                        description=stps[stp]["name"],
                    )
                )
            else:
                log.info("update existing STP")
                existing_stp.vlanRange = stps[stp]["vlanranges"]
                existing_stp.description = stps[stp]["name"]
