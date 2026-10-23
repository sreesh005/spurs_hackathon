from pathlib import Path

import typer

from . import config

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Spurs highlight enrichment pipeline."""


@app.command()
def smoke() -> None:
    """M0: check both APIs and the live feed (read-only)."""
    from . import smoke as m0

    if not m0.run(config.load()):
        raise typer.Exit(1)


@app.command()
def clip(seconds: float = typer.Option(15, help="How many seconds of the feed to record")) -> None:
    """M1: record N seconds of the live feed into clips/<id>.mp4 + .json."""
    from . import feed

    mp4 = feed.record(config.load().live_feed_url, seconds)
    print(f"wrote {mp4.relative_to(config.ROOT)} and {mp4.with_suffix('.json').relative_to(config.ROOT)}")


@app.command("clip-source")
def clip_source(
    start: float = typer.Option(..., help="Start offset in the match, seconds"),
    end: float = typer.Option(..., help="End offset in the match, seconds"),
    name: str = typer.Option(..., help="Clip ID, e.g. goal_mnu"),
) -> None:
    """Cut a test clip from the recorded match (SCOREPLAY_MEDIA_ID) instead of the live feed."""
    from . import feed, scoreplay_data

    s = config.load()
    mp4 = feed.cut_source(scoreplay_data.source_file_url(s.scoreplay_media_id), s.scoreplay_media_id, start, end, name)
    print(f"wrote {mp4.relative_to(config.ROOT)}")


@app.command("analyze")
def analyze_cmd(clips: list[Path] = typer.Argument(..., help="One or more clips/<id>.mp4")) -> None:
    """M2: analyze clips with TwelveLabs and save runs/<id>.analysis.json."""
    import json

    from . import analyze

    for mp4 in clips:
        run = analyze.analyze(mp4)
        print(f"== {mp4.name}  ({run['seconds']}s, {run['usage']})")
        print(json.dumps(run["analysis"], indent=2, ensure_ascii=False))


@app.command()
def live(
    minutes: float = typer.Option(10, help="How long to run"),
    no_analyze: bool = typer.Option(False, "--no-analyze", help="Don't call TwelveLabs (free run of the local half)"),
    no_mediapipe: bool = typer.Option(False, "--no-mediapipe", help="Loudness only, skip the MediaPipe signals"),
    max_calls: int = typer.Option(None, help="Stop calling TwelveLabs after this many calls"),
    source: str = typer.Option("scoreplay", envvar="LIVE_SOURCE",
                               help="scoreplay: ScorePlay's live recording; feed: the organizer feed (LIVE_FEED_URL)"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for a ScorePlay recording to start"),
) -> None:
    """The live loop: feed -> rules engine -> TwelveLabs -> ScorePlay (writes printed while DRY_RUN is on)."""
    from . import live as live_mod

    live_mod.Live(not no_analyze, not no_mediapipe, max_calls, source=source, wait=wait).run(minutes)


@app.command()
def replay(
    start: float = typer.Option(4500, help="Match offset to start at, seconds"),
    end: float = typer.Option(6000, help="Match offset to stop at, seconds"),
    refresh: bool = typer.Option(False, help="Measure the signals again instead of using the cache"),
    verbose: bool = typer.Option(False, help="Print every segment's signals"),
) -> None:
    """Run the rules engine over the recorded match (no TwelveLabs). Use it to tune rules.yaml."""
    from . import replay as replay_mod

    replay_mod.run(start, end, refresh, verbose)


@app.command()
def writeback(run_file: Path = typer.Argument(..., help="runs/<id>.analysis.json")) -> None:
    """M3: write one analyzed clip back to ScorePlay (printed while DRY_RUN is on)."""
    import json

    from . import writeback as wb

    run = json.loads(run_file.read_text())
    print(wb.deliver(run, config.ROOT / run["clip_file"]))


@app.command()
def angles(
    play: str = typer.Option(..., help="The play, e.g. 'Solanke equalizer from a goalmouth scramble'"),
    at: str = typer.Option("", help="When, e.g. '91:15'"),
) -> None:
    """Ask Jockey which clips in our knowledge store show the same play from different angles."""
    import json

    from . import tl_store

    print(json.dumps(tl_store.group_angles(play, at), indent=2))


if __name__ == "__main__":
    app()
