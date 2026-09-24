"""The page's compiled JavaScript, read for the ``doc_id`` each operation compiles to.

A page document names the bundles its bootloader may load, each on :data:`STATIC_BUNDLE_HOST`
under ``/rsrc.php/``, most of them inside the ``rsrcMap`` of a ``Bootloader`` payload where every
slash is escaped. A bundle defines every Relay operation it carries as two modules: the artifact
``<Operation>.graphql``, and ``<Operation>_instagramRelayOperation``, whose whole body exports the
operation's ``doc_id`` as a string. The second is what :func:`compiled_operations` reads, so no
bundle is evaluated and nothing is fired.

A bundle is a static, public, immutable asset. A browser fetches it cross-site with no cookie,
so it is fetched here through a cookieless transport pinned to the static host, never through
the account's own.

Findings: ``static-js-bundle-fetch`` for the host and the request, and the pattern
``a-bundle-exports-each-operation-s-doc-id-from-its-own-module`` for the module shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, ORIGIN

__all__ = [
   "STATIC_BUNDLE_HOST",
   "CompiledOperations",
   "build_bundle_request",
   "bundle_urls",
   "compiled_operations",
]

STATIC_BUNDLE_HOST = "static.cdninstagram.com"
"""The one host a bundle is fetched from, and the one the bundle transport is pinned to.

Every script a home cold load fetched from a bundle path the document names sat on it, 45 and 59
on two loads of 2026-09-23. Scripts on ``static.xx.fbcdn.net`` were fetched too, 8 per load, but
the home document named none of them, so that host is not read.
"""

_SLASH = r"(?:\\/|/)"
_BUNDLE_URL = re.compile(
   r"https:"
   + _SLASH
   + _SLASH
   + re.escape(STATIC_BUNDLE_HOST)
   + _SLASH
   + r"rsrc\.php"
   + _SLASH
   + r"[A-Za-z0-9_,.\-]+(?:"
   + _SLASH
   + r"[A-Za-z0-9_,.\-]+)*\.js(?![A-Za-z0-9_])"
)

_OPERATION_ID_MODULE = re.compile(
   r'__d\("([A-Za-z0-9_]+)_instagramRelayOperation",\[\],'
   r'\(function\([A-Za-z0-9_$,]*\)\{[A-Za-z0-9_$]+\.exports="(\d+)"\}\)'
)
_OPERATION_ARTIFACT = re.compile(r'__d\("([A-Za-z0-9_]+)\.graphql"')


@dataclass(frozen=True)
class CompiledOperations:
   """What one bundle compiles: each operation's ``doc_id``, and every artifact it defines.

   ``doc_ids`` maps an operation name to every id found for it, because nothing observed says a
   name cannot carry two. ``artifacts`` names every ``.graphql`` module, which is how an
   operation whose artifact is present but whose id module did not match is told apart from one
   that is not in the bundle at all.
   """

   doc_ids: dict[str, frozenset[str]]
   artifacts: frozenset[str]


def bundle_urls(html: str) -> tuple[str, ...]:
   """Every bundle on :data:`STATIC_BUNDLE_HOST` a page document names, in document order, once.

   A script tag and a preload link name a bundle plainly, the bootloader's ``rsrcMap`` names it
   with every slash escaped, and both are read. The document is otherwise left alone: its inline
   scripts carry the session's tokens, and nothing here keeps any of it.
   """

   ordered: dict[str, None] = {}

   for match in _BUNDLE_URL.finditer(html):
      url = match.group(0).replace("\\/", "/")
      ordered.setdefault(url, None)

   return tuple(ordered)


def compiled_operations(bundle_text: str) -> CompiledOperations:
   """The operation to ``doc_id`` pairs one bundle defines, and every artifact name it holds."""

   doc_ids: dict[str, set[str]] = {}

   for match in _OPERATION_ID_MODULE.finditer(bundle_text):
      operation, doc_id = match.group(1), match.group(2)
      doc_ids.setdefault(operation, set()).add(doc_id)

   artifacts = frozenset(match.group(1) for match in _OPERATION_ARTIFACT.finditer(bundle_text))

   return CompiledOperations(
      doc_ids={operation: frozenset(found) for operation, found in doc_ids.items()},
      artifacts=artifacts,
   )


def build_bundle_request(url: str, user_agent: str = DEFAULT_USER_AGENT) -> Request:
   """One bundle, asked for the way the page asks for a script it preloads.

   The headers are the ones a browser sent on the bundle fetch captured on 2026-09-23 with its
   wire headers: ``origin`` and ``referer`` the site, ``sec-fetch-dest`` script, ``sec-fetch-mode``
   cors and ``sec-fetch-site`` cross-site, with no cookie. ``accept-encoding`` is left to the
   HTTP client, because advertising an encoding it cannot decode would hand the parser bytes.
   A redirect is not followed, since a bundle answered anywhere but where the document named it
   is not the bundle the document named.
   """

   return Request(
      method="GET",
      url=url,
      headers={
         "user-agent": user_agent,
         "accept": "*/*",
         "accept-language": "en-US,en;q=0.9",
         "origin": ORIGIN,
         "referer": f"{ORIGIN}/",
         "sec-fetch-dest": "script",
         "sec-fetch-mode": "cors",
         "sec-fetch-site": "cross-site",
      },
      follow_redirects=False,
   )
