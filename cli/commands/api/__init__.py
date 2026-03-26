import click

from cli.commands.api.stubs import feature, suite, api_run


@click.group()
def api():
    """API testing commands (coming soon)."""
    pass


api.add_command(feature, "feature")
api.add_command(suite, "suite")
api.add_command(api_run, "run")
