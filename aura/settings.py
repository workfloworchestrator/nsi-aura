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

from pydantic import FilePath
from pydantic.networks import HttpUrl
from pydantic_settings import BaseSettings

#
# Settings
#


class Settings(BaseSettings):
    """Aura application settings."""

    SITE_TITLE: str = "AuRA - NSI uRA for Federating ANA"
    # SITE_TITLE = 'AuRA - NSI ultimate Requester Agent for ANA'

    #
    # NSI Orchestrator
    #
    # GLOBAL_ORCHESTRATOR_URL='https://supa.moxy.ana.dlp.surfnet.nl:443'
    ## Test with bad URL
    # GLOBAL_ORCHESTRATOR_URL='https://nosupa.moxy.ana.dlp.surfnet.nl'
    # GLOBAL_ORCHESTRATOR_DISCOVERY_PATH='/discovery'

    # DEMO_PROVIDER_NSA_ID='urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:nsa:supa'

    ANAGRAM_DDS_URL: HttpUrl = "https://dds.ana.dlp.surfnet.nl/dds/"

    UPA_URN_PREFIX: str = "urn:ogf:network:"

    DEFAULT_LINK_DOMAIN: str = "ANA"

    # apparently cannot dynamically figure out?
    SERVER_URL_PREFIX: HttpUrl = "http://127.0.0.1:8000"
    # str(str(settings.SERVER_URL_PREFIX))="http://145.100.104.178:8000"

    # certificate en key to authenticate against NSI control plane
    NSI_AURA_CERTIFICATE: FilePath = "aura-certificate.pem"
    NSI_AURA_PRIVATE_KEY: FilePath = "aura-private-key.pem"


settings = Settings(_env_file="aura.env")
