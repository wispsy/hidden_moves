"""The CLI is an adapter around explicitly assembled Python capabilities."""

import sys
from contextlib import redirect_stdout

from expose_interface import CommandError, Context, Interface, option

from hidden_moves import MoveError, Moves, Registry, discover_providers, load_provider
from hidden_moves.commands.capabilities import (
	move_commands,
	plugin_commands,
)


@option("--plugin", dest="plugins", multiple=True, help="Explicitly load an installed provider.")
def _setup(context: Context, plugins: tuple[str, ...] = ()) -> None:
	if context.command is None:
		return
	registry = Registry()
	if plugins:
		entries = discover_providers()
		for name in plugins:
			matches = [entry for entry in entries if entry.name == name]
			if len(matches) != 1:
				reason = "not installed" if not matches else "advertised by multiple packages"
				raise CommandError(f"Provider {name!r} is {reason}.")
			try:
				with redirect_stdout(sys.stderr):
					load_provider(matches[0], registry)
			except MoveError as error:
				raise CommandError(str(error)) from error
	context.obj = Moves(registry=registry)


app = Interface("hidden-moves", description="Discover and use reusable Python capabilities.", setup=_setup)
app.add_interface(move_commands)
app.add_interface(plugin_commands)


@app.program(name=None)
@move_commands.program(name=None)
@plugin_commands.program(name=None)
def _missing_command(context: Context) -> None:
	selected = app
	for name in context.path:
		selected = selected.children[name]
	print(selected.format_help(prog_name=" ".join((app.name, *context.path))), file=sys.stderr, end="")
	raise SystemExit(2)


def main(argv: list[str] | None = None, *, prog_name: str | None = None) -> None:
	"""Run the installed CLI with fresh provider state for each invocation."""
	try:
		app.main(argv, prog_name=prog_name)
	except (EOFError, KeyboardInterrupt):
		print("\nAborted!", file=sys.stderr)
		raise SystemExit(1) from None
