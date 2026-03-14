"""CLI tool that submits an Arena trading action."""

from __future__ import annotations

import argparse
import json

from arena_agent.core.runtime_loop import build_transition_event
from arena_agent.skills.shared import (
    build_base_parser,
    build_runtime_components,
    parse_action_payload,
    print_json,
)


def main() -> None:
    parser = build_base_parser("Submit an Arena trading action.")
    parser.add_argument("payload", nargs="?", help="Optional JSON action payload.")
    parser.add_argument("--action", help="Action type, e.g. OPEN_LONG.")
    parser.add_argument("--size", type=float, default=None)
    parser.add_argument("--tp", type=float, default=None)
    parser.add_argument("--sl", type=float, default=None)
    parser.add_argument("--signal-indicators", default=None, help="JSON array of requested indicator specs.")
    parser.add_argument(
        "--execute",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Override config dry_run and execute a real trade when true.",
    )
    args = parser.parse_args()

    signal_indicators = json.loads(args.signal_indicators) if args.signal_indicators else None
    config, _, state_builder, executor, transition_store, _ = build_runtime_components(
        args.config,
        signal_indicators=signal_indicators,
    )
    executor.dry_run = config.dry_run if not args.execute else False

    state_before = state_builder.build()
    action = parse_action_payload(
        args.payload,
        action=args.action,
        size=args.size,
        tp=args.tp,
        sl=args.sl,
    )
    execution_result = executor.execute(action, state_before)
    state_after = state_builder.build()
    transition = build_transition_event(state_before, action, execution_result, state_after)
    transition_store.append(transition)
    print_json(
        {
            "action": action,
            "execution_result": execution_result,
            "transition": transition,
        }
    )


if __name__ == "__main__":
    main()
