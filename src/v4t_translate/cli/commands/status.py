"""``status``: where the project is, in one screen."""

from __future__ import annotations

import json

import click

from ...ops.status import ProjectStatus, project_status
from ..context import Context, pass_context

__all__ = ["status"]


@click.command()
@click.option("--locale", "-l", "locales", multiple=True,
              help="Only this language. Repeatable.")
@click.option("--json", "as_json", is_flag=True,
              help="Machine readable, for a release script.")
@click.option("--exit-code", is_flag=True,
              help="Exit 1 when anything is blocking a release. For CI.")
@pass_context
def status(context: Context, locales: tuple[str, ...], as_json: bool,
           exit_code: bool) -> None:
    """Say whether the project can ship, and what is stopping it."""
    result = project_status(context.config, locales=list(locales) or None)

    if as_json:
        click.echo(_to_json(result))
    else:
        _say(context, result)

    if exit_code and not result.can_ship:
        # Deliberately not CheckFailed. Nothing failed; the answer is no.
        raise SystemExit(1)


def _say(context: Context, result: ProjectStatus) -> None:
    context.say(result.verdict())
    context.say("")

    context.say(
        f"{result.project}: {result.messages} messages, "
        f"{result.source_words} words"
    )

    if result.catalog_is_stale:
        context.warn(
            f"the catalog is older than {', '.join(result.stale_sources)}. "
            f"Everything below is measured against a stale message list."
        )

    for entry in result.worst_first():
        context.say(f"  {entry.describe()}")
        if entry.last_touched is not None:
            context.say(f"      last touched {entry.last_touched}", level=1)

    outstanding = result.total_outstanding_words()
    if outstanding:
        context.say("")
        context.say(f"{outstanding} words outstanding across all languages")

    if result.waivers:
        context.say(f"{result.waivers} waivers, {result.expired_waivers} expired",
                    level=1)

    for note in result.notes:
        context.warn(note)


def _to_json(result: ProjectStatus) -> str:
    payload = {
        "project": result.project,
        "canShip": result.can_ship,
        "verdict": result.verdict(),
        "messages": result.messages,
        "sourceWords": result.source_words,
        "catalogIsStale": result.catalog_is_stale,
        "staleSources": result.stale_sources,
        "outstandingWords": result.total_outstanding_words(),
        "waivers": {"total": result.waivers, "expired": result.expired_waivers},
        "locales": [
            {
                "locale": entry.tag,
                "readiness": entry.readiness.value,
                "approved": entry.stats.approved,
                "total": entry.stats.total,
                "translated": entry.stats.translated,
                "stale": entry.stale,
                "drafts": entry.drafts,
                "needsReview": entry.needs_review,
                "empty": entry.empty,
                "blocking": entry.blocking,
                "outstandingWords": entry.stats.outstanding_words,
                "lastTouched": (entry.last_touched.isoformat()
                                if entry.last_touched else None),
            }
            for entry in result.worst_first()
        ],
        "notes": result.notes,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
