import click

from cli.db import init_db
from cli.commands.project import project
from cli.commands.env import env_group
from cli.commands.status import status
from cli.commands.runs import runs_group
from cli.commands.web import web
from cli.commands.api import api


@click.group()
def qaclan():
    """QAClan — QA test management and execution CLI."""
    init_db()


qaclan.add_command(project, "project")
qaclan.add_command(env_group, "env")
qaclan.add_command(status, "status")
qaclan.add_command(runs_group, "runs")
qaclan.add_command(web, "web")
qaclan.add_command(api, "api")


# Also register `run show` at top level as `qaclan run show`
@qaclan.group("run", invoke_without_command=True)
@click.pass_context
def run_group(ctx):
    """View individual run details."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


from cli.commands.runs import run_show
run_group.add_command(run_show, "show")


if __name__ == "__main__":
    qaclan()
