"""Agent-to-agent MCP tools (AGT-31 "ask another project's agents", §6.6).

Asking (find_answer, ask_project, withdraw_question): any token except an answering run, so questions never
loop. A task run asks on behalf of its own task. Answering (submit_answer): answering runs only, for their own
question. get_question: anyone who may read the question; an answering run sees its own.
"""

import uuid
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.a2a import service
from app.a2a.models import Question
from app.mcp_server.auth import current_run, tool_session
from app.projects.models import Project
from app.tasks.models import Task
from app.workflow import engine


def _refuse_answer_runs() -> None:
    run = current_run.get()
    if run is not None and run.question_id is not None:
        raise ToolError("not_allowed_in_role")


async def _run_task_key(db) -> str | None:
    run = current_run.get()
    if run is None or run.task_id is None:
        return None
    task = await db.get(Task, run.task_id)
    project = await db.get(Project, task.project_id)
    return f"{project.key}-{task.number}"


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ToolError("question_not_found") from None


def _view(q: Question, ref: str) -> dict[str, Any]:
    return {
        "id": str(q.id), "ref": ref, "status": str(q.status), "title": q.title, "body": q.body,
        "context": q.context, "answer_md": q.answer_md, "citations": list(q.citations or []),
        "answer_source": q.answer_source,
    }


def register_a2a_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    async def find_answer(project_key: str, question: str) -> dict[str, Any]:
        """Before asking another project, look for an existing answer in its Knowledge Base and the memory.
        Returns up to 5 suggestions {kind, id, title, snippet, link}; read them with kb_read or search_memory."""
        _refuse_answer_runs()
        async with tool_session() as (db, user):
            project = await service.project_by_key(db, project_key)
            found = await service.suggest(db, user, project.id, question)
            return {"suggestions": [s.model_dump(mode="json") for s in found]}

    @mcp.tool()
    async def ask_project(
        project_key: str, question: str, context: str | None = None, task_key: str | None = None
    ) -> dict[str, Any]:
        """Ask another project a question about its code (an online agent of that project reads the code and
        answers, citing files). Include in `context` errors and what you tried. You may move on to other work:
        the answer arrives in your task's thread and prompt, or read it later with get_question."""
        _refuse_answer_runs()
        async with tool_session() as (db, user):
            own = await _run_task_key(db)
            if own is not None:
                if task_key is not None and task_key.strip().upper() != own:
                    raise ToolError("wrong_task")
                task_key = own
            run = current_run.get()
            q, suggestions = await service.ask(
                db, user, project_key=project_key, body=question, context=context or "", task_key=task_key,
                agent_id=run.agent_id if run is not None else None,
            )
            project = await db.get(Project, q.target_project_id)
            out = {"question_id": str(q.id), "ref": service.ref_of(project, q), "status": str(q.status),
                   "suggestions": [s.model_dump(mode="json") for s in suggestions]}
            await engine.dispatch_queued(db)
            return out

    @mcp.tool()
    async def get_question(question_id: str) -> dict[str, Any]:
        """A question with its status and, once answered, the answer and its citations."""
        async with tool_session() as (db, user):
            qid = _uuid(question_id)
            run = current_run.get()
            if run is not None and run.question_id is not None:
                if run.question_id != qid:
                    raise ToolError("question_not_found")
                q = await db.get(Question, qid)
            else:
                q = await service.get_question_for(db, user, qid)
            return _view(q, service.ref_of(await db.get(Project, q.target_project_id), q))

    @mcp.tool()
    async def withdraw_question(question_id: str) -> dict[str, Any]:
        """Withdraw a question you asked (for example when find_answer already answered it)."""
        _refuse_answer_runs()
        async with tool_session() as (db, user):
            q = await service.withdraw(db, user, await service.get_question_for(db, user, _uuid(question_id)))
            return {"status": str(q.status)}

    @mcp.tool()
    async def submit_answer(answer_md: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
        """Answer the question this session was started for. `citations`: [{path, start_line, end_line}] for
        the code you read. Never include secrets, credentials or environment values."""
        run = current_run.get()
        if run is None or run.question_id is None:
            raise ToolError("not_allowed_in_role")
        async with tool_session() as (db, _user):
            q = await service.submit(db, run, answer_md, citations)
            return {"status": str(q.status)}
