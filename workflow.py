from pathlib import Path

from workflow_tasks.lrfhss_flowtask import run_workflow as run_reference_series_workflow

__all__ = ["run_workflow"]


def run_workflow(
    multi_beam_root: Path,
    lrfhss_root: Path,
    output_dir: Path,
    seed: int,
    node_min: int,
    node_max: int,
    node_points: int,
    demodulator_options: list[int],
    nodes_list: list[int] | None,
    reference_csv: Path,
    scenario_steps: int = 120,
    step_seconds: float = 228.0,
    runs_per_point: int = 10,
):
    return run_reference_series_workflow(
        multi_beam_root=multi_beam_root,
        lrfhss_root=lrfhss_root,
        output_dir=output_dir,
        seed=seed,
        node_min=node_min,
        node_max=node_max,
        node_points=node_points,
        demodulator_options=demodulator_options,
        nodes_list=nodes_list,
        reference_csv=reference_csv,
        scenario_steps=scenario_steps,
        step_seconds=step_seconds,
        runs_per_point=runs_per_point,
    )
