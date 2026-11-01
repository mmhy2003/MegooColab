"""Rounds of an agent chat are tasks kept off the board until someone adds them to it."""

from sqlalchemy import ColumnElement

from app.tasks.models import Task


def on_board() -> ColumnElement[bool]:
    """The tasks that show on the board, in lists, counts, reports and search: every task but a chat round."""
    return Task.in_chat.is_(False)
