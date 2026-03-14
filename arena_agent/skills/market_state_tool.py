"""CLI tool that returns the current Arena market state snapshot."""

from __future__ import annotations

import json

from arena_agent.skills.shared import build_base_parser, build_runtime_components, print_json


def main() -> None:
    parser = build_base_parser("Return the current Arena market state snapshot.")
    parser.add_argument("--signal-indicators", default=None, help="JSON array of requested indicator specs.")
    args = parser.parse_args()

    signal_indicators = json.loads(args.signal_indicators) if args.signal_indicators else None
    _, _, state_builder, _, _, _ = build_runtime_components(args.config, signal_indicators=signal_indicators)
    state = state_builder.build()
    print_json(state)


if __name__ == "__main__":
    main()
