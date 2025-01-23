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

#
# NSI-AuRA = NSI ANA ultimate Requester Agent
# ===========================================
# @author: Arno Bakker
#
# CSS can be controlled via class_name attribute and
# https://getbootstrap.com/docs/4.5/utilities/colors/ definitions
#
# TODO:
# - Concurrency control on the Model data: endpoints, links, reservations
#   * This includes changing URLs to use absolute endpoint and link identifiers, so really RESTful
# - Export HTTP exceptions to fastUI level, so they can be signalled to user.
# - Security for NOC access, see /login /logout already below.
# - Global Reservation Id in Reserve message is apparently unique to uPA, Orchestrator/Safnari barfs.
# - footer is separate construct?
#

import asyncio
import datetime
import os
import secrets
import threading
import traceback
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui import prebuilt_html
from fastui.components.display import DisplayLookup
from fastui.events import BackEvent, GoToEvent
from pydantic import BaseModel

# pydantic suckx
c.Link.model_rebuild()


import logging

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.DEBUG)


ONLINE = True


#
# Own code
#
from nsi_comm import *

#
# Constants
#

SITE_TITLE = "AuRA - NSI uRA for Federating ANA"
# SITE_TITLE = 'AuRA - NSI ultimate Requester Agent for ANA'

#
# NSI Orchestrator
#
# GLOBAL_ORCHESTRATOR_URL='https://supa.moxy.ana.dlp.surfnet.nl:443'
## Test with bad URL
# GLOBAL_ORCHESTRATOR_URL='https://nosupa.moxy.ana.dlp.surfnet.nl'
# GLOBAL_ORCHESTRATOR_DISCOVERY_PATH='/discovery'

# DEMO_PROVIDER_NSA_ID='urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:nsa:supa'


ANAGRAM_DDS_URL = "https://dds.ana.dlp.surfnet.nl/dds/"

UPA_URN_PREFIX = "urn:ogf:network:"

DEFAULT_LINK_DOMAIN = "ANA"


# AuRA
# apparently cannot dynamically figure out?
SERVER_URL_PREFIX = "http://127.0.0.1:8000"
# SERVER_URL_PREFIX="http://145.100.104.178:8000"


#
# Used in polling and callbacks
#
FASTAPI_MSGNAME_RESERVE = "reserve"
FASTAPI_MSGNAME_QUERY_RECURSIVE = "queryRecursive"

# fake not ONLINE data
sample_qr_cbpath = os.path.join("samples", "query-recursive-callback-example3.xml")


#
# Security: Session cookies as per
#
#     https://gist.github.com/rochacbruno/3b8dbb79b2b6c54486c396773fdde532
#
#
from fastapi import Depends, Request, Response
from fastapi.responses import RedirectResponse

# This must be randomly generated
RANDON_SESSION_ID = "see below"

# This must be a lookup on user database
USER_CORRECT = ("arno", "tshirtdeal")

# This must be Redis, Memcached, SQLite, KV, etc...
SESSION_DB = {}


def create_and_record_sessionid(username):
    # Arno
    sessionid_b64str = secrets.token_urlsafe(16)
    SESSION_DB[sessionid_b64str] = username
    return sessionid_b64str


def get_auth_user(request: Request):
    """Verify that user has a valid session"""
    session_id = request.cookies.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authorized to use AuRA, please login")
    if session_id not in SESSION_DB:
        raise HTTPException(status_code=403, detail="Please login to use AuRA")
    return True


#
# Global variables
#

#
# Producer/Consumer type interaction between GUI and Orchestrator async callbacks
# TODO: won't work with multi-process fastAPI application
#
global_orch_async_replies_lock = threading.Lock()
global_orch_async_replies_dict = {}  # indexed on CorrelationId


#
# Models
#


#
# Endpoint
# --------
# TODO: CONCURRENCY: add absolute identifier such that those can be used in URLs instead of Model id's
# which may change during a reload of topos
#
class Endpoint(BaseModel):
    id: int
    name: str
    svlanid: int  # start VLAN ID, hack for tuple
    evlanid: int  # end VLAN ID, hack for tuple. If same, then qualified STP
    domain: str  # domain for this endpoint


# define some endpoints
global_endpoints = [
    Endpoint(id=1, name="moxy-cie-01_eth0", svlanid=190, evlanid=190, domain="CANARIE"),
    Endpoint(id=2, name="esnet-csc-01_eth1", svlanid=293, evlanid=293, domain="ESnet"),
    Endpoint(id=3, name="paris-nok-06_eth2", svlanid=391, evlanid=391, domain="Geant"),
    Endpoint(id=4, name="manlan-ari-05_eth3", svlanid=492, evlanid=492, domain="Internet2"),
    Endpoint(id=5, name="seoul-jnx-06_eth4", svlanid=591, evlanid=591, domain="KREONET"),
    Endpoint(id=6, name="nea3r-nok-01_eth5", svlanid=692, evlanid=692, domain="NEA3R"),
    Endpoint(id=7, name="noma-nok-06_eth7", svlanid=791, evlanid=791, domain="NORDUnet"),
    Endpoint(id=8, name="sinet-nok-06_eth8", svlanid=891, evlanid=891, domain="Sinet"),
    Endpoint(id=9, name="nlight-jnx-06_eth9", svlanid=991, evlanid=991, domain="SURF"),
]


# On some installs we get confusion between Link(DataModel) and the Link HTML component
class NetworkLink(BaseModel):
    id: int
    name: str
    linkid: int
    svlanid: int  # start VLAN ID, hack for tuple
    evlanid: int  # end VLAN ID, hack for tuple. If same, then qualified STP
    domain: str  # domain for this endpoint


# define some ANA links
global_links = [
    NetworkLink(
        id=1, name="MOXY EXA Atlantic North 100G", linkid=31, svlanid=190, evlanid=190, domain=DEFAULT_LINK_DOMAIN
    ),
    NetworkLink(
        id=2, name="Tata TGN-Atlantic South 100G", linkid=32, svlanid=190, evlanid=190, domain=DEFAULT_LINK_DOMAIN
    ),
    NetworkLink(
        id=3, name="AquaComms AEC-1 South 100G", linkid=33, svlanid=190, evlanid=190, domain=DEFAULT_LINK_DOMAIN
    ),
    NetworkLink(id=3, name="EXA Express 100G", linkid=34, svlanid=190, evlanid=190, domain=DEFAULT_LINK_DOMAIN),
    NetworkLink(id=5, name="Amitie 400G", linkid=35, svlanid=190, evlanid=190, domain=DEFAULT_LINK_DOMAIN),
]


class Reservation(BaseModel):
    id: int
    connectionId: str
    description: str
    startTime: str
    endTime: str
    sourceSTP: str
    destSTP: str
    requesterNSA: str
    reservationState: str
    lifecycleState: str
    dataPlaneStatus: str  # HACKED into value of <active>


# 1 dummy reservation
DUMMY_CONNECTION_ID_STR = "d940e5b1-ed22-4c1a-ae09-10f20e4bd267"
DUMMY_GLOBAL_RESERVATION_ID_STR = "urn:uuid:c46b7412-2263-46c6-b497-54f52e9f9ff4"
DUMMY_CORRELATION_ID_STR = "urn:uuid:a3eb6740-7227-473b-af6f-6705d489407c"  # TODO URN?

global_reservations = [
    Reservation(
        id=1,
        connectionId=DUMMY_CONNECTION_ID_STR,
        description="Dummy reservation",
        startTime="2024-11-07T15:53:32+00:00",
        endTime="2024-11-07T15:53:36+00:00",
        sourceSTP="asd001b-jnx-06_eth0",
        destSTP="mon001a-nok-01_eth1",
        requesterNSA="urn:ogf:network:anaeng.global:2024:nsa:nsi-aura",
        reservationState="ReserveHeld",
        lifecycleState="Created",
        dataPlaneStatus="true",
    ),
]


#
# Span i.e. a Connection i,e., two STPs that are connected, e.g. for showing a path
#


class Span(BaseModel):
    id: int
    connectionId: str  # connectionId UUID
    sourceSTP: str  # source STP URN
    destSTP: str  # dest STP URN


#
# Discovery, i.e. NSI meta data information on a uPA such as version and expires
#
class Discovery(BaseModel):
    id: int
    agentid: str  # 'urn:ogf:network:ana.dlp.surfnet.nl:2024:nsa:safnari',
    version: str  # '2024-11-27T15:07:21.050548388Z',
    expires: str  # '2025-11-27T15:07:24.229Z'},
    # 'services': {'application/vnd.ogf.nsi.dds.v1+xml': 'https://dds.ana.dlp.surfnet.nl/dds', 'application/vnd.ogf.nsi.cs.v2.requester+soap': 'https://safnari.ana.dlp.surfnet.nl/nsi-v2/ConnectionServiceRequester', 'application/vnd.ogf.nsi.cs.v2.provider+soap': 'https://safnari.ana.dlp.surfnet.nl/nsi-v2/ConnectionServiceProvider'}}


def discoverydict2model(disccount, disc_metadata_dict):

    disc_dict = disc_metadata_dict["metadata"]
    print("DISC2DATAMODEL:", disc_dict)

    agentid = disc_dict["id"]
    version = disc_dict["version"]
    expires = disc_dict["expires"]
    return Discovery(id=disccount, agentid=agentid, version=version, expires=expires)


#
# SOAP templating
#


def nsi_load_dds_documents():
    """Contact hard-coded DDS for ANA to discovery
    a. who is the Orchestrator
    b. discovery and topology information for all connected NSI uPAs

    Retrieves DDS info, and loads into data Models
    Also sets
    - global_provider_nsa_id
    - global_soap_provider_url
    returns dds_documents_dict for displaying summaries to the user
    """
    dds_documents_dict = nsi_get_dds_documents(ANAGRAM_DDS_URL)

    global global_provider_nsa_id
    global global_soap_provider_url

    # DDS knows all, so also who is our Orchestrator/Safnari
    orchestrator_dict = dds_documents_dict["local"]
    global_provider_nsa_id = orchestrator_dict["metadata"]["id"]
    global_soap_provider_url = orchestrator_dict["services"][SOAP_PROVIDER_MIME_TYPE]

    print("nsi_load_dds_documents: Found Aggregator ID", global_provider_nsa_id)
    print("nsi_load_dds_documents: Found Aggregator SOAP", global_soap_provider_url)

    worldwide_stps = {}
    worldwide_sdp_list = []
    documents = dds_documents_dict["documents"]
    for upa_id in documents.keys():
        print("nsi_load_dds_documents: Found uPA", upa_id)

        # Load topologies, compose list of STPs (aka Endpoints) and SDPs (aka Links)
        document = documents[upa_id]
        topo_dict = document["topology"]
        stps = topo_dict["stps"]
        sdps = topo_dict["sdps"]

        print("nsi_load_dds_documents: Adding STPs", len(stps), stps)
        print("nsi_load_dds_documents: Adding SDPs", len(sdps), sdps)

        worldwide_stps.update(stps)

        # TODO: merge, so check for duplicates
        worldwide_sdp_list += sdps  # append

    # Load new data into Datamodel
    nsi_reload_topology_into_endpoints_model(worldwide_stps)
    nsi_reload_topology_into_links_model(worldwide_sdp_list)

    global ONLINE
    ONLINE = True
    return dds_documents_dict


def nsi_reload_topology_into_endpoints_model(stps):
    """Updates global DataModel endpoints to contain the given list of STPs
    Returns nothing
    """
    global global_endpoints
    global_endpoints = stps2endpoints(stps)


def parse_vlan_range(vlanstr):
    """Takes a VLAN spec with either a single VLAN or range and converts it to
    (start VLAN id,end VLAN id)
    """
    idx = vlanstr.find("-")
    if idx == -1:
        # Qualified STP, just one vlan ID
        svlanid = int(vlanstr)
        evlanid = svlanid
    else:
        vlanstrings = vlanstr.split("-")
        svlanid = int(vlanstrings[0])
        evlanid = int(vlanstrings[1])
    return (svlanid, evlanid)


def stpid2domain(stpid):
    """Abbreviates STP id to a simple domain name for display purposes"""
    urn = stpid
    nopref = urn[len(UPA_URN_PREFIX) :]
    idx = nopref.find(":")
    domain = nopref[:idx]
    return domain


def add_endpoint(id, stpid, svlanid, evlanid, domain, local_endpoints):
    endpoint = Endpoint(id=id, name=stpid, svlanid=svlanid, evlanid=evlanid, domain=domain)
    # Put in list
    local_endpoints.append(endpoint)


def stps2endpoints(stps):
    """Take downloaded STPs and put into a DataModel Endpoints list
    Returns list
    """
    local_endpoints = []
    bidiports = stps

    print("nsi_reload_topology_into_endpoints_model: Loading STPs", bidiports)
    if bidiports is None:
        return local_endpoints

    endpointcount = 1

    for stpid in bidiports.keys():

        domain = stpid2domain(stpid)
        vlanstr = bidiports[stpid]["vlanranges"]  # can be int-int,int-int

        idx = vlanstr.find(",")
        if idx == -1:
            # Single int or range
            (svlanid, evlanid) = parse_vlan_range(vlanstr)
            add_endpoint(endpointcount, stpid, svlanid, evlanid, domain, local_endpoints)
            endpointcount += 1
        else:
            ranges = vlanstr.split(",")
            for r in ranges:
                (svlanid, evlanid) = parse_vlan_range(r)
                add_endpoint(endpointcount, stpid, svlanid, evlanid, domain, local_endpoints)
                endpointcount += 1
    return local_endpoints


def sdp2name(inport, outport):
    # Assuming urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-1:in is a standard
    # format, at least the beginning until 2024:
    inwords = inport.split(":")
    outwords = outport.split(":")
    name = inwords[5] + ":" + inwords[6] + "--" + outwords[5] + ":" + outwords[6]
    return name


def sdp2comp(d):
    """Return a copy of an SDP with :in and :out removed from the port identifiers"""
    d2 = copy.deepcopy(d)
    inport_id = d2["inport"]
    outport_id = d2["outport"]
    ibidiport_id = inport_id[: -len(INPORT_IN_POSTFIX)]
    obidiport_id = outport_id[: -len(OUTPORT_OUT_POSTFIX)]
    d2["inport"] = ibidiport_id
    d2["outport"] = obidiport_id
    return d2


## ChatGPT + Arno
import json


def sdp_remove_duplicates(dict_list):
    seen = set()
    unique_dicts = []

    for d in dict_list:
        d2 = sdp2comp(d)

        # Also test if the symmetric version is not already in seen
        sd = copy.deepcopy(d2)
        tempport = sd["inport"]
        sd["inport"] = sd["outport"]
        sd["outport"] = tempport
        # Convert dictionary to a JSON string to check for uniqueness
        dict_str = json.dumps(d2, sort_keys=True)
        sdict_str = json.dumps(sd, sort_keys=True)

        print("sdp_remove_duplicates: COMP", dict_str, sdict_str)

        if dict_str not in seen and sdict_str not in seen:
            seen.add(dict_str)
            unique_dicts.append(d)

    return unique_dicts


def add_link(id, linkid, name, svlanid, evlanid, domain):
    link = NetworkLink(id=id, linkid=linkid, name=name, svlanid=svlanid, evlanid=evlanid, domain=domain)
    # Put in list
    global global_links
    global_links.append(link)


def nsi_reload_topology_into_links_model(sdps):
    """Take downloaded STPs and put into Endpoints
    Returns nothing
    """
    global links

    print("nsi_reload_topology_into_links_model: Loading SDPs", sdps)
    if sdps is None or len(sdps) == 0:
        return

    unique_sdps = sdp_remove_duplicates(sdps)

    print("nsi_reload_topology_into_links_model: Loading unique SDPs", sdps)

    #
    # Override default links
    #
    linkcount = 1
    global global_links
    global_links = []

    for sdp in unique_sdps:
        name = sdp2name(sdp["inport"], sdp["outport"])
        domain = DEFAULT_LINK_DOMAIN
        vlanstr = sdp["vlanranges"]  # can be int-int,int-int

        idx = vlanstr.find(",")
        if idx == -1:
            # Single int or range
            (svlanid, evlanid) = parse_vlan_range(vlanstr)
            add_link(linkcount, linkcount, name, svlanid, evlanid, domain)
            linkcount += 1
        else:
            ranges = vlanstr.split(",")
            for r in ranges:
                (svlanid, evlanid) = parse_vlan_range(r)
                add_link(linkcount, linkcount, name, svlanid, evlanid, domain)
                linkcount += 1


def nsi_load_parsed_soap_into_reservations_model(resdictlist):
    """Turn downloaded reservations into Model   #TODO: refactor to match nsi_load_topo or something
    Returns nothing
    """
    global global_reservations

    #
    # Override default global_reservations
    #
    global_reservations = []

    for connid in resdictlist.keys():
        reserve_dict = resdictlist[connid]

        if (
            reserve_dict[S_RESERVATION_STATE_TAG] == NSI_RESERVATION_FAILED_STATE
            or reserve_dict[S_RESERVATION_STATE_TAG] == NSI_RESERVATION_TIMEOUT_STATE
        ):
            # Some fields missing, such as startTime
            reserve_dict[S_STARTTIME_TAG] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            reserve_dict[S_ENDTIME_TAG] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            reserve_dict[S_SOURCE_STP_TAG] = "n/a"
            reserve_dict[S_DEST_STP_TAG] = "n/a"
            reservation = Reservation(
                id=reserve_dict[FASTUID_ID_KEY],
                connectionId=connid,
                description=reserve_dict[S_DESCRIPTION_TAG],
                startTime=reserve_dict[S_STARTTIME_TAG],
                endTime=reserve_dict[S_ENDTIME_TAG],
                sourceSTP=reserve_dict[S_SOURCE_STP_TAG],
                destSTP=reserve_dict[S_DEST_STP_TAG],
                requesterNSA=reserve_dict[S_REQUESTER_NSA_TAG],
                reservationState=reserve_dict[S_RESERVATION_STATE_TAG],
                lifecycleState=reserve_dict[S_LIFECYCLE_STATE_TAG],
                dataPlaneStatus=reserve_dict[S_DATAPLANE_STATUS_TAG],
            )
        else:
            reservation = Reservation(
                id=reserve_dict[FASTUID_ID_KEY],
                connectionId=connid,
                description=reserve_dict[S_DESCRIPTION_TAG],
                startTime=reserve_dict[S_STARTTIME_TAG],
                endTime=reserve_dict[S_ENDTIME_TAG],
                sourceSTP=reserve_dict[S_SOURCE_STP_TAG],
                destSTP=reserve_dict[S_DEST_STP_TAG],
                requesterNSA=reserve_dict[S_REQUESTER_NSA_TAG],
                reservationState=reserve_dict[S_RESERVATION_STATE_TAG],
                lifecycleState=reserve_dict[S_LIFECYCLE_STATE_TAG],
                dataPlaneStatus=reserve_dict[S_DATAPLANE_STATUS_TAG],
            )

        # Put in list
        global_reservations.append(reservation)


#
# MAIN
#


app = FastAPI()

# make sure you have a folder named 'static' in your project and put the css and js files inside a subfolder called 'assets'
app.mount("/static", StaticFiles(directory="static"), name="static")


#
# NSI COMM
#
nsi_comm_init(("arno-perscert-pub-2024.crt", "DO-NOT-COMMIT-arno-priv-2024.pem"))


try:
    # DEMO: Turn topology loading off for now, so we can also demo with synthetic data,
    # which may be more comprehensible
    ONLINE = False
    # nsi_load_dds_documents()
except:
    traceback.print_exc()
    ONLINE = False

#
# Load SOAP templates
#

# RESERVE
reserve_templpath = os.path.join(os.getcwd(), "static", NSI_RESERVE_TEMPLATE_XMLFILE)

# Read Reserve template code
with open(reserve_templpath) as reserve_templfile:
    reserve_templstr = reserve_templfile.read()
reserve_templfile.close()

# RESERVE-COMMIT
reserve_commit_templpath = os.path.join(os.getcwd(), "static", NSI_RESERVE_COMMIT_TEMPLATE_XMLFILE)

# Read Reserve Commit template code
with open(reserve_commit_templpath) as reserve_commit_templfile:
    reserve_commit_templstr = reserve_commit_templfile.read()
reserve_commit_templfile.close()


# PROVISION
provision_templpath = os.path.join(os.getcwd(), "static", NSI_PROVISION_TEMPLATE_XMLFILE)

# Read Reserve template code
with open(provision_templpath) as provision_templfile:
    provision_templstr = provision_templfile.read()
provision_templfile.close()


# QUERY SUMMARY SYNC
query_summary_sync_templpath = os.path.join(os.getcwd(), "static", NSI_QUERY_SUMMARY_SYNC_TEMPLATE_XMLFILE)

# Read Reserve template code
with open(query_summary_sync_templpath) as query_summary_sync_templfile:
    query_summary_sync_templstr = query_summary_sync_templfile.read()
query_summary_sync_templfile.close()

# QUERY RECURSIVE to get path details
query_recursive_templpath = os.path.join(os.getcwd(), "static", NSI_QUERY_RECURSIVE_TEMPLATE_XMLFILE)

# Read RESERVE_TIMEOUT_ACK template code
with open(query_recursive_templpath) as query_recursive_templfile:
    query_recursive_templstr = query_recursive_templfile.read()
query_recursive_templfile.close()


# TERMINATE
terminate_templpath = os.path.join(os.getcwd(), "static", NSI_TERMINATE_TEMPLATE_XMLFILE)

# Read TERMINATE template code
with open(terminate_templpath) as terminate_templfile:
    terminate_templstr = terminate_templfile.read()
terminate_templfile.close()


# RELEASE
release_templpath = os.path.join(os.getcwd(), "static", NSI_RELEASE_TEMPLATE_XMLFILE)

# Read RELEASE template code
with open(release_templpath) as release_templfile:
    release_templstr = release_templfile.read()
release_templfile.close()


# RESERVE_TIMEOUT_ACK
reserve_timeout_ack_templpath = os.path.join(os.getcwd(), "static", NSI_RESERVE_TIMEOUT_ACK_TEMPLATE_XMLFILE)

# Read RESERVE_TIMEOUT_ACK template code
with open(reserve_timeout_ack_templpath) as reserve_timeout_ack_templfile:
    reserve_timeout_ack_templstr = reserve_timeout_ack_templfile.read()
reserve_timeout_ack_templfile.close()


#
# Views
#


def create_footer():
    img = c.Image(
        # src='https://avatars.githubusercontent.com/u/110818415',
        src="/static/ANA-website-footer.png",
        alt="ANA footer Logo",
        width=900,
        height=240,
        loading="lazy",
        referrer_policy="no-referrer",
        class_name="border rounded",
    )
    return img


def show_endpoints_table(heading, clickurl, local_endpoints) -> list[AnyComponent]:
    """Show a table of four endpoints, `/api` is the endpoint the frontend will connect to
    when a endpoint visits `/` to fetch components to render.
    """
    detail_url = "/endpoint-details/?id={id}"

    return [
        c.Page(  # Page provides a basic container for components
            components=[
                c.Heading(text=heading, level=2, class_name="+ text-danger"),  # renders `<h2>Endpoints</h2>`
                c.Link(components=[c.Text(text="Back")], on_click=BackEvent()),
                c.Table(
                    data=local_endpoints,
                    # define two columns for the table
                    columns=[
                        # the first is the endpoint's name rendered as a link to clickurl
                        DisplayLookup(field="name", on_click=GoToEvent(url=clickurl)),
                        # the second is the start vlan
                        DisplayLookup(field="svlanid"),
                        DisplayLookup(field="evlanid"),
                        DisplayLookup(field="domain", on_click=GoToEvent(url=detail_url)),
                    ],
                ),
                create_footer(),
            ]
        ),
    ]


def show_links_table(heading, clickurl, local_links) -> list[AnyComponent]:
    """Show a table of ANA links"""
    return [
        c.Page(  # Page provides a basic container for components
            components=add_links_table(heading, clickurl, local_links, 2)
        ),
    ]


def add_links_table(heading, clickurl, local_links) -> list[AnyComponent]:
    """Return list of components for a table of ANA links"""
    return [
        c.Heading(text=heading, level=2, class_name="+ text-danger"),
        c.Paragraph(
            text="NSI supports Explicit Route Objects (ERO), allowing link selection", class_name="+ text-success"
        ),
        c.Table(
            data=local_links,
            # define two columns for the table
            columns=[
                DisplayLookup(field="name", on_click=GoToEvent(url=clickurl)),
                DisplayLookup(field="linkid"),
            ],
        ),
        create_footer(),
    ]


def show_reservations_table(heading, clickurl, local_reservations) -> list[AnyComponent]:
    """Show a table of reservations"""
    root_url = SERVER_URL_PREFIX + "/"  # back to landing

    return [
        c.Page(  # Page provides a basic container for components
            components=[
                c.Heading(text=heading, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
                c.Link(components=[c.Paragraph(text="To Landing Page")], on_click=GoToEvent(url=root_url)),
                c.Table(
                    data_model=Reservation,
                    data=local_reservations,
                    # define two columns for the table
                    columns=[
                        DisplayLookup(field="connectionId", on_click=GoToEvent(url=clickurl)),
                        DisplayLookup(field="description"),
                        DisplayLookup(field="lifecycleState"),
                    ],
                ),
                create_footer(),
            ]
        ),
    ]


def add_spans_table(heading, clickurl, local_spans) -> list[AnyComponent]:
    """Return list of components for a table of Spans"""
    return [
        c.Heading(text=heading, level=3, class_name="+ text-success"),
        c.Table(
            data_model=Span,
            data=local_spans,
            # define columns for the table
            columns=[
                DisplayLookup(field="connectionId", on_click=GoToEvent(url=clickurl)),
                DisplayLookup(field="sourceSTP"),
                DisplayLookup(field="destSTP"),
            ],
        ),
        create_footer(),
    ]


def add_discovery_table(heading, clickurl, local_discoveries, level) -> list[AnyComponent]:
    """Return list of components for a table of Spans"""
    return [
        c.Heading(text=heading, level=level, class_name="+ text-dark"),
        c.Table(
            data_model=Discovery,
            data=local_discoveries,
            # define columns for the table
            columns=[
                DisplayLookup(field="agentid", on_click=GoToEvent(url=clickurl)),
                DisplayLookup(field="version"),
                DisplayLookup(field="expires"),
            ],
        ),
        # create_footer(),
    ]


def add_spans_table(heading, clickurl, local_spans) -> list[AnyComponent]:
    """Return list of components for a table of Spans"""
    return [
        c.Heading(text=heading, level=3, class_name="+ text-success"),
        c.Table(
            data_model=Span,
            data=local_spans,
            # define columns for the table
            columns=[
                DisplayLookup(field="connectionId", on_click=GoToEvent(url=clickurl)),
                DisplayLookup(field="sourceSTP"),
                DisplayLookup(field="destSTP"),
            ],
        ),
        create_footer(),
    ]


#
# Routes
#


# Landing page
# @app.get("/api/", response_model=FastUI, response_model_exclude_none=True)
@app.get("/api/", response_model=FastUI, response_model_exclude_none=True, dependencies=[Depends(get_auth_user)])
def fastapi_landing_page(request: Request) -> list[AnyComponent]:
    """Landing page"""
    logger.debug("DEBUG: /api/ ENTER landing")

    global ONLINE
    global global_provider_nsa_id
    if not ONLINE:
        # Could not talk to agent, go to standalone demo
        orchestrator_name = "(off-line)"
    else:
        orchestrator_name = global_provider_nsa_id

    mailto_noc_url = "mailto:noc@netherlight.net"  # TODO: fix that is correct link in HTML
    reload_topos_url = SERVER_URL_PREFIX + "/reload-topos/"
    selecta_url = SERVER_URL_PREFIX + "/selecta/"
    query_url = SERVER_URL_PREFIX + "/query/"

    # Check if authorized
    auth_bool = get_auth_user(request)
    if auth_bool:
        auth_str = "Authorized"
    else:
        auth_str = (
            "You are accessing a system illegally according to the Dutch Wet Computer Criminaliteit. You MUST go away!"
        )

    return [
        c.Page(  # Page provides a basic container for components
            components=[
                c.Heading(text=SITE_TITLE, level=2, class_name="+ text-danger"),
                c.Paragraph(text="Talking to " + orchestrator_name, class_name="+ text-success"),
                c.Paragraph(text=auth_str, class_name="+ text-warning"),
                c.Heading(text="Create New Connection", level=3),
                c.Link(
                    components=[
                        c.Paragraph(
                            text="1. Mail NOC of domain A and Z to determine Customer VLAN IDs and add matching endpoints to NSI domain topologies"
                        )
                    ],
                    on_click=GoToEvent(url=mailto_noc_url),
                ),
                c.Link(
                    components=[c.Paragraph(text="2. Reload topologies of domains from NSI-DDS")],
                    on_click=GoToEvent(url=reload_topos_url),
                ),
                c.Link(
                    components=[c.Paragraph(text="3. Select endpoints and link")], on_click=GoToEvent(url=selecta_url)
                ),
                c.Heading(text="Overview", level=3),
                c.Link(
                    components=[c.Paragraph(text="Query existing connections from NSI Aggregator")],
                    on_click=GoToEvent(url=query_url),
                ),
                create_footer(),
            ]
        ),
    ]


# Reload topologies from NSI-DDS
@app.get("/api/reload-topos/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_reload_topos() -> list[AnyComponent]:
    """Reload topos from NSI-Orchestrator"""
    click_url = SERVER_URL_PREFIX + "/"  # back to landing
    try:
        # TODO, USE await example with data model from fastUI tutorial

        #
        # Retrieves DDS info, and loads into data Models
        # Also sets
        # - global_provider_nsa_id
        # - global_soap_provider_url
        #
        dds_documents_dict = nsi_load_dds_documents()

        # Display info about reload to user:
        # DDS knows all, so also who is our Orchestrator/Safnari
        orchestrator_dict = dds_documents_dict["local"]
        global global_provider_nsa_id
        # global_soap_provider_url = orchestrator_dict["services"][SOAP_PROVIDER_MIME_TYPE]

        # upas = []
        local_discoveries = []
        disccount = 1

        upas_list_as_string = ""

        documents = dds_documents_dict["documents"]
        for upa_id in documents.keys():
            document = documents[upa_id]

            if upa_id != global_provider_nsa_id:
                upas_list_as_string += upa_id + ", "

            print("fastapi_reload_topos: Adding to Datamodel", upa_id)
            discovery_obj = discoverydict2model(disccount, document["discovery"])
            local_discoveries.append(discovery_obj)
            disccount += 1

        # TODO: implement link details
        root_url = SERVER_URL_PREFIX + "/"
        clickurl = root_url

    except Exception:
        traceback.print_exc()

        # Going offline
        global ONLINE
        ONLINE = False

        raise HTTPException(status_code=404, detail="Endpoint or link not found")

    complist = [
        c.Heading(text="NSI Reload Topologies", level=2, class_name="+ text-danger"),
        c.Link(components=[c.Paragraph(text="Back")], on_click=GoToEvent(url=root_url)),
        c.Paragraph(text="Loaded Aggregator and uPA information", class_name="+ text-success"),
        c.Heading(text="Connected to Aggregator", level=4),
        c.Paragraph(text=global_provider_nsa_id, class_name="+ text-warning"),
        # c.Heading(text="Found the following domains / uPAs", level=4),
        # c.Paragraph(text=upas_list_as_string, class_name="+ text-success"),
    ]
    complist.extend(add_discovery_table("Found Agents", clickurl, local_discoveries, 4))
    complist.extend(add_links_table("ANA Links Found", clickurl, global_links, 3))
    # complist.append(create_footer())

    page = c.Page(components=complist)

    return [page]


def add_links_table(heading, clickurl, local_links, level) -> list[AnyComponent]:
    """Return list of components for a table of ANA links"""
    return [
        c.Heading(text=heading, level=level, class_name="+ text-danger"),
        c.Paragraph(
            text="NSI supports Explicit Route Objects (ERO), allowing link selection", class_name="+ text-success"
        ),
        c.Table(
            data=local_links,
            # define two columns for the table
            columns=[
                DisplayLookup(field="name", on_click=GoToEvent(url=clickurl)),
                DisplayLookup(field="linkid"),
            ],
        ),
        create_footer(),
    ]


# /api/selecta/ MUST END IN SLASH
@app.get("/api/selecta/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_select_a() -> list[AnyComponent]:
    """Show a table of four endpoints, `/api` is the endpoint the frontend will connect to
    when a endpoint visits `/` to fetch components to render.
    """
    try:

        logger.debug("DEBUG: /api/selecta/ ENTER")
        global global_endpoints

        # Arno: id refers to id of item in table as shown.
        # NOTE: relative to /api ...!
        try:
            complist = show_endpoints_table("Select endpoint A", "/selectz/?epida={id}", global_endpoints)
        except:
            traceback.print_exc()

        logger.debug("DEBUG: /api/selecta/ create complist")

        query_url = SERVER_URL_PREFIX + "/query/"
        # querycomp = c.Link(components=[c.Text(text='Query existing connections from NSI Aggregator')], on_click=GoToEvent(url=query_url))
        # complist.append(querycomp)

        logger.debug("DEBUG: /api/selecta/ return complist")

        return complist
    except Exception:
        raise HTTPException(status_code=404, detail="Landing page not found")


@app.get("/api/selectz/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_select_z(epida: int) -> list[AnyComponent]:
    """Show a table of four endpoints, `/api` is the endpoint the frontend will connect to
    when a endpoint visits `/` to fetch components to render.
    """
    logger.debug("DEBUG: /api/selectz/ ENTER")
    global global_endpoints

    # NOTE: relative to /api...!
    clickurl = "/selectlink/?epida=" + str(epida) + "&epidz={id}"

    logger.debug("DEBUG: URL template" + clickurl)

    return show_endpoints_table("Select endpoint Z", clickurl, global_endpoints)


@app.get("/api/selectlink/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_select_link(epida: int, epidz: int) -> list[AnyComponent]:
    """Show a table of links, on click goto Reserve page"""
    logger.debug("DEBUG: /api/selectlink/ ENTER")

    # NOTE: relative to /api...!
    clickurl = "/reserve/?epida=" + str(epida) + "&epidz=" + str(epidz) + "&linkid={id}"

    logger.debug("DEBUG: URL template" + clickurl)

    return show_links_table("Select ANA link", clickurl, global_links)


#
# Arch:
#       - Send message from page, wait for HTTP reply, show info
#       - Poll for async callback from NSI
#       - Show button to user for next message
#
#       - Orchestrator sends async replies to one point.
#       - Placed in list/queue there
#       - Poll from GUI takes this from the list/queue
#


def generate_poll_url(msgname, clean_correlation_uuid_str, clean_connection_id_str):
    return "/poll/?msg=" + msgname + "&corruuid=" + clean_correlation_uuid_str + "&connid=" + clean_connection_id_str


# GUI polling for Orchestrator async reply using GET
pollcount = 481


@app.get("/api/poll/", response_model=FastUI, response_model_exclude_none=True)
async def fastapi_general_poll(msg: str, corruuid: uuid.UUID, connid: uuid.UUID) -> list[AnyComponent]:
    """FastUI page polls for a Orchestrator async response, aka callback
    msg: for which message type we are awaiting an async callback
    corruuid: expected correlation UUID
    connid: expected connection ID (also a UUID)
    """
    try:
        print("poll: ENTER")
        print("poll: ENTER for", msg)
        logger.debug("poll: ENTER2: " + msg)

        await asyncio.sleep(1)  # 1 second, fractions allowed too
        global pollcount
        pollcount += 1
        text = "Received poll from GUI #" + str(pollcount)

        # We got poll from GUI, now process it
        # SECURITY: fastAPI has made sure these are UUIDs
        clean_connection_id_str = str(connid)
        clean_correlation_uuid_str = str(corruuid)

        print("poll: Polling for", clean_correlation_uuid_str)

        global global_orch_async_replies_lock
        global global_orch_async_replies_dict
        poll_again = True
        complist = []
        body = None
        with global_orch_async_replies_lock:
            if clean_correlation_uuid_str in global_orch_async_replies_dict.keys():
                # Consume reply from queue
                body = global_orch_async_replies_dict[clean_correlation_uuid_str]
                global_orch_async_replies_dict.pop(clean_correlation_uuid_str, None)

                # Control GUI
                poll_again = False
                text = text + ": got reply!"
        # Release lock ASAP

        if not ONLINE:
            # generate fake
            if msg == FASTAPI_MSGNAME_QUERY_RECURSIVE:
                # Read sample reply
                with open(sample_qr_cbpath, mode="rb") as sample_qr_cbfile:
                    body = sample_qr_cbfile.read()
                sample_qr_cbfile.close()

        # Found a callback, turn XML into GUI components, depending on NSI msg type
        if body is not None:
            complist = fastui_generate_from_callback(msg, body)

        retlist = [c.Paragraph(text=text)]
        retlist.extend(complist)
        if poll_again:
            # Poll again with info
            poll_url = generate_poll_url(msg, clean_correlation_uuid_str, clean_connection_id_str)
            retlist.append(c.ServerLoad(path=poll_url))

        print("poll: RETURN")
        return retlist
    except:
        traceback.print_exc()
        print("poll: ERROR")
        return [c.Paragraph(text="poll: EXCEPTION", class_name="+ text-danger")]


def fastui_generate_from_callback(msg, xml):
    """Generate a partial page from the SOAP XML async reply to an NSI message of
    type "msg" from the Orchestrator
    Returns a Component list
    """
    complist = []
    if msg == FASTAPI_MSGNAME_RESERVE:
        retdict = nsi_soap_parse_reserve_callback(xml)

        print("fastui_generate_from_callback: Parsed", retdict)

        faultstring = retdict[S_FAULTSTRING_TAG]
        if faultstring is None:
            complist = [
                c.Heading(text="Source STP (final VLAN id)", level=3),
                c.Paragraph(text=retdict[S_SOURCE_STP_TAG], class_name="+ text-success"),
                c.Heading(text="Dest STP (final VLAN id)", level=3),
                c.Paragraph(text=retdict[S_DEST_STP_TAG], class_name="+ text-success"),
                c.Heading(text="State", level=3),
                c.Paragraph(text=retdict[S_RESERVE_CONFIRMED_TAG], class_name="+ text-warning"),
                # c.Heading(text="ConnectionId", level=3),
                # c.Paragraph(text=retdict[S_CONNECTION_ID_TAG], class_name="+ text-warning"),
            ]
        else:

            complist = [
                c.Paragraph(text=faultstring, class_name="+ text-danger"),
            ]
    elif msg == FASTAPI_MSGNAME_QUERY_RECURSIVE:
        retdict = nsi_soap_parse_query_recursive_callback(xml)
        children_spans = []
        if retdict[S_CHILDREN_TAG] is not None:
            children_str = repr(retdict[S_CHILDREN_TAG])
            children_spans = children2spans(retdict[S_CHILDREN_TAG])
        else:
            children_str = "No children found"

        click_url = "/"

        # complist = [
        #    c.Heading(text="Found children", level=3),
        #    c.Paragraph(text=children_str, class_name="+ text-success"),
        #    ]
        complist = []
        complist2 = add_spans_table("Found children", click_url, children_spans)
        complist.extend(complist2)

    return complist


def children2spans(children):
    """Take children dict parsed from Orchestrator async SOAP reply to DataModel Spans
    returns a list of Spans
    """
    paircount = 1
    local_spans = []
    for connid in children.keys():
        child = children[connid]
        span = Span(id=paircount, connectionId=connid, sourceSTP=child[S_SOURCE_STP_TAG], destSTP=child[S_DEST_STP_TAG])
        paircount += 1
        local_spans.append(span)
    return local_spans


#
#
#  Orchestrator sending async reply, got all NSI message types
#
#


@app.post("/api/callback/")
async def orchestrator_general_callback(request: Request):
    """Orchestrator POSTs async reply to AuRA. Hence AuRA needs to run on reachable IP
    reply is stored in global_orch_async_replies_dict by correlationId
    Returns nothing
    """
    print("CALLBACK: ENTER")
    body = await request.body()
    # body = request.body()
    print("CALLBACK: Got body", body)

    #
    # TODO: move XML handling to nsicomm.py
    # TODO: properly parse cotent-type
    #
    content_type = request.headers["content-type"]
    content_type = content_type.lower()
    if (
        content_type == "application/xml"
        or content_type == "text/xml"
        or content_type == "text/xml;charset=utf-8"
        or content_type == "text/xml; charset=UTF-8"
        or content_type.startswith("text/xml")
    ):
        try:
            tree = nsi_util_parse_xml(body)
            tag = tree.find(FIND_ANYWHERE_PREFIX + S_CORRELATION_ID_TAG)
            if tag is not None:
                print("CALLBACK: Found correlationId", tag.text)
                correlation_urn = tag.text
            else:
                print("CALLBACK: Could not find correlationId", body)
                return []

            correlation_uuid_str = correlation_urn[len(URN_UUID_PREFIX) :]

            global global_orch_async_replies_lock
            global global_orch_async_replies_dict
            with global_orch_async_replies_lock:
                print("CALLBACK: Got lock")
                global_orch_async_replies_dict[correlation_uuid_str] = body
        except:
            traceback.print_exc()
    else:
        print("CALLBACK: Orchestrator did not return XML, but #" + request.headers["content-type"] + "#")

    # TODO: reply from example
    return ["Rick", "Morty"]


#
# GUI Send NSI RESERVE
#
@app.get("/api/reserve/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_reserve(epida: int, epidz: int, linkid: int) -> list[AnyComponent]:
    """NSI RESERVE"""
    try:
        print("fastapi_nsi_reserve: ENTER")

        endpointa = next(u for u in global_endpoints if u.id == epida)
        endpointz = next(u for u in global_endpoints if u.id == epidz)
        link = next(u for u in global_links if u.id == linkid)

        # duration_td = datetime.timedelta(days=30)
        duration_td = datetime.timedelta(minutes=5)

        correlation_uuid_py = generate_uuid()

        # Create URL
        # For async Orchestrator reply
        # TEST
        # clean_correlation_uuid_str = 'b23efb40-9ce5-11ef-8a24-fa163e074abf'
        # From static/orch-callback-reply-soap.xml
        # clean_correlation_uuid_str = '8d8e76aa-854e-45e7-ae10-c7fd856fdbad'
        clean_correlation_uuid_str = str(correlation_uuid_py)

        print("fastapi_nsi_reserve: TEST WITH", clean_correlation_uuid_str)
        print("fastapi_nsi_reserve: TEST WITH2", correlation_uuid_py)

        # FIXME: remove connectionId from callback, at least for RESERVE
        clean_connection_id_str = str(generate_uuid())

        # orch_reply_to_url = SERVER_URL_PREFIX+"/callback/?corruuid="+clean_correlation_uuid_str+"&connid="+clean_connection_id_str
        # orch_reply_to_url = SERVER_URL_PREFIX+"/callback/?corruuid="+clean_correlation_uuid_str
        orch_reply_to_url = SERVER_URL_PREFIX + "/api/callback/"

        print("fastapi_nsi_reserve: Orch will reply via", orch_reply_to_url)

        # Fake data for off-line, to be overwritten
        reserve_reply_dict = {}
        reserve_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        reserve_reply_dict["correlationId"] = clean_correlation_uuid_str  # DUMMY_CORRELATION_ID_STR
        reserve_reply_dict["globalReservationId"] = DUMMY_GLOBAL_RESERVATION_ID_STR
        reserve_reply_dict["connectionId"] = DUMMY_CONNECTION_ID_STR

        # Call NSI, wait for sync HTTP reply
        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global reserve_templstr
            reserve_reply_dict = nsi_reserve(
                reserve_templstr,
                global_soap_provider_url,
                correlation_uuid_py,
                orch_reply_to_url,
                global_provider_nsa_id,
                endpointa.name,
                endpointa.svlanid,
                endpointz.name,
                endpointz.evlanid,
                link.name,
                link.id,
                duration_td,
            )

        # Check for errors
        if reserve_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = reserve_reply_dict[S_FAULTSTRING_TAG]

        # If we do not trust Orchestrator, sanitize these because they are displayed in HTML
        clean_correlation_uuid_str = reserve_reply_dict["correlationId"]
        clean_connection_id_str = reserve_reply_dict["connectionId"]

        print("fastapi_nsi_reserve: REPLY HAS CORRUUID", clean_correlation_uuid_str)

        # Create URL
        # For GUI to poll on (relative URL)
        # poll_url = '/poll/reserve/'
        # poll_url = "/poll/reserve/?corruuid="+corruuid+"&connid="+connid
        poll_url = generate_poll_url(FASTAPI_MSGNAME_RESERVE, clean_correlation_uuid_str, clean_connection_id_str)

        root_url = SERVER_URL_PREFIX + "/"

        # To inspect the spans that were stitched together
        query_rec_url = SERVER_URL_PREFIX + "/query-recursive/?connid=" + reserve_reply_dict["connectionId"]

        # For simulation, no /api
        sim_reply_to_url = SERVER_URL_PREFIX + "/reserve-commit/?connid=" + reserve_reply_dict["connectionId"]

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="Endpoint or link not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI RESERVE the following product", level=2, class_name="+ text-danger"),
                c.Heading(text="Endpoint A", level=3),
                c.Details(data=endpointa),
                c.Heading(text="Endpoint Z", level=3),
                c.Details(data=endpointz),
                c.Heading(text="Link", level=3),
                c.Details(data=link),
                c.Heading(text="Sent RESERVE", level=3),
                c.Heading(text="Returned connectionId " + clean_connection_id_str, level=4, class_name=cssclassname),
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(components=[c.Paragraph(text="Inspect reserved path")], on_click=GoToEvent(url=query_rec_url)),
                c.Link(components=[c.Paragraph(text="Send Reserve Commit")], on_click=GoToEvent(url=sim_reply_to_url)),
                c.Link(components=[c.Paragraph(text="Back to landing page")], on_click=GoToEvent(url=root_url)),
                c.ServerLoad(path=poll_url),
            ]
        ),
    ]


#  GUI Send RESERVE COMMIT
@app.get("/api/reserve-commit/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_reserve_commit(connid: str) -> list[AnyComponent]:
    """NSI RESERVE callback, send RESERVE-COMMIT

    # TODO: check input uuid str
    # fastapi names must be as in query param
    """
    try:
        print("fastapi_nsi_reserve_commit: ENTER")

        # We got async reply from NSI-Orchestrator, and user pressed "Send RESERVE COMMIT"
        # We expect the following ids in the request
        expect_correlation_uuid_py = generate_uuid()
        expect_connection_id_str = connid

        # SECURITY: DO NOT PRINT ANY OF THESE INPUTS
        clean_connection_id_str = "BAD UUID FROM CLIENT"
        try:
            u = uuid.UUID(expect_connection_id_str)
            clean_connection_id_str = str(u)
        except:
            traceback.print_exc()

        #
        # Send Reserve commit
        #
        # Fake data for off-line, to be overwritten
        reserve_commit_reply_dict = {}
        reserve_commit_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        reserve_commit_reply_dict["correlationId"] = DUMMY_CORRELATION_ID_STR
        # TODO: get rid of globalReservationId
        reserve_commit_reply_dict["globalReservationId"] = DUMMY_GLOBAL_RESERVATION_ID_STR
        reserve_commit_reply_dict["connectionId"] = DUMMY_CONNECTION_ID_STR

        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global reserve_commit_templstr
            reserve_commit_reply_dict = nsi_reserve_commit(
                reserve_commit_templstr,
                global_soap_provider_url,
                SERVER_URL_PREFIX,
                global_provider_nsa_id,
                clean_connection_id_str,
            )

        # RESTFUL: Do Not Store (TODO or for security)
        # TODO NEWCALLBACK
        orch_reply_to_url = (
            SERVER_URL_PREFIX
            + "/reserve-commit-callback/?corruuid="
            + reserve_commit_reply_dict["correlationId"]
            + "&globresuuid="
            + reserve_commit_reply_dict["globalReservationId"]
            + "&connid="
            + clean_connection_id_str
        )

        # Check for errors
        if reserve_commit_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = reserve_commit_reply_dict[S_FAULTSTRING_TAG]

        root_url = SERVER_URL_PREFIX + "/"

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="RESERVE CALLBACK query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI RESERVE COMMIT", level=2, class_name="+ text-danger"),
                c.Heading(text="Sent RESERVE COMMIT", level=3),
                c.Heading(text="Got reply for connection " + clean_connection_id_str, level=4),  # NOT FROM URL QUERY
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(
                    components=[c.Paragraph(text="Simulate async Reserve Commit Callback")],
                    on_click=GoToEvent(url=orch_reply_to_url),
                ),
                c.Link(components=[c.Paragraph(text="Back to landing page")], on_click=GoToEvent(url=root_url)),
            ]
        ),
    ]


# NSI RESERVE PROVISION NEWCALLBACK
@app.get("/api/reserve-commit-callback/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_reserve_commit_callback(corruuid: str, globresuuid: str, connid: str) -> list[AnyComponent]:
    """NSI RESERVE COMMIT callback, send PROVISION

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_reserve_commit_callback: ENTER")

        # TODO: We got async reply from NSI-Orchestrator, now process it
        # We expect the following ids in the
        expect_correlation_uuid_py = uuid.UUID(corruuid)  # TODO: new UUID for new message
        expect_global_reservation_uuid_py = uuid.UUID(globresuuid)
        expect_connection_id_str = connid

        # SECURITY: DO NOT PRINT ANY OF THESE INPUTS
        clean_connection_id_str = "BAD UUID FROM CLIENT"
        try:
            u = uuid.UUID(expect_connection_id_str)
            clean_connection_id_str = str(u)
        except:
            traceback.print_exc()

        #
        # Send Provision
        #
        # Fake data for off-line, to be overwritten
        provision_reply_dict = {}
        provision_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        provision_reply_dict["correlationId"] = DUMMY_CORRELATION_ID_STR
        provision_reply_dict["globalReservationId"] = DUMMY_GLOBAL_RESERVATION_ID_STR
        provision_reply_dict["connectionId"] = DUMMY_CONNECTION_ID_STR

        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global provision_templstr
            provision_reply_dict = nsi_provision(
                provision_templstr,
                global_soap_provider_url,
                SERVER_URL_PREFIX,
                global_provider_nsa_id,
                expect_global_reservation_uuid_py,
                clean_connection_id_str,
            )

        # RESTFUL: Do Not Store (TODO or for security)
        orch_reply_to_url = (
            SERVER_URL_PREFIX
            + "/provision-callback/?corruuid="
            + provision_reply_dict["correlationId"]
            + "&globresuuid="
            + provision_reply_dict["globalReservationId"]
            + "&connid="
            + clean_connection_id_str
        )

        # Check for errors
        if provision_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = provision_reply_dict[S_FAULTSTRING_TAG]

        root_url = SERVER_URL_PREFIX + "/"

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="RESERVE COMMIT CALLBACK query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI PROVISION", level=2, class_name="+ text-danger"),
                c.Heading(text="Sent PROVISION", level=3),
                c.Heading(text="Got reply for connection " + clean_connection_id_str, level=4),  # NOT FROM URL QUERY
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(
                    components=[c.Paragraph(text="Simulate async Provision Callback")],
                    on_click=GoToEvent(url=orch_reply_to_url),
                ),
                c.Link(components=[c.Paragraph(text="Back to landing page")], on_click=GoToEvent(url=root_url)),
            ]
        ),
    ]


# NSI PROVISION callback
# Will be: Provisioned link overview
@app.get("/api/provision-callback/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_provision_callback(corruuid: str, globresuuid: str) -> list[AnyComponent]:
    """NSI PROVISION callback, Go Back to Start, or Show List

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_provision_callback: ENTER")

        global provision_templstr
        correlation_uuid_py = uuid.UUID(corruuid)
        global_reservation_uuid_py = uuid.UUID(corruuid)

        root_url = SERVER_URL_PREFIX + "/"
        query_url = SERVER_URL_PREFIX + "/query/"

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="PROVISION CALLBACK query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI PROVISION callback", level=2, class_name="+ text-danger"),
                c.Heading(text=str(correlation_uuid_py), level=3),  # NOT FROM URL QUERY
                c.Heading(text="Successful? See Reservations list", level=3),
                c.Link(
                    components=[c.Paragraph(text="Query existing connections from NSI Orchestrator")],
                    on_click=GoToEvent(url=query_url),
                ),
                c.Link(components=[c.Paragraph(text="Back to Landing Page")], on_click=GoToEvent(url=root_url)),
            ]
        ),
    ]


# NSI QUERY SUMMARY SYNC
@app.get("/api/query/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_connections_query() -> list[AnyComponent]:
    """NSI Query, Go Back to Start"""
    print("fastapi_nsi_connections_query: ENTER")
    click_url = "/reservation-details/?id={id}"
    try:
        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global query_summary_sync_templstr
            resdictlist = nsi_connections_query(
                query_summary_sync_templstr, global_soap_provider_url, SERVER_URL_PREFIX, global_provider_nsa_id
            )

            print("fastapi_nsi_connections_query: Got reservations", resdictlist)

            # Turn into Model
            nsi_load_parsed_soap_into_reservations_model(resdictlist)

            logger.debug("fastapi_nsi_connections_query: UPDATED reservations Model")
            print("fastapi_nsi_connections_query: UPDATED reservations Model")

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="QUERY query param not found")

    return show_reservations_table("NSI Current Reservations", click_url, global_reservations)


#
# TODO: CHECK IF THERE IS ANY CALLBACK ON A QUERY
#


# NSI QUERY SUMMARY SYNC callback
#
# TODO: UNUSED?
#
@app.get("/api/query-callback/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_connections_query_callback(corruuid: str) -> list[AnyComponent]:
    """NSI QUERY callback, Go Back to Start, or Redo query

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        global query_summary_sync_templstr
        correlation_uuid_py = uuid.UUID(corruuid)

        root_url = SERVER_URL_PREFIX + "/"
        query_url = SERVER_URL_PREFIX + "/query/"

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="QUERY CALLBACK query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI QUERY Callback", level=2, class_name="+ text-danger"),
                c.Heading(text=str(correlation_uuid_py), level=3),  # NOT FROM URL QUERY
                c.Heading(text="List? See Body", level=3),
                c.Link(components=[c.Text(text="Create another Connection")], on_click=GoToEvent(url=root_url)),
                c.Heading(text="Overview", level=3),
                c.Link(
                    components=[c.Text(text="Redo query existing connections from NSI Aggregator")],
                    on_click=GoToEvent(url=query_url),
                ),
            ]
        ),
    ]


# NSI TERMINATE
@app.get("/api/terminate/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_terminate(connid: str) -> list[AnyComponent]:
    """NSI TERMINATE

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_terminate: ENTER")

        # TODO: We got async reply from NSI-Orchestrator, now process it
        # We expect the following ids in the
        expect_connection_id_str = connid

        # SECURITY: DO NOT PRINT ANY OF THESE INPUTS
        clean_connection_id_str = "BAD UUID FROM CLIENT"
        try:
            u = uuid.UUID(expect_connection_id_str)
            clean_connection_id_str = str(u)
        except:
            traceback.print_exc()

        #
        # Send Terminate
        #
        terminate_reply_dict = {}
        terminate_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        # TODO: prepare error dict, see above
        # e.g. add correlation_uuid_py = uuid.UUID(corruuid)

        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global terminate_templstr
            terminate_reply_dict = nsi_terminate(
                terminate_templstr,
                global_soap_provider_url,
                SERVER_URL_PREFIX,
                global_provider_nsa_id,
                clean_connection_id_str,
            )

        if terminate_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = terminate_reply_dict[S_FAULTSTRING_TAG]

        # RESTFUL: Do Not Store (TODO or for security)
        orch_reply_to_url = (
            SERVER_URL_PREFIX
            + "/terminate-callback/?corruuid="
            + terminate_reply_dict["correlationId"]
            + "&connid="
            + clean_connection_id_str
        )

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="TERMINATE query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI TERMINATE", level=2, class_name="+ text-danger"),
                c.Heading(text="Sent TERMINATE", level=3),
                c.Heading(text="Got reply for connection " + clean_connection_id_str, level=4),  # NOT FROM URL QUERY
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(
                    components=[c.Paragraph(text="Simulate async Terminate Callback")],
                    on_click=GoToEvent(url=orch_reply_to_url),
                ),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
            ]
        ),
    ]


#
# TODO: Terminate callback
#


# NSI RELEASE
@app.get("/api/release/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_release(connid: str) -> list[AnyComponent]:
    """NSI RELEASE

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_release: ENTER")

        # TODO: We got async reply from NSI-Orchestrator, now process it
        # We expect the following ids in the
        expect_connection_id_str = connid

        # SECURITY: DO NOT PRINT ANY OF THESE INPUTS
        clean_connection_id_str = "BAD UUID FROM CLIENT"
        try:
            u = uuid.UUID(expect_connection_id_str)
            clean_connection_id_str = str(u)
        except:
            traceback.print_exc()

        release_reply_dict = {}
        release_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        # TODO: more error dict

        #
        # Send release
        #
        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global release_templstr
            release_reply_dict = nsi_release(
                release_templstr,
                global_soap_provider_url,
                SERVER_URL_PREFIX,
                global_provider_nsa_id,
                clean_connection_id_str,
            )

        if release_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = release_reply_dict[S_FAULTSTRING_TAG]

        # RESTFUL: Do Not Store (TODO or for security)
        orch_reply_to_url = (
            SERVER_URL_PREFIX
            + "/release-callback/?corruuid="
            + release_reply_dict["correlationId"]
            + "&connid="
            + clean_connection_id_str
        )

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="release query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI RELEASE", level=2, class_name="+ text-danger"),
                c.Heading(text="Sent RELEASE", level=3),
                c.Heading(text="Got reply for connection " + clean_connection_id_str, level=4),  # NOT FROM URL QUERY
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(
                    components=[c.Paragraph(text="Simulate async release Callback")],
                    on_click=GoToEvent(url=orch_reply_to_url),
                ),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
            ]
        ),
    ]


#
# TODO: release callback
#


# NSI reserve_timeout_ack
@app.get("/api/reserve-timeout-ack/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_reserve_timeout_ack(connid: str) -> list[AnyComponent]:
    """NSI RELEASE

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_reserve_timeout_ack: ENTER")

        # TODO: We got async reply from NSI-Orchestrator, now process it
        # We expect the following ids in the
        expect_connection_id_str = connid

        # SECURITY: DO NOT PRINT ANY OF THESE INPUTS
        clean_connection_id_str = "BAD UUID FROM CLIENT"
        try:
            u = uuid.UUID(expect_connection_id_str)
            clean_connection_id_str = str(u)
        except:
            traceback.print_exc()

        reserve_timeout_ack_reply_dict = {}
        reserve_timeout_ack_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable (demo mode)"
        # TODO: more error dict

        #
        # Send reserve_timeout_ack
        #
        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global reserve_timeout_ack_templstr
            reserve_timeout_ack_reply_dict = nsi_reserve_timeout_ack(
                reserve_timeout_ack_templstr,
                global_soap_provider_url,
                SERVER_URL_PREFIX,
                global_provider_nsa_id,
                clean_connection_id_str,
            )

        if reserve_timeout_ack_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = reserve_timeout_ack_reply_dict[S_FAULTSTRING_TAG]

        # RESTFUL: Do Not Store (TODO or for security)
        orch_reply_to_url = (
            SERVER_URL_PREFIX
            + "/reserve_timeout_ack-callback/?corruuid="
            + reserve_timeout_ack_reply_dict["correlationId"]
            + "&connid="
            + clean_connection_id_str
        )

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="reserve_timeout_ack query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI RESERVE TIMEOUT ACK", level=2, class_name="+ text-danger"),
                c.Heading(text="Sent RESERVE TIMEOUT ACK", level=3),
                c.Heading(text="Got reply for connection " + clean_connection_id_str, level=4),  # NOT FROM URL QUERY
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(
                    components=[c.Paragraph(text="Simulate async reserve_timeout_ack Callback")],
                    on_click=GoToEvent(url=orch_reply_to_url),
                ),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
            ]
        ),
    ]


#
# TODO: reserve_timeout_ack callback
#


# NSI QUERY RECURSIVE
@app.get("/api/query-recursive/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_query_recursive(connid: str) -> list[AnyComponent]:
    """NSI QUERY RECURSIVE
    This asks the Orchestrator for details on a connection. There is a synchronous HTTP reply for receipt,
    and then an async callback with the actual data.

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_query_recursive: ENTER")

        # We expect the following ids in the
        expect_connection_id_str = connid

        # SECURITY: DO NOT PRINT ANY OF THESE INPUTS
        clean_connection_id_str = "BAD UUID FROM CLIENT"
        try:
            u = uuid.UUID(expect_connection_id_str)
            clean_connection_id_str = str(u)
        except:
            traceback.print_exc()

        # THINK
        # For queryRecursive there is no HTTP reply with
        ##correlation_uuid_py = generate_uuid()

        #
        # Send query recursive
        #
        # Fake data for off-line, to be overwritten
        query_recursive_reply_dict = {}
        query_recursive_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        query_recursive_reply_dict["correlationId"] = DUMMY_CORRELATION_ID_STR
        query_recursive_reply_dict["globalReservationId"] = DUMMY_GLOBAL_RESERVATION_ID_STR
        query_recursive_reply_dict["connectionId"] = DUMMY_CONNECTION_ID_STR

        orch_reply_to_url = SERVER_URL_PREFIX + "/api/callback/"

        print("fastapi_nsi_query_recursive: Orch will reply via", orch_reply_to_url)

        global ONLINE
        if ONLINE:
            global global_provider_nsa_id
            global global_soap_provider_url
            global query_recursive_templstr
            query_recursive_reply_dict = nsi_query_recursive(
                query_recursive_templstr,
                global_soap_provider_url,
                orch_reply_to_url,
                global_provider_nsa_id,
                clean_connection_id_str,
            )

        if query_recursive_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = query_recursive_reply_dict[S_FAULTSTRING_TAG]

        # HTTP Reply is a simple <nsi_ctypes:acknowledgment/>

        # If we do not trust Orchestrator, sanitize these because they are displayed in HTML
        clean_correlation_uuid_str = query_recursive_reply_dict["correlationId"]
        # No connectionId
        # clean_connection_id_str = DUMMY_CONNECTION_ID_STR

        # TEST w/example3
        clean_correlation_uuid_str = "dffc7375-4711-4ab2-9fda-88d51a0f2237"

        print("fastapi_nsi_query_recursive: REPLY HAS CORRUUID", clean_correlation_uuid_str)

        # Create URL
        # For GUI to poll on (relative URL)
        # poll_url = '/poll/reserve/'
        # poll_url = "/poll/reserve/?corruuid="+corruuid+"&connid="+connid
        poll_url = generate_poll_url(
            FASTAPI_MSGNAME_QUERY_RECURSIVE, clean_correlation_uuid_str, clean_connection_id_str
        )

        # When coming from /reserve
        next_step_url = SERVER_URL_PREFIX + "/reserve-commit/?connid=" + expect_connection_id_str

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="query_recursive query param not found")
    return [
        c.Page(
            components=[
                c.Heading(text="NSI QUERY RECURSIVE", level=2, class_name="+ text-danger"),
                c.Heading(text="Sent QUERY RECURSIVE", level=3),
                c.Heading(text="Got reply for connection " + clean_connection_id_str, level=4),  # NOT FROM URL QUERY
                c.Paragraph(text=faultstring, class_name=cssclassname),
                c.Link(
                    components=[c.Paragraph(text="Simulate async query-recursive callback by Aggregator")],
                    on_click=GoToEvent(url=orch_reply_to_url),
                ),
                c.Link(components=[c.Paragraph(text="Send RESERVE-COMMIT")], on_click=GoToEvent(url=next_step_url)),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
                c.ServerLoad(path=poll_url),
            ]
        ),
    ]


#
# Detail Views
#


# Original show endpoint
@app.get("/api/endpoint/{endpoint_id}/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_profile_orig(endpoint_id: int) -> list[AnyComponent]:
    """Endpoint profile page, the frontend will fetch this when the endpoint visits `/endpoint/{id}/`."""
    try:
        endpoint = next(u for u in global_endpoints if u.id == endpoint_id)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return [
        c.Page(
            components=[
                c.Heading(text=endpoint.name, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Text(text="Back")], on_click=BackEvent()),
                c.Details(data=endpoint),
            ]
        ),
    ]


# New show endpoint
@app.get("/api/endpoint-details/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_profile(id: int) -> list[AnyComponent]:
    """Endpoint profile page, the frontend will fetch this when the endpoint visits `/endpoint/{id}/`."""
    try:
        endpoint = next(u for u in global_endpoints if u.id == id)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return [
        c.Page(
            components=[
                c.Heading(text=endpoint.name, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Text(text="Back")], on_click=BackEvent()),
                c.Details(data=endpoint),
            ]
        ),
    ]


# Show reservation
@app.get("/api/reservation-details/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_reservation_profile(id: int) -> list[AnyComponent]:
    """Reservation profile page, the frontend will fetch this when the endpoint visits `/endpoint/?id={id}`."""
    try:
        logger.debug("fastapi_reservation_profile: ENTER")

        reservation = next(u for u in global_reservations if u.id == id)

        headtext = "ConnectionId " + reservation.connectionId

        terminate_url = SERVER_URL_PREFIX + "/terminate/?connid=" + reservation.connectionId
        release_url = SERVER_URL_PREFIX + "/release/?connid=" + reservation.connectionId
        reserve_timeout_ack_url = SERVER_URL_PREFIX + "/reserve-timeout-ack/?connid=" + reservation.connectionId
        query_recursive_url = SERVER_URL_PREFIX + "/query-recursive/?connid=" + reservation.connectionId

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="Reservation not found")
    return [
        c.Page(
            components=[
                c.Heading(text=headtext, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Text(text="Back")], on_click=BackEvent()),
                c.Details(data=reservation),
                c.Link(components=[c.Paragraph(text="Terminate Connection")], on_click=GoToEvent(url=terminate_url)),
                c.Link(components=[c.Paragraph(text="Release Connection")], on_click=GoToEvent(url=release_url)),
                c.Link(
                    components=[c.Paragraph(text="Simulate ReserveTimeoutAck Connection")],
                    on_click=GoToEvent(url=reserve_timeout_ack_url),
                ),
                c.Link(
                    components=[c.Paragraph(text="Query Recursive Connection")],
                    on_click=GoToEvent(url=query_recursive_url),
                ),
            ]
        ),
    ]


#
# Security from Bruno
#


# Arno: TODO move down to all routes
# @app.post("/login")
@app.get("/api/login/")
async def session_login(username: str, password: str):
    """/login?username=ssss&password=1234234234"""
    print("LOGIN: ENTER", username, password)

    allow = (username, password) == USER_CORRECT
    if allow is False:
        raise HTTPException(status_code=401)

    print("LOGIN: OK")

    # Arno
    sessionid_b64str = create_and_record_sessionid(username)

    response = RedirectResponse("/api/", status_code=302)
    response.set_cookie(key="Authorization", value=sessionid_b64str)

    return response


# @app.post("/logout")
@app.get("/api/logout/")
async def session_logout(response: Response):
    session_id = request.cookies.get("Authorization")
    response.delete_cookie(key="Authorization")
    SESSION_DB.pop(session_id, None)
    return {"status": "logged out"}


# @app.get("/", dependencies=[Depends(get_auth_user)])
# async def secret():
#    return {"secret": "info"}


# Tutorial


@app.get("/{path:path}")
async def html_landing() -> HTMLResponse:
    """Simple HTML page which serves the React app, comes last as it matches all paths."""
    return HTMLResponse(prebuilt_html(title=SITE_TITLE))
