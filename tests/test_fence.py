"""Ticket start bundles use clean clones and disposable local bare remotes."""

import os
from pathlib import Path

import pytest
from test_fenced_runner import delivery  # noqa: F401

from cplane import deny, fence, state


@pytest.fixture
def start_chain(delivery, monkeypatch):  # noqa: F811 - shared pytest fixture
    d = delivery
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "eval")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "eval@localhost")
    chain = d["root"] / "chain"
    d["g"](d["root"], "clone", d["remote"], chain)
    d["g"](chain, "checkout", "-b", "base0-start")

    def build(
        messages=("tests", "ticket 1", "ticket 2"),
        *,
        private=False,
        private_ticket=False,
    ):
        commits = []
        for index, message in enumerate(messages):
            name = "pinned test.py" if index == 0 else "implementation.py"
            (chain / name).write_text(
                deny.CANARY
                if (private and index == 0 or private_ticket and index == 1)
                else f"synthetic {index}\n"
            )
            d["g"](chain, "add", ".")
            d["g"](chain, "commit", "-m", message)
            commits.append(d["g"](chain, "rev-parse", "HEAD"))
        bundle = d["root"] / "starts.bundle"
        d["g"](
            chain, "bundle", "create", bundle, "refs/heads/base0-start", "^" + d["base"]
        )
        return bundle, commits

    d.update(chain=chain, build=build)
    return d


def publish(d, bundle, **kwargs):
    return d["adapter"].publish_eval_starts(
        "example/repo", 53, kwargs.get("base", d["base"]), 2, bundle
    )


def test_start_chain_and_idempotent_branches(start_chain):
    d = start_chain
    bundle, commits = d["build"]()
    starts = publish(d, bundle)
    assert starts == [
        {
            "start_commit": commit,
            "start_branch": f"eval/pr53-t{n}",
            "pinned_paths": ["pinned test.py"],
        }
        for n, commit in enumerate(commits[:-1], 1)
    ]
    assert publish(d, bundle) == starts
    branches = d["g"](
        d["remote"],
        "for-each-ref",
        "--format=%(refname):%(objectname)",
        "refs/heads/eval/",
    )
    assert branches.splitlines() == [
        f"refs/heads/eval/pr53-t{n}:{commit}"
        for n, commit in enumerate(commits[:-1], 1)
    ]
    assert commits[-1] not in branches
    assert not d["g"](d["clean"], "for-each-ref", "refs/factory/eval-starts/")
    pushes = [args for args, _ in d["calls"] if "push" in args]
    assert len(pushes) == 2
    assert all("eval/pr53-t" in args[-1] for args in pushes)



@pytest.mark.parametrize(
    ("messages", "error"),
    [
        (("tests", "ticket 2", "ticket 1"), "expected ticket 1"),
        (("setup", "ticket 1", "ticket 2"), "expected tests"),
        (("ticket 1", "ticket 2"), "expected tests and 2 ticket commits"),
        (
            ("tests", "ticket 1", "ticket 2", "extra"),
            "expected tests and 2 ticket commits",
        ),
    ],
)
def test_start_chain_refuses_bad_order_or_length(start_chain, messages, error):
    d = start_chain
    bundle, _ = d["build"](messages)
    with pytest.raises(state.StateError, match=error):
        publish(d, bundle)
    assert not any("push" in args for args, _ in d["calls"])
    assert not d["g"](d["clean"], "for-each-ref", "refs/factory/eval-starts/")


def test_start_chain_wrong_base(start_chain):
    d = start_chain
    bundle, _ = d["build"]()
    d["g"](d["chain"], "checkout", "main")
    (d["chain"] / "README").write_text("other base\n")
    d["g"](d["chain"], "commit", "-am", "other base")
    other = d["g"](d["chain"], "rev-parse", "HEAD")
    d["g"](d["chain"], "push", "origin", "main")
    with pytest.raises(state.StateError, match="case base for tests"):
        publish(d, bundle, base=other)
    assert not any("push" in args for args, _ in d["calls"])


def test_start_branch_conflict(start_chain):
    d = start_chain
    bundle, _ = d["build"]()
    d["g"](d["remote"], "update-ref", "refs/heads/eval/pr53-t1", d["base"])
    with pytest.raises(
        state.StateError, match="eval/pr53-t1 already exists at another commit"
    ):
        publish(d, bundle)
    assert not any("push" in args for args, _ in d["calls"])


def test_start_deny_check_prevents_push(start_chain):
    d = start_chain
    bundle, _ = d["build"](private=True)
    with pytest.raises(deny.Denied) as caught:
        publish(d, bundle)
    assert deny.CANARY not in str(caught.value)
    assert not any("push" in args for args, _ in d["calls"])


def test_start_branch_cannot_be_default(start_chain):
    d = start_chain
    bundle, _ = d["build"]()
    d["g"](d["remote"], "update-ref", "refs/heads/eval/pr53-t1", d["base"])
    d["g"](d["remote"], "symbolic-ref", "HEAD", "refs/heads/eval/pr53-t1")
    with pytest.raises(state.StateError, match="eval start branch is the default"):
        publish(d, bundle)
    assert not any("push" in args for args, _ in d["calls"])


def test_start_bundle_requires_single_ref(start_chain):
    d = start_chain
    _, _ = d["build"]()
    bundle = d["root"] / "multiple.bundle"
    d["g"](
        d["chain"],
        "bundle",
        "create",
        bundle,
        "HEAD",
        "refs/heads/base0-start",
        "^" + d["base"],
    )
    with pytest.raises(state.StateError, match="expected a single ref"):
        publish(d, bundle)
    assert not any("push" in args for args, _ in d["calls"])


def test_start_pinned_paths_include_renames_binary_and_unusual_names(start_chain):
    d = start_chain
    (d["chain"] / "README").rename(d["chain"] / "renamed")
    (d["chain"] / "é\n.py").write_text("synthetic\n")
    (d["chain"] / "binary").write_bytes(b"\0synthetic")
    bundle, _ = d["build"]()
    starts = publish(d, bundle)
    assert [s["pinned_paths"] for s in starts] == [
        ["README", "binary", "pinned test.py", "renamed", "é\n.py"]
    ] * 2


def test_start_chain_refuses_merge_commit(start_chain):
    d = start_chain
    bundle, commits = d["build"]()
    d["g"](d["chain"], "checkout", "-b", "side", commits[0])
    (d["chain"] / "side").write_text("synthetic\n")
    d["g"](d["chain"], "add", ".")
    d["g"](d["chain"], "commit", "-m", "side")
    d["g"](d["chain"], "checkout", "base0-start")
    d["g"](d["chain"], "reset", "--hard", commits[1])
    d["g"](d["chain"], "merge", "--no-ff", "side", "-m", "ticket 2")
    bundle.unlink()
    d["g"](
        d["chain"],
        "bundle",
        "create",
        bundle,
        "refs/heads/base0-start",
        "^" + d["base"],
    )
    with pytest.raises(
        state.StateError, match="ticket 2 must have only the expected parent"
    ):
        publish(d, bundle)
    assert not any("push" in args for args, _ in d["calls"])


def test_start_deny_check_scans_intermediate_commit_removed_by_later_ticket(
    start_chain,
):
    d = start_chain
    bundle, _ = d["build"](
        ("tests", "ticket 1", "ticket 2", "ticket 3"), private_ticket=True
    )
    with pytest.raises(deny.Denied):
        d["adapter"].publish_eval_starts("example/repo", 53, d["base"], 3, bundle)
    branches = d["g"](
        d["remote"], "for-each-ref", "--format=%(refname)", "refs/heads/eval/"
    )
    assert branches == "refs/heads/eval/pr53-t1"


@pytest.mark.parametrize('mode,uid,is_work,accepted', [
    (0o1733, 0, True, True), (0o1777, 0, True, True),
    (0o0711, 0, True, True), (0o0733, 0, True, False),
    (0o0770, 0, True, False), (0o1733, 21010, True, False),
    (0o1733, 21011, True, False), (0o1733, 0, False, False),
    (0o0700, 21010, False, True), (0o0700, 21011, False, False),
])
def test_trusted_work_root_sticky_exception(tmp_path, monkeypatch, mode, uid, is_work, accepted):
    path = tmp_path / 'directory'
    path.mkdir()
    monkeypatch.setattr(fence, 'WORK_ROOT', path if is_work else tmp_path / 'work')
    monkeypatch.setattr(fence.os, 'geteuid', lambda: 21010)
    original_lstat = Path.lstat
    def info(part):
        result = original_lstat(part)
        values = list(result)
        # Synthetic service/root ancestors, independent of the test host UID.
        values[4] = 0
        if part == path:
            values[0] = (result.st_mode & ~0o7777) | mode
            values[4] = uid
        return os.stat_result(values)
    monkeypatch.setattr(Path, 'lstat', info)
    if accepted:
        assert fence.trusted_directory(path) == path
    else:
        with pytest.raises(state.StateError, match='trusted directory'):
            fence.trusted_directory(path)
