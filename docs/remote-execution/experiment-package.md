# Experiment Package

## Status

Architecture hypothesis.

## Purpose

An `ExperimentPackage` is a portable, immutable artifact that represents the
experiment intent locally previewed by a user and later submitted for remote
validation and execution.

## Candidate Fields

- package ID
- author
- created time
- scan plan snapshot
- parameter snapshot reference and hash
- code asset references and hashes
- required resources
- lease policy
- expected dataset schema
- safety constraints
- preview summary
- plan hash
- execution policy

## Principle

Remote execution must execute the same plan that was locally previewed.
