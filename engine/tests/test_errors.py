"""Gates on the shape of the public exception hierarchy.

The retry path in `_core` will accept only members of `RETRYABLE`, so these assertions are
what make the checkpoint exclusion structural rather than conventional.
"""

import inspect

from dumpstagram import errors


def public_error_classes() -> list[type[BaseException]]:
   found: list[type[BaseException]] = []

   for name, cls in inspect.getmembers(errors, inspect.isclass):
      is_exception = issubclass(cls, BaseException)
      is_public = not name.startswith("_")

      if is_exception and is_public:
         found.append(cls)

   return found


def test_checkpoint_is_absent_from_the_retryable_set() -> None:
   """A retried challenge escalates a soft block into a locked account."""
   assert errors.CheckpointRequired not in errors.RETRYABLE


def test_checkpoint_inherits_from_no_retryable_type() -> None:
   """Membership is checked with issubclass, so reparenting would smuggle it back in."""
   for retryable in errors.RETRYABLE:
      assert not issubclass(errors.CheckpointRequired, retryable)


def test_retryable_set_is_exactly_the_two_decided_types() -> None:
   """Widening the retry surface is an account-safety decision, not a refactor."""
   assert errors.RETRYABLE == (errors.TransportFailure, errors.RateLimited)


def test_every_public_error_descends_from_the_base() -> None:
   """A caller catching DumpstagramError must not miss a later addition."""
   for cls in public_error_classes():
      assert issubclass(cls, errors.DumpstagramError)


def test_all_declares_every_public_error() -> None:
   """An error class missing from __all__ is one the package does not re-export."""
   declared = set(errors.__all__)

   for cls in public_error_classes():
      assert cls.__name__ in declared
