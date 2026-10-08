from job_agent.__main__ import main

from test_labels import SENIOR, WRITER, setup  # noqa: F401  (fixture)


def run_stats(capsys, args):
    code = main(["stats", *args])
    return code, capsys.readouterr().out.splitlines()


def test_stats_counts(capsys, setup):
    args, _ = setup
    main(["label", WRITER, "yes", *args])
    main(["label", "nebius:4817126101", "maybe", *args])  # kept, unclear location
    main(["label", SENIOR, "no", "--reason", "too_senior", *args])  # excluded: seniority
    main(["label", "adyen:7436701", "no", "--reason", "other", "--note", "sales",
          *args])  # excluded: category
    capsys.readouterr()
    stats_args = [a for i, a in enumerate(args)
                  if a != "--db" and (i == 0 or args[i - 1] != "--db")]
    code, out = run_stats(capsys, stats_args)
    assert code == 0
    assert out[1] == "4 labels"

    def row(name):
        """The numbers on the table row starting with `name`."""
        line = next(l for l in out if l.startswith(name + "  "))
        return [int(x) for x in line[len(name):].split()]

    assert [row(x) for x in ("yes", "maybe", "no")] == [[1], [1], [2]]
    # Every configured reason is listed, unused ones as 0.
    assert [row(r) for r in ("dutch_required", "too_senior", "other")] == [[0], [1], [1]]
    assert "(maybe without a reason: 1)" in out
    # total, yes, maybe, no
    assert row("nebius") == [3, 1, 1, 1]
    assert row("adyen") == [1, 0, 0, 1]
    assert row("kept") == [2, 1, 1, 0]
    assert row("excluded: category") == [1, 0, 0, 1]
    assert row("excluded: seniority") == [1, 0, 0, 1]
    assert row("excluded (all)") == [2, 0, 0, 2]


def test_stats_without_labels(capsys, setup):
    args, labels = setup
    code, out = run_stats(capsys, ["--config", args[1], "--labels", str(labels)])
    assert (code, out[-1]) == (0, "no labels")
