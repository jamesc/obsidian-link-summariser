"""
Command handler for 'eval' subcommand.

Runs evaluation on a dataset of URLs and reports metrics.
"""

import logging
from pathlib import Path
from typing import Any

from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from summarize_links.config import Config
from summarize_links.eval_datasets import EvalDataset
from summarize_links.eval_metrics import evaluate_summary_result
from summarize_links.exceptions import (
    ConfigError,
    ContentExtractionError,
    ContentFetchError,
    GeminiAPIError,
    OllamaAPIError,
    RateLimitError,
)
from summarize_links.extract import fetch_and_extract_metadata
from summarize_links.langfuse_tracer import get_tracer
from summarize_links.llm import create_llm_client
from summarize_links.ui import console, print_error, print_message

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


def cmd_eval(config: Config, dataset_path: str, output_path: str | None = None) -> int:
    """
    Run evaluation on a dataset.

    Args:
        config: Application configuration.
        dataset_path: Path to evaluation dataset YAML file.
        output_path: Optional path to save results YAML file.

    Returns:
        Exit code.
    """
    print_message(f"[bold]Running evaluation on: {dataset_path}[/]")

    # Load dataset
    try:
        dataset = EvalDataset.from_yaml(Path(dataset_path))
    except ConfigError as e:
        print_error(f"[red]Failed to load dataset: {e}[/]")
        return EXIT_ERROR

    print_message(f"[green]Loaded {len(dataset)} examples from '{dataset.name}'[/]")
    if dataset.description:
        print_message(f"[dim]{dataset.description}[/]")
    print_message("")

    # Create LLM client
    try:
        client = create_llm_client(
            model=config.model,
            gemini_api_key=config.gemini_api_key,
            ollama_endpoint=config.ollama_endpoint,
            mock_mode=config.mock_mode,
            state_path=config.vault_path,
            rpm_limit=config.rpm_limit,
            tpm_limit=config.tpm_limit,
            daily_limit=config.daily_limit,
        )
    except Exception as e:
        print_error(f"[red]Failed to create LLM client: {e}[/]")
        return EXIT_ERROR

    if config.mock_mode:
        print_message("[yellow]Running in mock mode (no API calls)[/]")

    tracer = get_tracer()

    # Run evaluation
    results: list[dict[str, Any]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task: TaskID = progress.add_task("[cyan]Evaluating...", total=len(dataset))

        for example in dataset:
            url = example.url
            progress.update(task, description=f"[cyan]Evaluating: {url[:50]}...")

            try:
                # Fetch content
                page_metadata = fetch_and_extract_metadata(url)

                # Generate summary
                summary_result = client.summarize_with_metadata(
                    content=page_metadata.content,
                    url=url,
                    title=example.title or page_metadata.title,
                )

                # Evaluate
                metrics = evaluate_summary_result(
                    summary_content=summary_result.content,
                    summary_tags=summary_result.suggested_tags,
                    summary_content_type=summary_result.content_type,
                    expected_tags=example.expected_tags,
                    expected_content_type=example.expected_content_type,
                    url=url,
                )

                # Score the trace in Langfuse if available
                if tracer and hasattr(tracer, "score_trace"):
                    try:
                        tracer.score_trace(
                            trace_id=url,  # Use URL as trace identifier
                            name="tag_f1_score",
                            value=metrics["tag_accuracy"].primary_score,
                            comment=f"F1 score for {len(summary_result.suggested_tags)} tags",
                        )
                        tracer.score_trace(
                            trace_id=url,
                            name="content_type_accuracy",
                            value=metrics["content_type_accuracy"].primary_score,
                            comment=f"Predicted: {summary_result.content_type}",
                        )
                    except Exception as score_error:
                        logger.debug("Failed to score trace: %s", score_error)

                results.append(
                    {
                        "url": url,
                        "title": example.title or page_metadata.title,
                        "metrics": metrics,
                        "success": True,
                        "summary_tags": summary_result.suggested_tags,
                        "summary_content_type": summary_result.content_type,
                    }
                )

            except (ContentFetchError, ContentExtractionError) as e:
                logger.warning("Fetch/extraction error for %s: %s", url, e)
                results.append(
                    {
                        "url": url,
                        "error": str(e),
                        "error_type": "fetch_error",
                        "success": False,
                    }
                )

            except (GeminiAPIError, OllamaAPIError, RateLimitError) as e:
                logger.error("API error for %s: %s", url, e)
                results.append(
                    {
                        "url": url,
                        "error": str(e),
                        "error_type": "api_error",
                        "success": False,
                    }
                )

            except Exception as e:
                logger.error("Unexpected error for %s: %s", url, e, exc_info=True)
                results.append(
                    {
                        "url": url,
                        "error": str(e),
                        "error_type": "unexpected_error",
                        "success": False,
                    }
                )

            progress.advance(task)

    # Display results
    _display_eval_results(results, dataset.name, config.model)

    # Save results if output path provided
    if output_path:
        _save_eval_results(results, dataset.name, output_path)

    # Return success if at least some examples succeeded
    success_count = sum(1 for r in results if r["success"])
    if success_count == 0:
        return EXIT_ERROR
    return EXIT_SUCCESS


def _display_eval_results(results: list[dict[str, Any]], dataset_name: str, model: str) -> None:
    """Display evaluation results in a formatted table."""
    # Collect aggregate metrics
    tag_precisions: list[float] = []
    tag_recalls: list[float] = []
    tag_f1s: list[float] = []
    content_type_accs: list[float] = []

    for result in results:
        if not result["success"]:
            continue

        metrics = result["metrics"]

        tag_precisions.append(metrics["tag_accuracy"].scores["precision"])
        tag_recalls.append(metrics["tag_accuracy"].scores["recall"])
        tag_f1s.append(metrics["tag_accuracy"].scores["f1_score"])
        content_type_accs.append(metrics["content_type_accuracy"].scores["accuracy"])

    # Summary statistics table
    if tag_precisions:
        summary_table = Table(title=f"Evaluation Results: {dataset_name}", show_header=True)
        summary_table.add_column("Metric", style="cyan", no_wrap=True)
        summary_table.add_column("Average", style="green", justify="right")
        summary_table.add_column("Min", style="white", justify="right")
        summary_table.add_column("Max", style="white", justify="right")

        summary_table.add_row(
            "Tag Precision",
            f"{sum(tag_precisions) / len(tag_precisions):.2%}",
            f"{min(tag_precisions):.2%}",
            f"{max(tag_precisions):.2%}",
        )
        summary_table.add_row(
            "Tag Recall",
            f"{sum(tag_recalls) / len(tag_recalls):.2%}",
            f"{min(tag_recalls):.2%}",
            f"{max(tag_recalls):.2%}",
        )
        summary_table.add_row(
            "Tag F1 Score",
            f"{sum(tag_f1s) / len(tag_f1s):.2%}",
            f"{min(tag_f1s):.2%}",
            f"{max(tag_f1s):.2%}",
        )
        summary_table.add_row(
            "Content Type Accuracy",
            f"{sum(content_type_accs) / len(content_type_accs):.2%}",
            f"{min(content_type_accs):.2%}",
            f"{max(content_type_accs):.2%}",
        )

        console.print(summary_table)
        console.print()

    # Per-example results table
    details_table = Table(title="Per-Example Results", show_header=True)
    details_table.add_column("URL", style="cyan", max_width=50)
    details_table.add_column("Status", style="white", justify="center")
    details_table.add_column("Tag F1", style="green", justify="right")
    details_table.add_column("Type", style="blue", justify="center")

    for result in results:
        url_display = result["url"]
        if len(url_display) > 50:
            url_display = url_display[:47] + "..."

        if result["success"]:
            metrics = result["metrics"]
            tag_f1 = f"{metrics['tag_accuracy'].primary_score:.2%}"
            type_acc = "✓" if metrics["content_type_accuracy"].primary_score == 1.0 else "✗"
            status = "[green]✓ OK[/]"
        else:
            tag_f1 = "-"
            type_acc = "-"
            error_type = result.get("error_type", "error")
            status = f"[red]✗ {error_type}[/]"

        details_table.add_row(url_display, status, tag_f1, type_acc)

    console.print(details_table)
    console.print()

    # Summary counts
    total = len(results)
    success_count = sum(1 for r in results if r["success"])
    failure_count = total - success_count

    print_message(f"[bold]Summary:[/] Model: {model}")
    print_message(f"[bold]Total examples:[/] {total}")
    print_message(f"[green]Successful:[/] {success_count}")
    if failure_count > 0:
        print_message(f"[red]Failed:[/] {failure_count}")


def _save_eval_results(results: list[dict[str, Any]], dataset_name: str, output_path: str) -> None:
    """Save evaluation results to a YAML file."""
    from datetime import datetime

    import yaml

    # Convert MetricResult objects to dictionaries
    output_results: list[dict[str, Any]] = []
    output_data: dict[str, Any] = {
        "dataset_name": dataset_name,
        "evaluation_date": datetime.now().isoformat(),
        "total_examples": len(results),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": output_results,
    }

    for result in results:
        result_entry: dict[str, Any] = {
            "url": result["url"],
            "success": result["success"],
        }

        if result["success"]:
            metrics = result["metrics"]
            result_entry["metrics"] = {
                "tag_accuracy": {
                    "precision": metrics["tag_accuracy"].scores["precision"],
                    "recall": metrics["tag_accuracy"].scores["recall"],
                    "f1_score": metrics["tag_accuracy"].scores["f1_score"],
                },
                "content_type_accuracy": metrics["content_type_accuracy"].scores["accuracy"],
            }
            result_entry["summary_tags"] = result.get("summary_tags", [])
            result_entry["summary_content_type"] = result.get("summary_content_type", "")
        else:
            result_entry["error"] = result.get("error", "Unknown error")
            result_entry["error_type"] = result.get("error_type", "unknown")

        output_results.append(result_entry)

    # Calculate aggregates
    successful_results = [r for r in results if r["success"]]
    if successful_results:
        output_data["aggregates"] = {
            "avg_tag_precision": sum(
                r["metrics"]["tag_accuracy"].scores["precision"] for r in successful_results
            )
            / len(successful_results),
            "avg_tag_recall": sum(
                r["metrics"]["tag_accuracy"].scores["recall"] for r in successful_results
            )
            / len(successful_results),
            "avg_tag_f1": sum(
                r["metrics"]["tag_accuracy"].scores["f1_score"] for r in successful_results
            )
            / len(successful_results),
            "avg_content_type_accuracy": sum(
                r["metrics"]["content_type_accuracy"].scores["accuracy"] for r in successful_results
            )
            / len(successful_results),
        }

    # Write to file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print_message(f"[green]Saved evaluation results to: {output_path}[/]")
