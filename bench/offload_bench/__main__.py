"""Command line: python -m offload_bench <command> ...

  speed   <model> <runtime> <backend> [--label L] [--load-arg=ARG ...]
  matrix  <model> [<model> ...]      speed suite on every runtime x backend
  quality <model> <runtime> <backend> [--tier quick|full] [--only TASK ...] [--resume LOG ...]
  queue   <file>                     run the commands in a queue file, one per line
  report                             rebuild results/summary.md
  remove  <model>                    delete a model from LM Studio and Ollama together
"""
import argparse
import json

from . import config, quality, speed


def main():
    parser = argparse.ArgumentParser(prog="offload_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("speed")
    p.add_argument("model")
    p.add_argument("runtime", choices=["lmstudio", "ollama", "strata"])
    p.add_argument("backend", choices=["vulkan", "rocm", "hip"])
    p.add_argument("--label")
    p.add_argument("--load-arg", action="append", default=[],
                   help="extra argument for the runtime's load command, e.g. --load-arg=--speculative-draft-mtp")

    m = sub.add_parser("matrix")
    m.add_argument("models", nargs="+")

    qu = sub.add_parser("queue")
    qu.add_argument("file")

    sub.add_parser("report")

    rm = sub.add_parser("remove", help="delete a model from LM Studio and Ollama together")
    rm.add_argument("model")

    q = sub.add_parser("quality")
    q.add_argument("model")
    q.add_argument("runtime", choices=["lmstudio", "ollama", "strata"])
    q.add_argument("backend", choices=["vulkan", "rocm", "hip"])
    q.add_argument("--tier", choices=["quick", "full"], default="quick")
    q.add_argument("--only", nargs="+", help="run only these tasks from suite.yaml")
    q.add_argument("--limit", type=int, help="override every task's sample count (smoke tests)")
    q.add_argument("--max-tokens", type=int, help="override the answer budget (smoke tests)")
    q.add_argument("--gated", action="store_true",
                   help="run suite.yaml's screen first and stop if an already-measured model dominates this one")
    q.add_argument("--label")
    q.add_argument("--resume", nargs="+", metavar="LOG",
                   help="unfinished Inspect logs of this model to continue, keeping their finished samples")

    args = parser.parse_args()
    if args.command == "remove":
        from . import runtimes
        runtimes.remove_model(config.model(args.model))
    elif args.command == "report":
        from . import report
        print(report.build())
    elif args.command == "queue":
        from . import queue
        queue.run(args.file)
    elif args.command == "quality":
        quality.run(args.model, args.runtime, args.backend, args.tier, args.only, args.label,
                    args.limit, args.max_tokens, args.gated, args.resume)
    elif args.command == "speed":
        print(json.dumps(speed.run(args.model, args.runtime, args.backend, args.load_arg, args.label), indent=2))
    elif args.command == "matrix":
        runtimes = config.load("runtimes")
        for model in args.models:
            for runtime in ("lmstudio", "ollama"):
                for backend in runtimes[runtime]["backends"]:
                    r = speed.run(model, runtime, backend)
                    print(json.dumps({k: r.get(k) for k in ("model", "runtime", "backend", "ok", "error")}))


if __name__ == "__main__":
    main()
