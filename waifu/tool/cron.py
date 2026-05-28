from typing import TYPE_CHECKING, Optional

from hai.tool import Tool

if TYPE_CHECKING:
    from waifu.store.cron import CronStore

_VALID_TYPES = ("at", "every", "cron")
_VALID_KINDS = ("shell", "llm")


def _cron_list(store: "CronStore") -> str:
    jobs = store.list()
    if not jobs:
        return "[no cron jobs]"
    return "\n".join(
        f"id={j.id} name={j.name!r} type={j.type} schedule={j.schedule!r} kind={j.kind} enabled={j.enabled}"
        for j in jobs
    )


def _cron_create(
    store: "CronStore",
    name: Optional[str],
    schedule_type: Optional[str],
    schedule: Optional[str],
    command: Optional[str],
    kind: Optional[str],
) -> str:
    if not name or not schedule_type or not schedule or not command:
        return "[error] create requires: name, schedule_type, schedule, command"
    if schedule_type not in _VALID_TYPES:
        return f"[error] schedule_type must be one of {_VALID_TYPES}"
    job_kind = kind or "shell"
    if job_kind not in _VALID_KINDS:
        return f"[error] kind must be one of {_VALID_KINDS}"
    job = store.create(name=name, type=schedule_type, schedule=schedule, command=command, kind=job_kind)
    return f"[ok] created cron job id={job.id} name={job.name!r}"


def _cron_mutate(store: "CronStore", action: str, job_id: Optional[str], name: Optional[str]) -> str:
    if not job_id and not name:
        return f"[error] {action} requires id or name"
    job = store.get(job_id) if job_id else store.get_by_name(name or "")
    if job is None:
        return "[error] cron job not found"
    jid = str(job.id)
    if action == "delete":
        store.remove(jid)
        return f"[ok] deleted cron job {jid}"
    if action == "enable":
        store.enable(jid)
        return f"[ok] enabled cron job {jid}"
    store.disable(jid)
    return f"[ok] disabled cron job {jid}"


def make_cron_tool(store: "CronStore") -> Tool:
    """Build the cron management tool bound to a CronStore."""

    def _cron(
        action: str,
        name: Optional[str] = None,
        schedule_type: Optional[str] = None,
        schedule: Optional[str] = None,
        command: Optional[str] = None,
        kind: Optional[str] = None,
        id: Optional[str] = None,
    ) -> str:
        if action == "list":
            return _cron_list(store)
        if action == "create":
            return _cron_create(store, name, schedule_type, schedule, command, kind)
        if action in ("delete", "enable", "disable"):
            return _cron_mutate(store, action, id, name)
        return f"[error] unknown action {action!r}. use: list, create, delete, enable, disable"

    return Tool(
        name="cron",
        description=(
            "Manage scheduled cron jobs. "
            "Actions: list, create, delete, enable, disable. "
            "schedule_type: 'at' (ISO datetime), 'every' (e.g. '30m','2h'), 'cron' (cron expression). "
            "kind: 'shell' (run a shell command) or 'llm' (send a prompt to the agent)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "delete", "enable", "disable"],
                    "description": "Operation to perform.",
                },
                "name": {
                    "type": "string",
                    "description": "Job name. Required for create; used to look up for other actions.",
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["at", "every", "cron"],
                    "description": "Scheduling type. Required for create.",
                },
                "schedule": {
                    "type": "string",
                    "description": "Schedule value (ISO datetime / interval / cron expr). Required for create.",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command or LLM prompt. Required for create.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["shell", "llm"],
                    "description": "Execution kind (default: shell).",
                    "default": "shell",
                },
                "id": {
                    "type": "string",
                    "description": "Job ID. Use for delete/enable/disable when name is ambiguous.",
                },
            },
            "required": ["action"],
        },
        func=_cron,
    )
