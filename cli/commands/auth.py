import click
from rich.console import Console
from cli.config import get_auth_key, set_auth_key, remove_auth_key, get_server_url, set_server_url
from cli.api import validate_auth_key

console = Console()


@click.command()
@click.option("--key", default=None, help="Auth key (non-interactive mode for CI/scripts)")
@click.option("--server", default=None, help="Override server URL")
def login(key, server):
    """Log in to QAClan cloud with your auth key."""
    if server:
        set_server_url(server)

    server_url = get_server_url()

    if not key:
        key = click.prompt("Enter your auth key (from Settings > Auth Key at qaclan.com)")

    try:
        user = validate_auth_key(server_url, key)
    except Exception:
        console.print(f"[red]✗ Could not reach server at {server_url}. Check your connection.[/red]")
        raise SystemExit(1)

    if not user:
        console.print("[red]✗ Invalid auth key. Please check and try again.[/red]")
        raise SystemExit(1)

    set_auth_key(key)
    console.print(f"[green]✓ Logged in as {user['name']} ({user['email']})[/green]")


@click.command()
def logout():
    """Log out from QAClan cloud."""
    remove_auth_key()
    console.print("[green]✓ Logged out successfully.[/green]")


def require_auth():
    """Check auth key exists. Call at the start of commands that need auth."""
    key = get_auth_key()
    if not key:
        Console().print("[red]✗ Not logged in. Run 'qaclan login' to authenticate.[/red]")
        raise SystemExit(1)
    return key
