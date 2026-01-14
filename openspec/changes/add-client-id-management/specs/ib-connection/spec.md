## ADDED Requirements

### Requirement: Client ID Configuration
The system SHALL allow users to configure a `client_id_start` value that sets the base/floor for all client IDs used by iborker tools.

#### Scenario: Default client ID start
- **WHEN** no `client_id_start` is configured
- **THEN** the system uses 1 as the default base

#### Scenario: Custom client ID start via environment
- **WHEN** `IB_CLIENT_ID_START=100` is set
- **THEN** all tool client IDs start from 100

#### Scenario: Custom client ID start via .env file
- **WHEN** `.env` contains `IB_CLIENT_ID_START=50`
- **THEN** all tool client IDs start from 50

### Requirement: Automatic Client ID Allocation
The system SHALL automatically assign unique client IDs to each tool type to prevent connection conflicts.

#### Scenario: Different tools get different IDs
- **WHEN** `client_id_start=1` and CLI history command runs
- **THEN** CLI uses client_id = client_id_start + 0 (base offset for CLI)
- **WHEN** click trader GUI runs concurrently
- **THEN** trader uses client_id = client_id_start + 10 (reserved offset for trader)

#### Scenario: Tool type offset mapping
- **WHEN** allocating client IDs
- **THEN** the system uses fixed offsets per tool:
  - CLI commands: +0 to +9
  - Click Trader: +10 to +19
  - Stdev Analyzer: +20 to +29
  - Reserved for future: +30+

### Requirement: Concurrent Process Safety
The system SHALL prevent client ID collisions when multiple instances of the same tool type run concurrently.

#### Scenario: Multiple CLI commands running
- **WHEN** two `iborker history download` commands run simultaneously
- **THEN** each gets a unique client ID within the CLI range (e.g., base+0 and base+1)

#### Scenario: Lock file prevents collision
- **WHEN** a process acquires client_id = base+0
- **THEN** a lock file is created at `~/.iborker/locks/client_<id>.lock`
- **WHEN** another process requests the same tool type
- **THEN** it increments and tries the next available ID in the range

#### Scenario: Lock cleanup on exit
- **WHEN** a process terminates (normally or via signal)
- **THEN** its lock file is removed

### Requirement: Fixed Client ID Mode
The system SHALL support a `client_id_mode=fixed` option for users who want explicit control over client IDs.

#### Scenario: Fixed mode uses single ID
- **WHEN** `client_id_mode=fixed` and `client_id=5`
- **THEN** all tools use client_id=5 (user manages conflicts)

#### Scenario: Auto mode is default
- **WHEN** `client_id_mode` is not set
- **THEN** automatic allocation is used
