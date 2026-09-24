"""Build hooks for the documentation site in mkdocs.yml.

The source documents link to agent-facing pages, decision records and planning notes that stay
in the repository and are never published. On the site those links become their plain text, so
the source keeps linking correctly for a reader of the repository.

A link is unlinked only when its target is known not to be published: a document elsewhere in the
repository, a file under docs/ that exists and is excluded, or one of the documents the root
.gitignore keeps local, which a clean checkout does not have. Any other missing target is left
alone, so a broken link still fails the strict build.
"""

import re
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlsplit

from griffe import Extension, Object

MARKDOWN_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]]+)\]\((?P<target>[^)\s]+)\)")
FENCE = re.compile(r"^\s*(```|~~~)")
SPHINX_ROLE = re.compile(
   r":(?:class|meth|attr|func|exc|data|mod|obj):`(?P<tilde>~?)(?P<target>[^`]+)`"
)

LOCAL_ONLY_DOCS = (
   "README.md",
   "build-plan.md",
   "conventions.md",
   "roadmap.md",
   "engineering/*",
)


def is_published(docs_relative: str, files) -> bool:
   site_file = files.get_file_from_path(docs_relative)

   return site_file is not None and not site_file.inclusion.is_excluded()


def is_known_unpublished(target_path: Path, docs_dir: Path, files) -> bool:
   repository_root = docs_dir.parent.parent
   is_inside_docs = target_path.is_relative_to(docs_dir)
   is_inside_repository = target_path.is_relative_to(repository_root)

   if not is_inside_docs:
      return is_inside_repository

   docs_relative = target_path.relative_to(docs_dir).as_posix()

   if is_published(docs_relative, files):
      return False

   is_kept_local = any(fnmatch(docs_relative, pattern) for pattern in LOCAL_ONLY_DOCS)

   return target_path.exists() or is_kept_local


def unlink_unpublished(line: str, page_dir: Path, docs_dir: Path, files) -> str:
   def replace(match: re.Match[str]) -> str:
      target = urlsplit(match["target"])
      is_local_path = not target.scheme and not target.netloc and target.path != ""

      if not is_local_path:
         return match[0]

      target_path = (page_dir / target.path).resolve()

      if is_known_unpublished(target_path, docs_dir, files):
         return match["text"]

      return match[0]

   return MARKDOWN_LINK.sub(replace, line)


def on_page_markdown(markdown, page, config, files):
   docs_dir = Path(config["docs_dir"]).resolve()
   page_dir = (docs_dir / page.file.src_path).parent
   inside_fence = False
   rewritten = []

   for line in markdown.splitlines(keepends=True):
      if FENCE.match(line):
         inside_fence = not inside_fence

      if inside_fence:
         rewritten.append(line)
         continue

      rewritten.append(unlink_unpublished(line, page_dir, docs_dir, files))

   return "".join(rewritten)


def sphinx_role_as_code(match: re.Match[str]) -> str:
   target = match["target"]
   display = target.rsplit(".", 1)[-1] if match["tilde"] else target

   return f"`{display}`"


class SphinxRolesAsCode(Extension):
   """The public docstrings cross-reference with Sphinx roles, which Markdown does not read.
   Each role is rendered as a code span holding the name it points at."""

   def on_instance(self, *, obj: Object, **kwargs) -> None:
      if obj.docstring is None:
         return

      obj.docstring.value = SPHINX_ROLE.sub(sphinx_role_as_code, obj.docstring.value)
