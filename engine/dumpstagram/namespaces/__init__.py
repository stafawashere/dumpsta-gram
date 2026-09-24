"""The domain namespaces both clients carry: ``client.direct``, ``client.feeds``,
``client.media``, ``client.profiles`` and ``client.social``.

Each one is a small hand-written object over one client, per rulings W1, W2 and W19 in
``docs/web-parity-plan.md``, and each module holds the awaitable namespace beside its blocking
twin. A capability is documented here and reaches ``_core`` from here. The flat methods on
:class:`~dumpstagram.aio.AsyncClient` and :class:`~dumpstagram.client.SyncClient` stay, and
answer identically through these.

Nothing is re-exported, so a name is imported from the module that defines it.
"""

__all__: list[str] = []
