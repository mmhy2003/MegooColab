from app.kb_drafts.blocks import compose, join_blocks, new_turn, open_count, segments, split_blocks

BEFORE = "# A\n\nold\n\nkeep1\n\nFAQ\n\nkeep2"
AFTER = "# A\n\nnew\n\nkeep1\n\nkeep2\n\n## Rollback"


def test_fence_with_blank_lines_is_one_block():
    md = "Intro\n\n```\na\n\nb\n```\n\nEnd"
    assert split_blocks(md) == ["Intro", "```\na\n\nb\n```", "End"]


def test_unclosed_fence_runs_to_the_end():
    md = "Intro\n\n~~~\na\n\n\nb"
    assert split_blocks(md) == ["Intro", "~~~\na\n\n\nb"]


def test_crlf_and_extra_blank_lines_are_normalised():
    assert split_blocks("a  \r\n\r\n\r\n\r\nb\r\n") == ["a", "b"]
    assert join_blocks(["a", "b"]) == "a\n\nb"


def test_turn_marks_added_changed_removed():
    turn = new_turn("tidy up", BEFORE, AFTER)
    marks = [s for s in segments(turn, AFTER) if s["kind"] == "mark"]
    assert [m["change"] for m in marks] == ["changed", "removed", "added"]
    assert marks[0]["old_md"] == "old" and marks[0]["new_md"] == "new"
    assert marks[1]["old_md"] == "FAQ" and marks[1]["new_md"] == ""
    assert marks[2]["new_md"] == "## Rollback"
    assert all(m["request"] == "tidy up" for m in marks)
    assert segments(turn, AFTER)[0] == {"kind": "text", "md": "# A"}
    assert compose(turn) == AFTER
    assert open_count(turn) == 3


def test_undo_puts_back_the_before_blocks():
    turn = new_turn("tidy up", BEFORE, AFTER)
    removed = [s for s in segments(turn, AFTER) if s["kind"] == "mark"][1]["id"]
    turn["status"][str(removed)] = "undone"
    assert compose(turn) == "# A\n\nnew\n\nkeep1\n\nFAQ\n\nkeep2\n\n## Rollback"
    body = compose(turn)
    # an undone mark is settled: it shows as plain text, the others stay open
    segs = segments(turn, body)
    assert [s["change"] for s in segs if s["kind"] == "mark"] == ["changed", "added"]
    assert open_count(turn) == 2


def test_kept_marks_merge_into_the_text():
    turn = new_turn("x", "a\n\nb", "a\n\nc")
    turn["status"]["0"] = "kept"
    assert segments(turn, compose(turn)) == [{"kind": "text", "md": "a\n\nc"}]


def test_no_change_gives_no_turn():
    assert new_turn("x", "a", "a\n") is None


def test_segments_without_a_turn_are_the_body():
    assert segments(None, "hello") == [{"kind": "text", "md": "hello"}]
    assert segments(None, "") == []
