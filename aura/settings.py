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

from pydantic import DirectoryPath, FilePath
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

    ANAGRAM_DDS_URL: HttpUrl = HttpUrl("https://dds.ana.dlp.surfnet.nl/dds/")

    UPA_URN_PREFIX: str = "urn:ogf:network:"

    DEFAULT_LINK_DOMAIN: str = "ANA"

    # apparently cannot dynamically figure out?
    # NOTE: HttpUrl class will automatically add trailing / when converting to str
    SERVER_URL_PREFIX: HttpUrl = HttpUrl("http://127.0.0.1:8000")
    # str(str(settings.SERVER_URL_PREFIX))="http://145.100.104.178:8000"

    # certificate en key to authenticate against NSI control plane
    NSI_AURA_CERTIFICATE: FilePath = FilePath("aura-certificate.pem")
    NSI_AURA_PRIVATE_KEY: FilePath = FilePath("aura-private-key.pem")

    # database directory, may be relative or absolute
    DATABASE_DIRECTORY: DirectoryPath = DirectoryPath("db")

    # directory containing static files, such as images and SOAP templates
    # TODO: make sure all code uses this, see nsi_comm_init() kludge
    STATIC_DIRECTORY: DirectoryPath = DirectoryPath("static")

    # nsi-aura (external) URL (scheme, host, port, prefix)
    NSA_SCHEME: str = "http"
    NSA_HOST: str = "localhost"
    NSA_PORT: str = "8000"
    NSA_PATH_PREFIX: str = ""

    # NOTE: HttpUrl class will automatically add trailing / when converting to str
    @property
    def NSA_BASE_URL(self):
        """External base URL of this NSA."""
        return HttpUrl(f"{self.NSA_SCHEME}://{self.NSA_HOST}:{self.NSA_PORT}{self.NSA_PATH_PREFIX}")

    # Logging
    SQL_LOGGING: bool = False


settings = Settings(_env_file="aura.env")
