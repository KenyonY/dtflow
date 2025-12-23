"""
Data display utilities.
"""

from typing import Any, Dict, List, Optional

import orjson


def display_data(
    data: List[Dict[str, Any]],
    fields: Optional[List[str]] = None,
    start_index: int = 0,
    use_rich: bool = True,
) -> None:
    """
    Display data in a readable format.

    Args:
        data: List of data items to display
        fields: Specific fields to display (None = all fields)
        start_index: Starting index for numbering
        use_rich: Whether to use rich formatting (if available)
    """
    if not data:
        print("No data to display")
        return

    try:
        if use_rich:
            _display_with_rich(data, fields, start_index)
        else:
            _display_plain(data, fields, start_index)
    except ImportError:
        _display_plain(data, fields, start_index)


def _display_with_rich(
    data: List[Dict[str, Any]], fields: Optional[List[str]], start_index: int
) -> None:
    """Display using rich library for pretty formatting."""
    from rich import box
    from rich.console import Console
    from rich.json import JSON
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    for i, item in enumerate(data):
        index = start_index + i

        # Filter fields if specified
        display_item = item
        if fields:
            display_item = {k: v for k, v in item.items() if k in fields}

        # Create a panel for each item
        json_str = orjson.dumps(display_item, option=orjson.OPT_INDENT_2).decode("utf-8")

        panel = Panel(
            JSON(json_str, indent=2),
            title=f"[bold cyan]Item {index}[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )

        console.print(panel)
        console.print()


def _display_plain(
    data: List[Dict[str, Any]], fields: Optional[List[str]], start_index: int
) -> None:
    """Display using plain text formatting."""
    separator = "=" * 80

    for i, item in enumerate(data):
        index = start_index + i

        print(f"\n{separator}")
        print(f"Item {index}")
        print(separator)

        # Filter fields if specified
        display_item = item
        if fields:
            display_item = {k: v for k, v in item.items() if k in fields}

        # Pretty print JSON
        print(orjson.dumps(display_item, option=orjson.OPT_INDENT_2).decode("utf-8"))

    print(f"\n{separator}\n")


def format_item(item: Dict[str, Any], max_width: int = 80) -> str:
    """
    Format a single item as a string.

    Args:
        item: Item to format
        max_width: Maximum width for text wrapping

    Returns:
        Formatted string
    """
    return orjson.dumps(item, option=orjson.OPT_INDENT_2).decode("utf-8")


def preview_fields(data: List[Dict[str, Any]], n: int = 5) -> Dict[str, List[Any]]:
    """
    Preview values for each field in the dataset.

    Args:
        data: List of data items
        n: Number of example values to show per field

    Returns:
        Dictionary mapping field names to example values
    """
    if not data:
        return {}

    # Collect all fields
    all_fields = set()
    for item in data:
        all_fields.update(item.keys())

    # Collect examples for each field
    field_examples = {}
    for field in all_fields:
        examples = []
        for item in data:
            if field in item and len(examples) < n:
                value = item[field]
                # Truncate long strings
                if isinstance(value, str) and len(value) > 100:
                    value = value[:97] + "..."
                examples.append(value)

        field_examples[field] = examples

    return field_examples


def print_stats(stats: Dict[str, Any]) -> None:
    """
    Print dataset statistics in a readable format.

    Args:
        stats: Statistics dictionary from DataTransformer.stats()
    """
    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        console = Console()

        # Overall stats
        console.print(f"\n[bold cyan]Dataset Statistics[/bold cyan]")
        console.print(f"Total items: [green]{stats['total']}[/green]")
        console.print(f"Total fields: [green]{len(stats['fields'])}[/green]\n")

        # Field stats table
        if stats.get("field_stats"):
            table = Table(title="Field Statistics", box=box.ROUNDED, show_header=True)
            table.add_column("Field", style="cyan", no_wrap=True)
            table.add_column("Count", style="green", justify="right")
            table.add_column("Missing", style="yellow", justify="right")
            table.add_column("Type", style="magenta")

            for field, field_stat in stats["field_stats"].items():
                table.add_row(
                    field, str(field_stat["count"]), str(field_stat["missing"]), field_stat["type"]
                )

            console.print(table)
            console.print()

    except ImportError:
        # Fallback to plain text
        print("\nDataset Statistics")
        print("=" * 60)
        print(f"Total items: {stats['total']}")
        print(f"Total fields: {len(stats['fields'])}")
        print(f"\nFields: {', '.join(stats['fields'])}")

        if stats.get("field_stats"):
            print("\nField Statistics:")
            print("-" * 60)
            for field, field_stat in stats["field_stats"].items():
                print(f"\n{field}:")
                print(f"  Count: {field_stat['count']}")
                print(f"  Missing: {field_stat['missing']}")
                print(f"  Type: {field_stat['type']}")
        print()
