"""CLI tool that returns the current Arena market state snapshot."""

from __future__ import annotations

from arena_agent.skills.shared import build_base_parser, build_runtime_components, print_json


def main() -> None:
    parser = build_base_parser("Return the current Arena market state snapshot.")
    args = parser.parse_args()

    _, _, state_builder, _, _, _ = build_runtime_components(args.config)
    state = state_builder.build()
    print_json(state)


if __name__ == "__main__":
    main()
