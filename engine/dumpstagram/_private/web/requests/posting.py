"""The post requests: a photo upload, the publish of one photo or of a carousel, and a delete.

These are the first requests the engine sends that are not the GraphQL form envelope. The
upload goes to its own host, carries the file as the body and names everything else in
headers. The two publishes are REST calls on the web API, the single one form encoded and the
carousel one JSON, and the delete is the comet form the post page sends.

Findings: ``upload-a-photo-for-a-post``, ``publish-a-photo-post``, ``publish-a-carousel-post``
and ``delete-my-own-post`` in the knowledge base.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.requests.common import jazoest_for
from dumpstagram._private.web.requests.media import post_url
from dumpstagram.errors import AuthenticationFailed
from dumpstagram.session import Session

__all__ = [
   "UPLOAD_HOST",
   "UploadedImage",
   "build_carousel_publish_request",
   "build_delete_post_request",
   "build_photo_publish_request",
   "build_photo_upload_request",
   "is_an_upload_id",
]

UPLOAD_HOST = "i.instagram.com"
"""The host a photo upload goes to. Only the upload, every other post request is on www."""

_UPLOAD_URL = "https://i.instagram.com/rupload_igphoto/fb_uploader_{upload_id}"

_PHOTO_PUBLISH_URL = "https://www.instagram.com/api/v1/media/configure/"

_CAROUSEL_PUBLISH_URL = "https://www.instagram.com/api/v1/media/configure_sidecar/"

_DELETE_POST_URL = "https://www.instagram.com/api/v1/web/create/{media_id}/delete/"

_PHOTO_MEDIA_TYPE = 1
"""What the upload's parameters call an image, the only kind uploaded here."""

_DELETE_ROUTE = "comet.igweb.PolarisDesktopPostRoute"
"""The page the delete is sent from, as the post page names itself in ``__crn``."""

_UPLOAD_ID = re.compile(r"[0-9]{1,20}")

_ASBD_ID = "359341"


@dataclass(frozen=True)
class UploadedImage:
   """One image as its upload names it: the bytes and what the upload says about them."""

   upload_id: str
   content: bytes
   content_type: str
   width: int
   height: int


def is_an_upload_id(value: str) -> bool:
   """Whether ``value`` has the shape of an upload id, the millisecond clock as digits."""

   return _UPLOAD_ID.fullmatch(value) is not None


def build_photo_upload_request(
   session: Session,
   image: UploadedImage,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Upload one image, the whole file at offset 0, the way the composer uploads a slide.

   The browser sends it cross site from the www page with credentials, so the cookies go and
   ``x-csrftoken`` does not. The composer's own uploader leaves out the claim and device
   headers, and so does this.
   """

   if not is_an_upload_id(image.upload_id):
      raise ValueError(f"{image.upload_id!r} is not an upload id, which is digits only")

   entity_name = f"fb_uploader_{image.upload_id}"
   rupload_params = {
      "media_type": _PHOTO_MEDIA_TYPE,
      "upload_id": image.upload_id,
      "upload_media_height": image.height,
      "upload_media_width": image.width,
   }

   headers = {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": image.content_type,
      "offset": "0",
      "origin": ORIGIN,
      "referer": f"{ORIGIN}/",
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-site",
      "user-agent": user_agent,
      "x-asbd-id": _ASBD_ID,
      "x-entity-length": str(len(image.content)),
      "x-entity-name": entity_name,
      "x-entity-type": image.content_type,
      "x-ig-app-id": session.app_id or "",
      "x-instagram-ajax": _revision(session),
      "x-instagram-rupload-params": json.dumps(rupload_params, separators=(",", ":")),
   }

   return Request(
      method="POST",
      url=_UPLOAD_URL.format(upload_id=image.upload_id),
      headers=headers,
      content=image.content,
      follow_redirects=False,
   )


def build_photo_publish_request(
   session: Session,
   upload_id: str,
   caption: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Publish one uploaded image as a post, with the fields the composer's single branch sends
   for a photo with nothing added: no location, no tags, no collaborator, no sharing out."""

   token = _page_token(session)

   if not is_an_upload_id(upload_id):
      raise ValueError(f"{upload_id!r} is not an upload id, which is digits only")

   fields = {
      "archive_only": "false",
      "caption": caption,
      "clips_share_preview_to_feed": "1",
      "disable_comments": "0",
      "igtv_share_preview_to_feed": "1",
      "is_unified_video": "1",
      "like_and_view_counts_disabled": "0",
      "media_share_flow": "creation_flow",
      "share_to_facebook": "",
      "share_to_fb_destination_type": "USER",
      "source_type": "library",
      "upload_id": upload_id,
      "video_subtitles_enabled": "0",
      "jazoest": jazoest_for(token),
      "fb_dtsg": token,
   }

   return Request(
      method="POST",
      url=_PHOTO_PUBLISH_URL,
      headers=_publish_headers(session, "application/x-www-form-urlencoded", user_agent),
      content=urlencode(fields).encode("utf-8"),
      follow_redirects=False,
   )


def build_carousel_publish_request(
   session: Session,
   upload_ids: list[str],
   caption: str,
   *,
   client_sidecar_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Publish several uploaded images as one carousel, as the composer's Share sent it.

   The body is JSON in the key order the composer wrote, the page token inside it.
   """

   token = _page_token(session)

   for upload_id in [*upload_ids, client_sidecar_id]:
      if not is_an_upload_id(upload_id):
         raise ValueError(f"{upload_id!r} is not an upload id, which is digits only")

   body = {
      "archive_only": False,
      "caption": caption,
      "children_metadata": [{"upload_id": upload_id} for upload_id in upload_ids],
      "client_sidecar_id": client_sidecar_id,
      "disable_comments": "0",
      "is_open_to_public_submission": False,
      "like_and_view_counts_disabled": 0,
      "media_share_flow": "creation_flow",
      "share_to_facebook": "",
      "share_to_fb_destination_type": "USER",
      "source_type": "library",
      "jazoest": jazoest_for(token),
      "fb_dtsg": token,
   }

   return Request(
      method="POST",
      url=_CAROUSEL_PUBLISH_URL,
      headers=_publish_headers(session, "application/json", user_agent),
      content=json.dumps(body, separators=(",", ":")).encode("utf-8"),
      follow_redirects=False,
   )


def build_delete_post_request(
   session: Session,
   media_id: str,
   code: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Delete the viewer's own post, named by its ``<pk>_<owner id>`` form, from its page.

   The body is the comet form the post page sends, without the fields the engine has never
   produced (``__s``, ``__dyn``, ``__csr`` and the rest), the same subset the GraphQL form
   sends. It carries no ``x-csrftoken``, because the page's request did not.
   """

   token = _page_token(session)
   spin = session.spin
   revision = _revision(session)

   fields = {
      "__d": "www",
      "__user": "0",
      "__a": "1",
      "__req": "1",
      "__hs": session.haste_session or "",
      "dpr": "2",
      "__ccg": "EXCELLENT",
      "__rev": revision,
      "__hsi": session.hsi or "",
      "__comet_req": "7",
      "fb_dtsg": token,
      "jazoest": jazoest_for(token),
      "lsd": session.lsd or "",
      "__spin_r": revision,
      "__spin_b": (spin.branch if spin is not None else None) or "",
      "__spin_t": (spin.timestamp if spin is not None else None) or "",
      "__crn": _DELETE_ROUTE,
   }

   headers = {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": "application/x-www-form-urlencoded",
      "origin": ORIGIN,
      "referer": post_url(code),
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": user_agent,
      "x-asbd-id": _ASBD_ID,
      "x-fb-lsd": session.lsd or "",
      "x-ig-d": "www",
   }

   return Request(
      method="POST",
      url=_DELETE_POST_URL.format(media_id=media_id),
      headers=headers,
      content=urlencode(fields).encode("utf-8"),
      follow_redirects=False,
   )


def _publish_headers(session: Session, content_type: str, user_agent: str) -> dict[str, str]:
   return {
      "accept": "*/*",
      "accept-language": "en-US,en;q=0.9",
      "content-type": content_type,
      "origin": ORIGIN,
      "referer": f"{ORIGIN}/",
      "sec-fetch-dest": "empty",
      "sec-fetch-mode": "cors",
      "sec-fetch-site": "same-origin",
      "user-agent": user_agent,
      "x-asbd-id": _ASBD_ID,
      "x-csrftoken": session.csrftoken,
      "x-ig-app-id": session.app_id or "",
      "x-instagram-ajax": _revision(session),
      "x-requested-with": "XMLHttpRequest",
   }


def _page_token(session: Session) -> str:
   if not session.fb_dtsg:
      raise AuthenticationFailed(
         "session has no fb_dtsg, so it has not been bootstrapped since it was loaded"
      )

   return session.fb_dtsg


def _revision(session: Session) -> str:
   spin = session.spin

   return (spin.revision if spin is not None else None) or ""
