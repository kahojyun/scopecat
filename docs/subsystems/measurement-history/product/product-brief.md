# Measurement History Product Brief

## Status

Draft.

## User Promise

Users can record measurement data from ordinary Python scripts, inspect simple
live views, survive ordinary interruptions with already-written data readable,
and reopen measurements or datasets by stable ID.

## First Slice

- local data library
- measurement identity
- dataset identity
- trace-valued and array-valued recording
- generic irregular step records
- simple live line, scatter, heatmap, magnitude/phase, and I/Q views
- checkpoint-safe readability after ordinary interruption
- stable-ID copy and reopen

## Non-Goals

- managed runner requirement
- device-control framework
- scheduler
- hosted service
- old-history import prerequisite
