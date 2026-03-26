import click

from cli.commands.web.feature import feature
from cli.commands.web.record import record
from cli.commands.web.script import script
from cli.commands.web.suite import suite
from cli.commands.web.run import web_run


@click.group()
def web():
    """Web testing commands."""
    pass


web.add_command(feature, "feature")
web.add_command(record, "record")
web.add_command(script, "script")
web.add_command(suite, "suite")
web.add_command(web_run, "run")
