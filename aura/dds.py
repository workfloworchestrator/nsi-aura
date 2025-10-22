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

import base64
import zlib

import structlog
from pydantic import HttpUrl

from aura.db import Session
from aura.model import SDP, STP
from aura.nsi import nsi_util_get_xml, nsi_util_xml_to_dict

logger = structlog.get_logger(__name__)


DISCOVERY_MIME_TYPE = "vnd.ogf.nsi.nsa.v1+xml"
TOPOLOGY_MIME_TYPE = "vnd.ogf.nsi.topology.v2+xml"

HAS_INBOUND_PORT = "http://schemas.ogf.org/nml/2013/05/base#hasInboundPort"
HAS_OUTBOUND_PORT = "http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort"
IS_ALIAS = "http://schemas.ogf.org/nml/2013/05/base#isAlias"


def strip_urn(urn: str) -> str:
    return urn.replace("urn:ogf:network:", "")


def to_dict(index: str, collection: dict) -> dict:
    return {element[index]: element for element in collection}


def to_list(index: str, collection: dict) -> list:
    return [element[index] for element in collection]


def topology_to_stps(topology: dict) -> list[STP]:
    """Parse dict representation of NSI topology document and return the lists of STP."""
    log = logger.bind(topology=topology["id"])

    try:
        bidirectionalPorts = to_dict("id", topology["BidirectionalPort"])
        relations = to_dict("type", topology["Relation"])
        inboundPorts = to_dict("id", relations[HAS_INBOUND_PORT]["PortGroup"])
        outboundPorts = to_dict("id", relations[HAS_OUTBOUND_PORT]["PortGroup"])
    except KeyError as e:
        log.warning("cannot parse topology", error=f"cannot find {str(e)} in topology")
        return []

    stps = []
    for bidirectionalPortId in bidirectionalPorts:
        inboundPort: dict | None = None
        outboundPort: dict | None = None
        for unidirectionalPortId in to_list("id", bidirectionalPorts[bidirectionalPortId]["PortGroup"]):
            if unidirectionalPortId in inboundPorts:
                inboundPort = inboundPorts[unidirectionalPortId]
            elif unidirectionalPortId in outboundPorts:
                outboundPort = outboundPorts[unidirectionalPortId]
            else:
                log.warning(f"unidirectional port {unidirectionalPortId} not found")
        inboundPortId: str | None = None
        outboundPortId: str | None = None
        inboundAliasId: str | None = None
        outboundAliasId: str | None = None
        if inboundPort and outboundPort:
            if inboundPort["LabelGroup"] != outboundPort["LabelGroup"]:
                log.warning(f"LabelGroups on in- and outbound ports of {bidirectionalPortId} do not match")
            # the following breaks when the port has multiple relations, then Relation will be a list instead of a dict
            if "Relation" in inboundPort and inboundPort["Relation"]["type"] == IS_ALIAS:
                inboundPortId = strip_urn(inboundPort["id"])
                inboundAliasId = strip_urn(inboundPort["Relation"]["PortGroup"]["id"])
            if "Relation" in outboundPort and outboundPort["Relation"]["type"] == IS_ALIAS:
                outboundPortId = strip_urn(outboundPort["id"])
                outboundAliasId = strip_urn(outboundPort["Relation"]["PortGroup"]["id"])
        stps.append(
            STP(
                stpId=strip_urn(bidirectionalPortId),
                inboundPort=inboundPortId,
                outboundPort=outboundPortId,
                inboundAlias=inboundAliasId,
                outboundAlias=outboundAliasId,
                vlanRange=inboundPort["LabelGroup"] if inboundPort else "",
                description=bidirectionalPorts[bidirectionalPortId]["name"],
            )
        )
        log.debug(f"found STP {bidirectionalPortId}: {stps[-1]}")
    return stps


def update_stps(stps: list[STP]) -> None:
    """Update STP table with topology information from DDS."""
    for new_stp in stps:
        log = logger.bind(
            stpId=new_stp.stpId,
            inboundPort=new_stp.inboundPort,
            outboundPort=new_stp.outboundPort,
            inboundAlias=new_stp.inboundAlias,
            outboundAlias=new_stp.outboundAlias,
            vlanRange=new_stp.vlanRange,
            description=new_stp.description,
        )
        with Session.begin() as session:
            existing_stp = session.query(STP).filter(STP.stpId == new_stp.stpId).one_or_none()  # type: ignore[arg-type]
            if existing_stp is None:
                log.info("add new STP")
                session.add(new_stp)
            elif (
                existing_stp.inboundPort != new_stp.inboundPort
                or existing_stp.outboundPort != new_stp.outboundPort
                or existing_stp.inboundAlias != new_stp.inboundAlias
                or existing_stp.outboundAlias != new_stp.outboundAlias
                or existing_stp.vlanRange != new_stp.vlanRange
                or existing_stp.description != new_stp.description
            ):
                log.info("update existing STP")
                existing_stp.inboundPort = new_stp.inboundPort
                existing_stp.outboundPort = new_stp.outboundPort
                existing_stp.inboundAlias = new_stp.inboundAlias
                existing_stp.outboundAlias = new_stp.outboundAlias
                existing_stp.vlanRange = new_stp.vlanRange
                existing_stp.description = new_stp.description
            else:
                log.debug("STP did not change")
    # TODO: implement disabling vanished STP


def has_alias(stp: STP) -> bool:
    return stp.inboundAlias is not None and stp.outboundAlias is not None


def update_sdps() -> None:
    """Update SDP table."""

    def is_sdp(a: STP, z: STP) -> bool:
        return (
            has_alias(a)
            and has_alias(z)
            and a.inboundAlias == z.outboundPort
            and a.outboundAlias == z.inboundPort
            and z.inboundAlias == a.outboundPort
            and z.outboundAlias == a.inboundPort
        )

    with Session() as session:
        stps = session.query(STP).all()
    # find connected STPs
    sdps = []
    for a in stps:
        for z in stps:
            if is_sdp(a, z):
                sdps.append((a, z))
                stps.remove(z)  # remove STP at other side of SDP as candidate
    # process found SDPs
    for stp_a, stp_z in sdps:
        description = f"{stp_a.description} <-> {stp_z.description}"
        log = logger.bind(
            stpAId=stp_a.stpId,
            stpZId=stp_z.stpId,
            vlanRange=stp_a.vlanRange,  # TODO: should store a and z overlapping range only
            description=description,
        )
        with Session.begin() as session:
            existing_sdp = session.query(SDP).filter((SDP.stpAId == stp_a.id) & (SDP.stpZId == stp_z.id)).one_or_none()  # type: ignore[arg-type]
            if existing_sdp is None:
                log.info("add new SDP")
                session.add(
                    SDP(
                        stpAId=stp_a.id,
                        stpZId=stp_z.id,
                        vlanRange=stp_a.vlanRange,  # TODO: should store a and z overlapping range only
                        description=description,
                    )
                )
            elif existing_sdp.vlanRange != stp_a.vlanRange or existing_sdp.description != description:
                log.info("update existing SDP")
                existing_sdp.vlanRange = stp_a.vlanRange  # TODO: should store a and z overlapping range only
                existing_sdp.description = description
            else:
                log.debug("SDP did not change")
    # TODO: implement disabling vanished SDP


def unzip(document: dict) -> bytes:
    """Unzip document content to bytes."""
    return zlib.decompress(base64.b64decode(document["content"]), 16 + zlib.MAX_WBITS)


def get_dds_documents(url: HttpUrl) -> dict[str, dict[str, bytes]]:
    """Retreive all documents from url and return them by type and id.

    Example:
    {'vnd.ogf.nsi.topology.v2+xml': {'urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy': b'<ns3:Topology> ...',
                                     'urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf': b'<ns3:Topology> ...',
    'vnd.ogf.nsi.nsa.v1+xml': {'urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:nsa:supa': b'<ns3:nsa ...',
                               'urn:ogf:network:ana.dlp.surfnet.nl:2024:nsa:safnari': b'<ns3:nsa ...',
                               'urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:nsa:supa': b'<ns3:nsa ...'}}

    """
    documents: dict[str, dict[str, bytes]] = {TOPOLOGY_MIME_TYPE: {}, DISCOVERY_MIME_TYPE: {}}

    xml = nsi_util_get_xml(url)  # TODO: catch Exception
    if xml:
        dds = nsi_util_xml_to_dict(xml)
        if isinstance(dds["documents"]["document"], list):
            for document in dds["documents"]["document"]:
                documents[document["type"]][document["id"]] = unzip(document)
        else:
            documents[document["type"]][document["id"]] = unzip(document := dds["documents"]["document"])

    return documents


# for debugging purposes
if __name__ == "__main__":
    example = {
        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy",
        "version": "2025-03-19T07:38:58Z",
        "name": "ANA MOXY topology",
        "Lifetime": {"start": "2025-03-19T07:38:58Z", "end": "2025-03-26T07:38:58Z"},
        "BidirectionalPort": [
            {
                "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1",
                "name": "High Performance Cluster in Canada",
                "PortGroup": [
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1:in"},
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1:out"},
                ],
            },
            {
                "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1",
                "name": "Research institute in Canada",
                "PortGroup": [
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1:in"},
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1:out"},
                ],
            },
            {
                "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1",
                "name": "ANA link 1 MOXY towards SURF",
                "PortGroup": [
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:in"},
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:out"},
                ],
            },
            {
                "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2",
                "name": "ANA link 2 MOXY towards SURF",
                "PortGroup": [
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2:in"},
                    {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2:out"},
                ],
            },
        ],
        "serviceDefinition": {
            "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:sd:EVTS.A-GOLE",
            "name": "GLIF Automated GOLE Ethernet VLAN Transfer Service",
            "serviceType": "http://services.ogf.org/nsi/2013/12/descriptions/EVTS.A-GOLE",
        },
        "Relation": [
            {
                "type": "http://schemas.ogf.org/nml/2013/05/base#hasService",
                "SwitchingService": {
                    "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                    "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:switch:EVTS.A-GOLE",
                    "labelSwapping": "true",
                    "labelType": "http://schemas.ogf.org/nml/2012/10/ethernet#vlan",
                    "Relation": [
                        {
                            "type": "http://schemas.ogf.org/nml/2013/05/base#hasInboundPort",
                            "PortGroup": [
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1:in"},
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1:in"},
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:in"},
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2:in"},
                            ],
                        },
                        {
                            "type": "http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort",
                            "PortGroup": [
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1:out"},
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1:out"},
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:out"},
                                {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2:out"},
                            ],
                        },
                    ],
                    "serviceDefinition": {"id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:sd:EVTS.A-GOLE"},
                },
            },
            {
                "type": "http://schemas.ogf.org/nml/2013/05/base#hasInboundPort",
                "PortGroup": [
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1:in",
                        "LabelGroup": "3762-3769",
                        "capacity": "10000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "10000000000",
                    },
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1:in",
                        "LabelGroup": "147",
                        "capacity": "10000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "10000000000",
                    },
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:in",
                        "LabelGroup": "1330-1429",
                        "Relation": {
                            "type": "http://schemas.ogf.org/nml/2013/05/base#isAlias",
                            "PortGroup": {"id": "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-1:out"},
                        },
                        "capacity": "100000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "100000000000",
                    },
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2:in",
                        "LabelGroup": "88-97",
                        "Relation": {
                            "type": "http://schemas.ogf.org/nml/2013/05/base#isAlias",
                            "PortGroup": {"id": "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-2:out"},
                        },
                        "capacity": "100000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "100000000000",
                    },
                ],
            },
            {
                "type": "http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort",
                "PortGroup": [
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1:out",
                        "LabelGroup": "3762-3769",
                        "capacity": "10000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "10000000000",
                    },
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1:out",
                        "LabelGroup": "147",
                        "capacity": "10000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "10000000000",
                    },
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:out",
                        "LabelGroup": "1330-1429",
                        "Relation": {
                            "type": "http://schemas.ogf.org/nml/2013/05/base#isAlias",
                            "PortGroup": {"id": "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-1:in"},
                        },
                        "capacity": "100000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "100000000000",
                    },
                    {
                        "encoding": "http://schemas.ogf.org/nml/2012/10/ethernet",
                        "id": "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2:out",
                        "LabelGroup": "88-97",
                        "Relation": {
                            "type": "http://schemas.ogf.org/nml/2013/05/base#isAlias",
                            "PortGroup": {"id": "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-2:in"},
                        },
                        "capacity": "100000000000",
                        "granularity": "1000000",
                        "minimumReservableCapacity": "1000000",
                        "maximumReservableCapacity": "100000000000",
                    },
                ],
            },
        ],
    }
    stps = topology_to_stps(example)
    logger.debug(stps)
