"""CLI tool that returns compact competition information."""

from __future__ import annotations

from arena_agent.skills.shared import build_base_parser, build_runtime_components, print_json


def main() -> None:
    parser = build_base_parser("Return compact competition information.")
    args = parser.parse_args()

    _, _, state_builder, _, _, _ = build_runtime_components(args.config)
    state = state_builder.build()
    payload = {
        "competition_id": state.competition.competition_id,
        "symbol": state.competition.symbol,
        "status": state.competition.status,
        "is_live": state.competition.is_live,
        "is_close_only": state.competition.is_close_only,
        "current_trades": state.competition.current_trades,
        "max_trades": state.competition.max_trades,
        "max_trades_remaining": state.competition.max_trades_remaining,
        "time_remaining_seconds": state.competition.time_remaining_seconds,
        "metadata": state.competition.metadata,
    }
    print_json(payload)


if __name__ == "__main__":
    main()
