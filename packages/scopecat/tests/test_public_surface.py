from __future__ import annotations

import scopecat as sc
import scopecat.diagnostics as diagnostics
import scopecat.results as results


def test_user_facing_facades_expose_entry_points() -> None:
    assert callable(sc.open)
    assert sc.Run is sc.RunHandle
    assert callable(sc.module)
    assert not hasattr(sc, "template")
    assert callable(sc.ModuleBuilder.template)
    assert callable(sc.ExperimentModule.template)
    assert callable(sc.var)
    assert callable(sc.param)
    assert callable(sc.table_param)
    assert callable(sc.input_series)
    assert callable(sc.input_table)
    assert callable(sc.compute_result)
    assert sc.compute_result("node") == sc.ComputeResultRef(node_id="node")
    assert not hasattr(sc, "compute_payload")
    assert not hasattr(sc, "ComputePayloadRef")
    assert callable(sc.parameter_table)
    assert sc.ScalarType(sc.IntType())
    assert sc.SeriesType(sc.ScalarType(sc.EntityType()))
    assert sc.TableType(columns=())
    assert not hasattr(sc, "EntityArray")
    assert not hasattr(sc, "entity_array")
    assert callable(sc.scan_axis_index)
    assert callable(sc.parameter_scan_records)
    assert sc.PointScanRecord(kind="point", target_id="x", axis_id="x", values=[1])
    assert sc.AroundScanRecord(
        kind="scan", target_id="x", axis_id="x", center=1, span=2, points=3
    )
    assert sc.ParameterScanRecord(
        kind="parameter",
        table_id="table",
        key={},
        column="column",
        axis_id="axis",
        values=[1],
    )
    assert sc.ScanGroupRecord(
        kind="zip",
        scans=[
            sc.PointScanRecord(
                kind="point",
                target_id="x",
                axis_id="x",
                values=[1],
            )
        ],
    )
    assert hasattr(results, "MeasurementRecord")
    assert {"severity", "code"}.issubset(diagnostics.Diagnostic.model_fields)


def test_workspace_terminals_are_prepare_or_scratch_only() -> None:
    assert callable(sc.Workspace.prepare)
    assert callable(sc.Workspace.experiment)

    assert callable(sc.PreparedExperiment.run)
    assert callable(sc.PreparedExperiment.preview)
    assert callable(sc.PreparedExperiment.validate)
    assert callable(sc.Experiment.run)
    assert callable(sc.Experiment.preview)
    assert callable(sc.Experiment.validate)
