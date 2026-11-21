"""Bound background generation, preserve task references, and reap on shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import HTTPException

from src.api.services.game_event_log import GameEventLog

_jobs: dict[str, asyncio.Task] = {}
MAX_JOBS = 3


def has_active_jobs() -> bool:
    return any(not job.done() for job in _jobs.values())


def start_job(game_id: str, coroutine, event_log: GameEventLog) -> asyncio.Task:
    if game_id in _jobs or len(_jobs) >= MAX_JOBS:
        coroutine.close()
        event_log.append(
            {
                "event_type": "failed",
                "game_id": game_id,
                "reason": "Generation workers are busy",
            }
        )
        raise HTTPException(
            429,
            "Generation workers are busy; try again later",
            headers={"Retry-After": "30"},
        )

    async def run():
        try:
            async with asyncio.timeout(3600):
                await coroutine
        except asyncio.CancelledError:
            if not event_log.has_terminal():
                event_log.append(
                    {
                        "event_type": "interrupted",
                        "game_id": game_id,
                        "reason": "Job cancelled or interrupted",
                    }
                )
            raise
        except TimeoutError:
            if not event_log.has_terminal():
                event_log.append(
                    {
                        "event_type": "interrupted",
                        "game_id": game_id,
                        "reason": "Job exceeded its deadline",
                    }
                )
        finally:
            _jobs.pop(game_id, None)

    task = asyncio.create_task(run(), name=f"game:{game_id}")
    _jobs[game_id] = task
    return task


async def cancel_job(game_id: str) -> bool:
    task = _jobs.get(game_id)
    if task is None:
        return False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return True


async def stop_jobs() -> None:
    tasks = list(_jobs.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def recover_jobs(root: Path) -> None:
    if not root.is_dir():
        return
    for project in root.iterdir():
        if project.is_symlink() or not project.is_dir():
            continue
        directories = [project / ".creation"]
        modifications = project / ".modifications"
        if modifications.is_dir() and not modifications.is_symlink():
            directories.extend(modifications.iterdir())
        for directory in directories:
            if directory.is_symlink() or not directory.is_dir():
                continue
            log = GameEventLog(project, log_dir=str(directory.relative_to(project)))
            if log.events_file.is_symlink():
                continue
            if log.exists() and not log.has_terminal():
                log.append(
                    {
                        "event_type": "interrupted",
                        "game_id": project.name,
                        "reason": "Backend restarted before verification completed",
                    }
                )
