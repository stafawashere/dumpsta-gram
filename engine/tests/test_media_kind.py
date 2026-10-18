"""MediaKind and the media_kind property on every model that carries ``media_type``.

The app read the upstream's numbers itself until release phase 3, which was Instagram knowledge
outside the engine. These gates hold the numbers here, and hold that no model carrying
``media_type`` lacks the typed kind beside it.
"""

from __future__ import annotations

import dataclasses
import inspect
from types import SimpleNamespace

import pytest

import dumpstagram
from dumpstagram import MediaKind


@pytest.mark.parametrize(
   ("media_type", "kind"),
   [(1, MediaKind.PHOTO), (2, MediaKind.VIDEO), (8, MediaKind.CAROUSEL)],
)
def test_the_three_measured_numbers_name_their_kind(media_type: int, kind: MediaKind) -> None:
   assert MediaKind.from_media_type(media_type) is kind


@pytest.mark.parametrize("media_type", [0, 3, 7, 9, -1, 11])
def test_any_other_number_is_other_not_a_guess(media_type: int) -> None:
   assert MediaKind.from_media_type(media_type) is MediaKind.OTHER


def _models_with_media_type() -> list[type]:
   models = []

   for name in dumpstagram.__all__:
      member = getattr(dumpstagram, name)
      if not (inspect.isclass(member) and dataclasses.is_dataclass(member)):
         continue

      if any(field.name == "media_type" for field in dataclasses.fields(member)):
         models.append(member)

   return models


def test_the_public_models_carrying_media_type_are_the_nine_known() -> None:
   names = sorted(model.__name__ for model in _models_with_media_type())

   assert names == [
      "CarouselChild",
      "Post",
      "PostDetail",
      "PostThumbnail",
      "PublishedPost",
      "ReelThumbnail",
      "SavedPost",
      "SearchPost",
      "StoryItem",
   ]


@pytest.mark.parametrize("model", _models_with_media_type(), ids=lambda model: model.__name__)
def test_every_model_with_media_type_reads_it_as_a_kind(model: type) -> None:
   prop = inspect.getattr_static(model, "media_kind", None)

   assert isinstance(prop, property)
   assert prop.fget is not None
   assert prop.fget(SimpleNamespace(media_type=2)) is MediaKind.VIDEO
   assert prop.fget(SimpleNamespace(media_type=8)) is MediaKind.CAROUSEL
   assert prop.fget(SimpleNamespace(media_type=4)) is MediaKind.OTHER
