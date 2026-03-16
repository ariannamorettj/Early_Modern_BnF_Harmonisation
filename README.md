## Early Modern BnF Dataset Harmonisation Workflow

The software is organised through a **nested numerical folder system** designed to preserve execution order, make the workflow easier to navigate, and support partial or repeated re-execution of individual stages without restructuring the project.

At the highest level, the numbering reflects the main functional areas of the workflow.  
Within each area, subfolders follow the same logic, so that each component can be located, executed, tested, or resumed in a predictable way.

### `00_test`

This directory contains the automated test suite for the main workflow components.  
Its purpose is to verify the deterministic behaviour of the scripts, the correctness of key formulas and helper functions, and the expected structure of outputs and resume logic.

### `00_monitor`

This directory contains the system monitoring utilities used to record machine-level and process-level metrics during long-running executions.  
It includes aligned Python and R implementations and supports both standalone execution and embedded use within other workflow scripts.

### `01_data_retrieval`

This directory contains the data acquisition stage of the workflow.  
It includes the scripts used to retrieve bibliographic and actor-related data, organise intermediate outputs, and generate the main raw datasets used by later workflow steps.

## Documentation Structure

Each main directory includes its own internal `README.md` file with more detailed technical documentation about:

- purpose
- internal structure
- execution behaviour
- inputs and outputs
- tests and monitoring, where applicable

The present README only provides the general project-level overview.