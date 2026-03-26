import click
from rich.console import Console

console = Console()

COMING_SOON = "[yellow]⚠[/yellow] API testing is coming soon."


@click.group()
def feature():
    """Manage API features."""
    pass


@feature.command("create")
@click.argument("name")
def feature_create(name):
    """Create an API feature."""
    console.print(COMING_SOON)


@feature.command("list")
def feature_list():
    """List API features."""
    console.print(COMING_SOON)


@feature.command("delete")
@click.argument("feature_id")
def feature_delete(feature_id):
    """Delete an API feature."""
    console.print(COMING_SOON)


@click.group()
def suite():
    """Manage API suites."""
    pass


@suite.command("create")
@click.argument("name")
def suite_create(name):
    """Create an API suite."""
    console.print(COMING_SOON)


@suite.command("list")
def suite_list():
    """List API suites."""
    console.print(COMING_SOON)


@click.command("run")
@click.option("--suite", "suite_id", required=True)
@click.option("--env", "env_name", default=None)
def api_run(suite_id, env_name):
    """Run an API test suite."""
    console.print(COMING_SOON)
