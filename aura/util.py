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
from sqlalchemy import Select, select

from aura.db import Session
from aura.fsm import ConnectionStateMachine
from aura.model import STP, Reservation
from aura.vlan import VlanRanges

logger = structlog.get_logger()


def update_service_termination_points_from_dds(stps: dict[str : dict[str, str]]) -> None:
    """Update ServiceTerminationPoint table with topology information from DDS."""
    with Session.begin() as session:
        for stp in stps.keys():
            stpId = stp.replace("urn:ogf:network:", "")
            log = logger.bind(
                stpId=stpId,
                vlanRange=stps[stp]["vlanranges"],
                description=stps[stp]["name"],
            )
            existing_stp = session.query(STP).filter(STP.stpId == stpId).one_or_none()
            if existing_stp is None:
                log.info("add new STP")
                session.add(
                    STP(
                        stpId=stpId,
                        vlanRange=stps[stp]["vlanranges"],
                        description=stps[stp]["name"],
                    )
                )
            elif existing_stp.vlanRange != stps[stp]["vlanranges"] or existing_stp.description != stps[stp]["name"]:
                log.info("update existing STP")
                existing_stp.vlanRange = stps[stp]["vlanranges"]
                existing_stp.description = stps[stp]["name"]
            else:
                log.debug("STP did not change")


def vlan_ranges(stpId: int) -> VlanRanges:
    """All VLAN ranges on STP identified by stpId."""
    with Session() as session:
        return VlanRanges(session.query(STP.vlanRange).filter(STP.id == stpId).scalar())


def in_use_vlan_ranges(select_statement: Select) -> list[int]:
    """Already in use VLAN ranges on STP identified by stpId."""
    with Session() as session:
        return (
            session.execute(select_statement.filter(Reservation.state.in_(ConnectionStateMachine.active_state_values)))
            .scalars()
            .all()
        )


def free_vlan_ranges(stpId: int) -> VlanRanges:
    """Free VLAN ranges on STP identified by stpId."""
    free_vlan_ranges = vlan_ranges(stpId)
    with Session() as session:
        for vlan in (
            in_use_vlan_ranges(select(Reservation.sourceVlan).filter(Reservation.sourceStpId == stpId))  # fmt: skip
            + in_use_vlan_ranges(select(Reservation.destVlan).filter(Reservation.destStpId == stpId))
        ):
            free_vlan_ranges = free_vlan_ranges - vlan if vlan in free_vlan_ranges else free_vlan_ranges
    return free_vlan_ranges
