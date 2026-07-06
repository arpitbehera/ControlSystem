"""Minimal `lab` operator CLI."""

from __future__ import annotations

import grpc
import typer

from proto_gen import lifecycle_pb2, run_model_pb2, scheduler_pb2, scheduler_pb2_grpc

app = typer.Typer(no_args_is_help=True)


def _stub(host: str, port: int) -> scheduler_pb2_grpc.SchedulerStub:
    return scheduler_pb2_grpc.SchedulerStub(grpc.insecure_channel(f"{host}:{port}"))


@app.command("submit-run")
def submit_run(
    user: str = typer.Option(...),
    template: str = typer.Option(...),
    params: str = typer.Option("{}", help="JSON object of parameters"),
    key: str = typer.Option(..., help="idempotency key"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(50070),
) -> None:
    resp = _stub(host, port).Enqueue(
        run_model_pb2.RunRequest(
            user=user,
            template_name=template,
            parameters_json=params,
            idempotency_key=key,
        ),
        timeout=10,
    )
    if resp.WhichOneof("outcome") == "rejected":
        typer.echo(f"rejected: {resp.rejected.code}: {resp.rejected.reason}")
        raise typer.Exit(code=1)
    typer.echo(
        f"accepted job_uuid={resp.accepted.job_uuid}"
        f" descriptor_id={resp.accepted.descriptor_id}"
        f" snapshot_id={resp.accepted.snapshot_id}"
    )


def _cancel(target: str, kind: str, by: str, host: str, port: int) -> None:
    resp = _stub(host, port).Cancel(
        run_model_pb2.CancelRequest(
            target=target,
            target_kind=kind,
            requested_by=by,
            idempotency_key=f"cancel-{target}",
        ),
        timeout=10,
    )
    if not resp.ok:
        typer.echo(f"cancel failed: {resp.error}")
        raise typer.Exit(code=1)
    typer.echo(f"cancelled: state={resp.state}")


@app.command("cancel-job")
def cancel_job(
    job_uuid: str,
    by: str = typer.Option("operator"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(50070),
) -> None:
    _cancel(job_uuid, "job", by, host, port)


@app.command("cancel-run")
def cancel_run(
    run_uuid: str,
    by: str = typer.Option("operator"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(50070),
) -> None:
    _cancel(run_uuid, "run", by, host, port)


@app.command("list-runs")
def list_runs(
    limit: int = typer.Option(20),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(50070),
) -> None:
    resp = _stub(host, port).ListRuns(
        scheduler_pb2.ListRunsRequest(limit=limit), timeout=10
    )
    for row in resp.runs:
        typer.echo(f"{row.run_uuid}  {row.state:12s}  {row.template_name}  {row.user}")


@app.command("status")
def status(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(50070),
    events: int = typer.Option(3),
) -> None:
    stream = _stub(host, port).Status(
        lifecycle_pb2.StatusRequest(),
        timeout=events * 2 + 5,
    )
    for index, event in enumerate(stream):
        typer.echo(f"{event.service_id} {event.state} {event.kind}")
        if index + 1 >= events:
            break


if __name__ == "__main__":
    app()
