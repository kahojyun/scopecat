# Subsystems

## Status

Subsystem documentation index.

## Purpose

Each subsystem owns its product brief, standalone adoption story, domain
concepts, architecture notes, specs, and subsystem-specific decisions.

The subsystem docs live under `docs/` because these are design boundaries, not
source-code package boundaries. Future source packages may have their own
near-code README files and implementation notes.

## Subsystem Template

```text
docs/subsystems/<name>/
  README.md
  product/
    product-brief.md
    standalone-adoption.md
    user-stories.md
    non-goals.md
  domain/
    README.md
    <concept-card>.md
  architecture/
    README.md
    <architecture-topic>.md
  specs/
    <subsystem-prefix>-001-<topic>.md
  decisions/
    <SUBSYSTEM>-ADR-0001-<decision>.md
```

## Concept Card Template

```markdown
# Concept Name

## Owner

## Purpose

## Identity

## Lifecycle

## References

## Does Not Own

## Migration Notes

## Open Questions
```
