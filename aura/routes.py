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

import asyncio
import logging
import os
import traceback
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui import prebuilt_html
from fastui.events import BackEvent, GoToEvent

import aura.state
from aura.models import DUMMY_CONNECTION_ID_STR, DUMMY_CORRELATION_ID_STR, DUMMY_GLOBAL_RESERVATION_ID_STR
from aura.nsi_aura import (
    SESSION_DB,
    USER_CORRECT,
    Span,
    add_discovery_table,
    add_links_table,
    add_spans_table,
    create_and_record_sessionid,
    create_footer,
    discoverydict2model,
    get_auth_user,
    nsi_load_dds_documents,
    nsi_load_parsed_soap_into_reservations_model,
    show_endpoints_table,
    show_links_table,
    show_reservations_table,
)
from aura.nsi_comm import (
    FIND_ANYWHERE_PREFIX,
    S_CHILDREN_TAG,
    S_CORRELATION_ID_TAG,
    S_DEST_STP_TAG,
    S_FAULTSTRING_TAG,
    S_RESERVE_CONFIRMED_TAG,
    S_SOURCE_STP_TAG,
    URN_UUID_PREFIX,
    generate_uuid,
    nsi_connections_query,
    nsi_provision,
    nsi_query_recursive,
    nsi_release,
    nsi_reserve,
    nsi_reserve_commit,
    nsi_reserve_timeout_ack,
    nsi_soap_parse_query_recursive_callback,
    nsi_soap_parse_reserve_callback,
    nsi_terminate,
    nsi_util_parse_xml, content_type_is_valid_soap, nsi_soap_parse_callback,
)
from aura.settings import settings

#
# Constants
#

#
# Used in polling and callbacks
#
FASTAPI_MSGNAME_RESERVE = "reserve"
FASTAPI_MSGNAME_QUERY_RECURSIVE = "queryRecursive"

# fake not ONLINE data
sample_qr_cbpath = os.path.join("samples", "query-recursive-callback-example3.xml")

#
# Routes
#

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.DEBUG)

router = APIRouter()


# Landing page
# @router.get("/api/", response_model=FastUI, response_model_exclude_none=True)
@router.get("/api/", response_model=FastUI, response_model_exclude_none=True, dependencies=[Depends(get_auth_user)])
def fastapi_landing_page(request: Request) -> list[AnyComponent]:
    """Landing page"""
    logger.debug("DEBUG: /api/ ENTER landing")

    if not aura.state.ONLINE:
        # Could not talk to agent, go to standalone demo
        orchestrator_name = "(off-line)"
    else:
        orchestrator_name = aura.state.global_provider_nsa_id

    mailto_noc_url = "mailto:noc@netherlight.net"  # TODO: fix that is correct link in HTML
    reload_topos_url = str(settings.SERVER_URL_PREFIX) + "reload-topos/"
    selecta_url = str(settings.SERVER_URL_PREFIX) + "selecta/"
    query_url = str(settings.SERVER_URL_PREFIX) + "query/"
    database_url = str(settings.SERVER_URL_PREFIX) + "database/"
    input_form_url = str(settings.SERVER_URL_PREFIX) + "forms/input_form/"

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
                c.Heading(text=settings.SITE_TITLE, level=2, class_name="+ text-danger"),
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
                    components=[c.Paragraph(text="3. Select endpoints and link")],
                    on_click=GoToEvent(url=selecta_url),
                ),
                c.Link(
                    components=[c.Paragraph(text="3. (NEW) Select endpoints with input form")],
                    on_click=GoToEvent(url=input_form_url),
                ),
                c.Heading(text="Overview", level=3),
                c.Link(
                    components=[c.Paragraph(text="Query existing connections from NSI Aggregator")],
                    on_click=GoToEvent(url=query_url),
                ),
                c.Link(
                    components=[c.Paragraph(text="Show database tables")],
                    on_click=GoToEvent(url=database_url),
                ),
                create_footer(),
            ]
        ),
    ]


# Reload topologies from NSI-DDS
@router.get("/api/reload-topos/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_reload_topos() -> list[AnyComponent]:
    """Reload topos from NSI-Orchestrator"""
    click_url = str(settings.SERVER_URL_PREFIX) + ""  # back to landing
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
        # global_soap_provider_url = orchestrator_dict["services"][SOAP_PROVIDER_MIME_TYPE]

        # upas = []
        local_discoveries = []
        disccount = 1

        upas_list_as_string = ""

        documents = dds_documents_dict["documents"]
        for upa_id in documents.keys():
            document = documents[upa_id]

            if upa_id != aura.state.global_provider_nsa_id:
                upas_list_as_string += upa_id + ", "

            print("fastapi_reload_topos: Adding to Datamodel", upa_id)
            discovery_obj = discoverydict2model(disccount, document["discovery"])
            local_discoveries.append(discovery_obj)
            disccount += 1

        # TODO: implement link details
        root_url = str(settings.SERVER_URL_PREFIX) + ""
        clickurl = root_url

    except Exception:
        traceback.print_exc()

        # Going offline
        aura.state.ONLINE = False

        raise HTTPException(status_code=404, detail="Endpoint or link not found")

    complist = [
        c.Heading(text="NSI Reload Topologies", level=2, class_name="+ text-danger"),
        c.Link(components=[c.Paragraph(text="Back")], on_click=GoToEvent(url=root_url)),
        c.Paragraph(text="Loaded Aggregator and uPA information", class_name="+ text-success"),
        c.Heading(text="Connected to Aggregator", level=4),
        c.Paragraph(text=aura.state.global_provider_nsa_id, class_name="+ text-warning"),
        # c.Heading(text="Found the following domains / uPAs", level=4),
        # c.Paragraph(text=upas_list_as_string, class_name="+ text-success"),
    ]
    complist.extend(add_discovery_table("Found Agents", clickurl, local_discoveries, 4))
    complist.extend(add_links_table("ANA Links Found", clickurl, aura.state.global_links, 3))
    # complist.append(create_footer())

    page = c.Page(components=complist)

    return [page]


# /api/selecta/ MUST END IN SLASH
@router.get("/api/selecta/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_select_a() -> list[AnyComponent]:
    """Show a table of four endpoints, `/api` is the endpoint the frontend will connect to
    when a endpoint visits `/` to fetch components to render.
    """
    try:

        logger.debug("DEBUG: /api/selecta/ ENTER")

        # Arno: id refers to id of item in table as shown.
        # NOTE: relative to /api ...!
        try:
            complist = show_endpoints_table("Select endpoint A", "/selectz/?epida={id}", aura.state.global_endpoints)
        except:
            traceback.print_exc()

        logger.debug("DEBUG: /api/selecta/ create complist")

        query_url = str(settings.SERVER_URL_PREFIX) + "query/"
        # querycomp = c.Link(components=[c.Text(text='Query existing connections from NSI Aggregator')], on_click=GoToEvent(url=query_url))
        # complist.append(querycomp)

        logger.debug("DEBUG: /api/selecta/ return complist")

        return complist
    except Exception:
        raise HTTPException(status_code=404, detail="Landing page not found")


@router.get("/api/selectz/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_select_z(epida: int) -> list[AnyComponent]:
    """Show a table of four endpoints, `/api` is the endpoint the frontend will connect to
    when a endpoint visits `/` to fetch components to render.
    """
    logger.debug("DEBUG: /api/selectz/ ENTER")

    # NOTE: relative to /api...!
    clickurl = "/selectlink/?epida=" + str(epida) + "&epidz={id}"

    logger.debug("DEBUG: URL template" + clickurl)

    return show_endpoints_table("Select endpoint Z", clickurl, aura.state.global_endpoints)


@router.get("/api/selectlink/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_select_link(epida: int, epidz: int) -> list[AnyComponent]:
    """Show a table of links, on click goto Reserve page"""
    logger.debug("DEBUG: /api/selectlink/ ENTER")

    # NOTE: relative to /api...!
    clickurl = "/reserve/?epida=" + str(epida) + "&epidz=" + str(epidz) + "&linkid={id}"

    logger.debug("DEBUG: URL template" + clickurl)

    return show_links_table("Select ANA link", clickurl, aura.state.global_links)


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


@router.get("/api/poll/", response_model=FastUI, response_model_exclude_none=True)
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
        aura.state.pollcount += 1
        text = "Received poll from GUI #" + str(aura.state.pollcount)

        # We got poll from GUI, now process it
        # SECURITY: fastAPI has made sure these are UUIDs
        clean_correlation_uuid_str = str(corruuid)
        # currently not used, could use for sanity checking
        clean_connection_id_str = str(connid)

        print("poll: Polling for", clean_correlation_uuid_str)

        poll_again = True
        complist = []
        body = None
        with aura.state.global_orch_async_replies_lock:
            if clean_correlation_uuid_str in aura.state.global_orch_async_replies_dict.keys():
                # Consume reply from queue
                body = aura.state.global_orch_async_replies_dict[clean_correlation_uuid_str]
                aura.state.global_orch_async_replies_dict.pop(clean_correlation_uuid_str, None)

                # Control GUI
                poll_again = False
                text = text + ": got reply!"
        # Release lock ASAP

        if not aura.state.ONLINE:
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


@router.post("/api/callback/")
async def orchestrator_general_callback(request: Request):
    """Orchestrator POSTs async reply to AuRA. Hence AuRA needs to run on reachable IP
    reply is stored in global_orch_async_replies_dict by correlationId
    Returns nothing
    """
    print("CALLBACK: ENTER")
    body = await request.body()
    # body = request.body()
    print("CALLBACK: Got body", body)

    content_type = request.headers["content-type"]
    if content_type_is_valid_soap(content_type):
        try:
            correlation_uuid_str = nsi_soap_parse_callback(body)
            with aura.state.global_orch_async_replies_lock:
                print("CALLBACK: Got lock")
                aura.state.global_orch_async_replies_dict[correlation_uuid_str] = body
        except:
            traceback.print_exc()
    else:
        print("CALLBACK: Orchestrator did not return XML, but #" + request.headers["content-type"] + "#")

    # TODO: reply from example
    return ["Rick", "Morty"]


#
# GUI Send NSI RESERVE
#
@router.get("/api/reserve/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_reserve(epida: int, epidz: int, linkid: int) -> list[AnyComponent]:
    """NSI RESERVE"""
    try:
        print("fastapi_nsi_reserve: ENTER")

        endpointa = next(u for u in aura.state.global_endpoints if u.id == epida)
        endpointz = next(u for u in aura.state.global_endpoints if u.id == epidz)
        link = next(u for u in aura.state.global_links if u.id == linkid)

        # duration_td = timedelta(days=30)
        duration_td = timedelta(minutes=5)

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

        # orch_reply_to_url = str(settings.SERVER_URL_PREFIX)+"/callback/?corruuid="+clean_correlation_uuid_str+"&connid="+clean_connection_id_str
        # orch_reply_to_url = str(settings.SERVER_URL_PREFIX)+"/callback/?corruuid="+clean_correlation_uuid_str
        orch_reply_to_url = str(settings.NSA_BASE_URL) + "/api/callback/"

        print("fastapi_nsi_reserve: Orch will reply via", orch_reply_to_url)
        print("aura.state.global_soap_provider_url:", aura.state.global_soap_provider_url)

        # Fake data for off-line, to be overwritten
        reserve_reply_dict = {}
        reserve_reply_dict[S_FAULTSTRING_TAG] = "Agent unreachable, demo mode"
        reserve_reply_dict["correlationId"] = clean_correlation_uuid_str  # DUMMY_CORRELATION_ID_STR
        reserve_reply_dict["globalReservationId"] = DUMMY_GLOBAL_RESERVATION_ID_STR
        reserve_reply_dict["connectionId"] = DUMMY_CONNECTION_ID_STR

        # Call NSI, wait for sync HTTP reply
        if aura.state.ONLINE:
            reserve_reply_dict = nsi_reserve(
                aura.state.global_soap_provider_url,
                correlation_uuid_py,
                orch_reply_to_url,
                aura.state.global_provider_nsa_id,
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

        root_url = str(settings.SERVER_URL_PREFIX) + ""

        # To inspect the spans that were stitched together
        query_rec_url = (
            str(settings.SERVER_URL_PREFIX) + "query-recursive/?connid=" + reserve_reply_dict["connectionId"]
        )

        # For simulation, no /api
        sim_reply_to_url = (
            str(settings.SERVER_URL_PREFIX) + "reserve-commit/?connid=" + reserve_reply_dict["connectionId"]
        )

        print("ARNO: fastapi_nsi_reserve: URLS", root_url, query_rec_url, sim_reply_to_url)

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
@router.get("/api/reserve-commit/", response_model=FastUI, response_model_exclude_none=True)
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

        if aura.state.ONLINE:
            reserve_commit_reply_dict = nsi_reserve_commit(
                aura.state.global_soap_provider_url,
                str(settings.SERVER_URL_PREFIX),
                aura.state.global_provider_nsa_id,
                clean_connection_id_str,
            )

        # RESTFUL: Do Not Store (TODO or for security)
        # TODO NEWCALLBACK
        orch_reply_to_url = (
            str(settings.NSA_BASE_URL)
            + "reserve-commit-callback/?corruuid="
            + reserve_commit_reply_dict["correlationId"]
            # + "&globresuuid="
            # + reserve_commit_reply_dict["globalReservationId"]
            # + "&connid="
            # + clean_connection_id_str
        )

        # Check for errors
        if reserve_commit_reply_dict[S_FAULTSTRING_TAG] is None:
            # Success
            cssclassname = "+ text-success"
            faultstring = "Success"
        else:
            cssclassname = "+ text-warning"
            faultstring = reserve_commit_reply_dict[S_FAULTSTRING_TAG]

        root_url = str(settings.SERVER_URL_PREFIX) + ""

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
@router.get("/api/reserve-commit-callback/", response_model=FastUI, response_model_exclude_none=True)
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

        if aura.state.ONLINE:
            provision_reply_dict = nsi_provision(
                aura.state.global_soap_provider_url,
                str(settings.NSA_BASE_URL),
                aura.state.global_provider_nsa_id,
                expect_global_reservation_uuid_py,
            )

        # RESTFUL: Do Not Store (TODO or for security)
        orch_reply_to_url = (
            str(settings.NSA_BASE_URL)
            + "provision-callback/?corruuid="
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

        root_url = str(settings.SERVER_URL_PREFIX) + ""

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
@router.get("/api/provision-callback/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_provision_callback(corruuid: str, globresuuid: str) -> list[AnyComponent]:
    """NSI PROVISION callback, Go Back to Start, or Show List

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        print("fastapi_nsi_provision_callback: ENTER")

        correlation_uuid_py = uuid.UUID(corruuid)
        aura.state.global_reservation_uuid_py = str(uuid.UUID(corruuid))

        root_url = str(settings.SERVER_URL_PREFIX) + ""
        query_url = str(settings.SERVER_URL_PREFIX) + "query/"

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
@router.get("/api/query/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_nsi_connections_query() -> list[AnyComponent]:
    """NSI Query, Go Back to Start"""
    print("fastapi_nsi_connections_query: ENTER")
    click_url = "/reservation-details/?id={id}"
    try:
        if aura.state.ONLINE:
            resdictlist = nsi_connections_query(
                aura.state.global_soap_provider_url,
                str(settings.SERVER_URL_PREFIX),
                aura.state.global_provider_nsa_id,
            )

            print("fastapi_nsi_connections_query: Got reservations", resdictlist)

            # Turn into Model
            nsi_load_parsed_soap_into_reservations_model(resdictlist)

            logger.debug("fastapi_nsi_connections_query: UPDATED reservations Model")
            print("fastapi_nsi_connections_query: UPDATED reservations Model")

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail="QUERY query param not found")

    return show_reservations_table("NSI Current Reservations", click_url, aura.state.global_reservations)


#
# TODO: CHECK IF THERE IS ANY CALLBACK ON A QUERY
#


# NSI QUERY SUMMARY SYNC callback
#
# TODO: UNUSED?
#
@router.get("/api/query-callback/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_connections_query_callback(corruuid: str) -> list[AnyComponent]:
    """NSI QUERY callback, Go Back to Start, or Redo query

    # TODO: check input uuid str
    # TODO: check reply in body
    """
    try:
        correlation_uuid_py = uuid.UUID(corruuid)

        root_url = str(settings.SERVER_URL_PREFIX) + ""
        query_url = str(settings.SERVER_URL_PREFIX) + "query/"

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
@router.get("/api/terminate/", response_model=FastUI, response_model_exclude_none=True)
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

        if aura.state.ONLINE:
            terminate_reply_dict = nsi_terminate(
                aura.state.global_soap_provider_url,
                str(settings.SERVER_URL_PREFIX),
                aura.state.global_provider_nsa_id,
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
            str(settings.NSA_BASE_URL)
            + "terminate-callback/?corruuid="
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
@router.get("/api/release/", response_model=FastUI, response_model_exclude_none=True)
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
        if aura.state.ONLINE:
            release_reply_dict = nsi_release(
                aura.state.global_soap_provider_url,
                str(settings.SERVER_URL_PREFIX),
                aura.state.global_provider_nsa_id,
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
            str(settings.NSA_BASE_URL)
            + "release-callback/?corruuid="
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
@router.get("/api/reserve-timeout-ack/", response_model=FastUI, response_model_exclude_none=True)
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
        if aura.state.ONLINE:
            reserve_timeout_ack_reply_dict = nsi_reserve_timeout_ack(
                aura.state.global_soap_provider_url,
                str(settings.SERVER_URL_PREFIX),
                aura.state.global_provider_nsa_id,
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
            str(settings.NSA_BASE_URL)
            + "reserve_timeout_ack-callback/?corruuid="
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
@router.get("/api/query-recursive/", response_model=FastUI, response_model_exclude_none=True)
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

        orch_reply_to_url = str(settings.NSA_BASE_URL) + "api/callback/"

        print("fastapi_nsi_query_recursive: Orch will reply via", orch_reply_to_url)

        if aura.state.ONLINE:
            query_recursive_reply_dict = nsi_query_recursive(
                aura.state.global_soap_provider_url,
                orch_reply_to_url,
                aura.state.global_provider_nsa_id,
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
        next_step_url = str(settings.SERVER_URL_PREFIX) + "reserve-commit/?connid=" + expect_connection_id_str

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
@router.get("/api/endpoint/{endpoint_id}/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_profile_orig(endpoint_id: int) -> list[AnyComponent]:
    """Endpoint profile page, the frontend will fetch this when the endpoint visits `/endpoint/{id}/`."""
    try:
        endpoint = next(u for u in aura.state.global_endpoints if u.id == endpoint_id)
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
@router.get("/api/endpoint-details/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_endpoint_profile(id: int) -> list[AnyComponent]:
    """Endpoint profile page, the frontend will fetch this when the endpoint visits `/endpoint/{id}/`."""
    try:
        endpoint = next(u for u in aura.state.global_endpoints if u.id == id)
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
@router.get("/api/reservation-details/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_reservation_profile(id: int) -> list[AnyComponent]:
    """Reservation profile page, the frontend will fetch this when the endpoint visits `/endpoint/?id={id}`."""
    try:
        logger.debug("fastapi_reservation_profile: ENTER")

        reservation = next(u for u in aura.state.global_reservations if u.id == id)

        headtext = "ConnectionId " + reservation.connectionId

        terminate_url = str(settings.SERVER_URL_PREFIX) + "terminate/?connid=" + reservation.connectionId
        release_url = str(settings.SERVER_URL_PREFIX) + "release/?connid=" + reservation.connectionId
        reserve_timeout_ack_url = (
            str(settings.SERVER_URL_PREFIX) + "reserve-timeout-ack/?connid=" + reservation.connectionId
        )
        query_recursive_url = str(settings.SERVER_URL_PREFIX) + "query-recursive/?connid=" + reservation.connectionId

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


# Arno: TODO move down to all router
# @router.post("/login")
@router.get("/api/login/")
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


# @router.post("/logout")
@router.get("/api/logout/")
async def session_logout(request: Request):
    session_id = request.cookies.get("Authorization")
    request.delete_cookie(key="Authorization")
    SESSION_DB.pop(session_id, None)
    return {"status": "logged out"}


# @router.get("/", dependencies=[Depends(get_auth_user)])
# async def secret():
#    return {"secret": "info"}


# Tutorial


@router.get("/{path:path}")
async def html_landing() -> HTMLResponse:
    """Simple HTML page which serves the React app, comes last as it matches all paths."""
    return HTMLResponse(prebuilt_html(title=settings.SITE_TITLE))
