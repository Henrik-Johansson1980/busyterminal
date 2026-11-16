# busyterminal

> "What are you working on?"
> "Oh, you know. Rebalancing shard 4417 across 32 nodes."

`busy.py` makes your terminal look like it is doing serious, important, deeply technical work.
It compiles things that do not exist, installs packages nobody asked for, tails logs from
services that were never deployed, and ships to production with a confidence no real deploy
has ever earned.

It does absolutely nothing. It does it beautifully.

## Features

- **Compiles** imaginary C, C++ and Rust, with the occasional unused-variable warning for realism.
  Nobody trusts a build with zero warnings.
- **Installs dependencies** with progress bars that stall at random, exactly like the real thing.
- **Tails logs** full of cache misses, GC pauses and a tasteful sprinkling of ERRORs.
- **Runs tests** that almost always pass. Almost.
- **Migrates the production database** without a backup, a review or a care in the world.
- **Decrypts data streams**, because every hacker movie said that is what terminals do.
- **Deploys** to `production`, `eu-west-1`, or wherever your manager happens to be looking.
- **Pings** hosts on the internal network that live only in its imagination.
- **Hexdumps** your NVMe drive. Not really. Probably.
- **Runs an ETL job** over millions of rows that are, in fact, zero rows.

## Usage

Requires Python 3. No dependencies, because even fake work should not need `node_modules`.

```sh
python3 busy.py
```

On startup it scrolls your prompt out of view, so nobody can see that you typed `busy.py`.
Plausible deniability is a feature.

### Options

| Option | What it does |
| --- | --- |
| `--speed N` | Multiply the speed. `2` for crunch time, `0.5` for a Friday afternoon. |
| `--slow` | Half speed. Same as `--speed 0.5`. |
| `--no-color` | Disable colors, for that authentic 1987 mainframe look. |
| `--duration TIME` | Stop after `90`, `30s`, `5m` or `1.5h` (max `24h`). Your shift, your rules. |

### Keys

| Key | What it does |
| --- | --- |
| `space` or `p` | Pause and resume. Paused time does not count toward `--duration`, so breaks are free. |
| `q` or `Esc` | Clock out. |
| `Ctrl+C` | Clock out, but more dramatically. |

## FAQ

**Is this productive?**
It is extremely productive at looking productive.

**Will it fool my coworkers?**
It will fool anyone who does not read the screen. In our experience, that is most people.

**Can I use it in a meeting while screen sharing?**
You can. We cannot stop you. We would like it noted that we did not suggest it.

**Does it actually touch my disk, network or production database?**
No. Everything is fake: the files, the hosts, the hashes, the confidence.

## License

Do whatever you want with it. Look busy.
