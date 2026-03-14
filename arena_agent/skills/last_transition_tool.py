"""CLI tool that returns the last stored transition."""

from __future__ import annotations

from arena_agent.skills.shared import build_base_parser, build_runtime_components, print_json, read_last_transition


def main() -> None:
    parser = build_base_parser("Return the last stored Arena transition.")
    args = parser.parse_args()

    config, _, _, _, _, _ = build_runtime_components(args.config)
    transition = read_last_transition(config.storage.transition_path)
    print_json({"transition": transition})


if __name__ == "__main__":
    main()
