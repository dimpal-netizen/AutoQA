"""The Chrome extension: what version this server ships, and the download.

Both routes are public. A download link is an `<a href>`, which cannot carry a
bearer token, and the zip holds nothing that needs one - the extension's own
source and the API address, which anyone using the web app already has. The
recordings it makes are authenticated the ordinary way, when the tester signs
in to it.
"""

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from app.core.config import settings
from app.services import extension_service

router = APIRouter(prefix="/extension", tags=["extension"])


class ExtensionInfo(BaseModel):
    version: str
    #: The oldest version this server accepts recordings from.
    minimum_version: str
    #: Where the web app links to. Relative to the API prefix, ready to append
    #: `?api_url=` to.
    download_path: str


@router.get("", response_model=ExtensionInfo)
def extension_info() -> ExtensionInfo:
    return ExtensionInfo(
        version=extension_service.version(),
        minimum_version=extension_service.MINIMUM_VERSION,
        download_path=f"{settings.API_V1_PREFIX}/extension/download",
    )


@router.get("/download")
def download_extension(
    request: Request,
    api_url: str | None = Query(
        default=None,
        description=(
            "The API address to bake into the extension. Defaults to the "
            "address this request arrived at."
        ),
    ),
) -> Response:
    """The extension as a zip, configured to talk to this server.

    The web app passes the API address it uses itself, because that is by
    definition one a visitor's browser can reach. Behind a reverse proxy the
    address this request appears to have arrived at is often the internal one.
    """
    if not api_url:
        api_url = f"{request.url.scheme}://{request.url.netloc}{settings.API_V1_PREFIX}"

    archive = extension_service.build_zip(api_url)
    filename = f"autoqa-recorder-{extension_service.version()}.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
