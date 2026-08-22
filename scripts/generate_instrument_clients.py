"""Generate Scopecat's first-party instrument package and codegen fixtures."""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from scopecat.sdk.instruments.client_codegen import (
    AcquisitionPublicNames as AcquisitionPublicNames,
)
from scopecat.sdk.instruments.client_codegen import (
    CatalogTarget,
    CompositeClientSurface,
    GenerationSurface,
    InstrumentClientManifest,
    clients_for,
    clients_for_composite,
    generate_instrument_package,
)
from scopecat.sdk.instruments.client_codegen import (
    render_client_module as render_client_module,
)
from scopecat.sdk.instruments.declarations import Member

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTS_PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-instruments"
FIXTURE_MODULE = "scopecat_testkit.instrument_codegen_fixtures"
FIXTURE_PACKAGE_ROOT = (
    REPOSITORY_ROOT
    / "testing"
    / "scopecat-testkit"
    / "src"
    / "scopecat_testkit"
    / "instrument_codegen_fixtures"
)


class _Options(argparse.Namespace):
    check: bool = False
    fixtures: bool = True
    manifest: str = "scopecat_instruments.package_manifest:PACKAGE_MANIFEST"
    output_root: Path = INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments"
    package_module: str = "scopecat_instruments"


class _FixtureDeclarations(Protocol):
    CatalogProjectionInterface: type[object]
    DriverFixedAcquisitionInterface: type[object]
    DriverMonitorInterface: type[object]
    DriverSourceInterface: type[object]
    LiteralOperationInterface: type[object]
    PayloadOperationInterface: type[object]
    ScalarOperationInterface: type[object]
    SharedAcquisitionResultInterface: type[object]
    SharedPropertyFirstInterface: type[object]
    SharedPropertySecondInterface: type[object]


def _fixture_declarations() -> _FixtureDeclarations:
    return cast(
        "_FixtureDeclarations",
        cast("object", import_module(f"{FIXTURE_MODULE}.declarations")),
    )


def _fixture_member(interface_type: type[object], name: str) -> Member[object]:
    return cast("Member[object]", getattr(interface_type, name))


def _fixture_catalog_surfaces(
    declarations: _FixtureDeclarations,
) -> tuple[GenerationSurface, ...]:
    return (
        clients_for(declarations.ScalarOperationInterface),
        clients_for(declarations.LiteralOperationInterface),
        clients_for(declarations.PayloadOperationInterface),
        clients_for(declarations.DriverFixedAcquisitionInterface),
        clients_for(declarations.DriverSourceInterface),
        clients_for_composite(
            "MonitorComposite",
            declarations.DriverSourceInterface,
            declarations.DriverMonitorInterface,
            driver_optional_flag="monitor",
            member_name_overrides=(
                (
                    _fixture_member(declarations.DriverSourceInterface, "enabled"),
                    "source_enabled",
                ),
                (
                    _fixture_member(declarations.DriverMonitorInterface, "enabled"),
                    "monitor_enabled",
                ),
            ),
        ),
    )


def _fixture_catalog_target() -> CatalogTarget:
    declarations = _fixture_declarations()
    surfaces = _fixture_catalog_surfaces(declarations)
    interface_types: list[type[object]] = [
        declarations.CatalogProjectionInterface,
        declarations.SharedAcquisitionResultInterface,
        declarations.SharedPropertyFirstInterface,
        declarations.SharedPropertySecondInterface,
    ]
    composites: list[CompositeClientSurface] = []
    for surface in surfaces:
        if isinstance(surface, CompositeClientSurface):
            selected = surface.interface_types
            composites.append(surface)
        else:
            selected = (surface.interface_type,)
        for interface_type in selected:
            if interface_type not in interface_types:
                interface_types.append(interface_type)
    return CatalogTarget(
        members_output=FIXTURE_PACKAGE_ROOT / "generated_members.py",
        interfaces_output=FIXTURE_PACKAGE_ROOT / "generated_interfaces.py",
        projections_output=FIXTURE_PACKAGE_ROOT / "generated_projections.py",
        members_module=f"{FIXTURE_MODULE}.generated_members",
        interface_types=tuple(interface_types),
        composite_surfaces=tuple(composites),
    )


def _load_manifest(symbol: str) -> InstrumentClientManifest:
    module_name, separator, attribute = symbol.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("manifest must use the form 'module:attribute'")
    return cast(
        "InstrumentClientManifest", getattr(import_module(module_name), attribute)
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--manifest",
        default="scopecat_instruments.package_manifest:PACKAGE_MANIFEST",
    )
    parser.add_argument("--package-module", default="scopecat_instruments")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments",
    )
    parser.add_argument(
        "--fixtures",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    options = _Options()
    parser.parse_args(argv, namespace=options)
    manifest = _load_manifest(options.manifest)
    stale = generate_instrument_package(
        manifest,
        package_module=options.package_module,
        output_root=options.output_root.resolve(),
        check=options.check,
        additional_catalog_targets=(
            (_fixture_catalog_target(),) if options.fixtures else ()
        ),
    )
    if stale:
        print(
            "generated instrument sources are stale ("
            + ", ".join(str(path) for path in stale)
            + "); run scripts/generate_instrument_clients.py without --check",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
