## MODIFIED Requirements

### Requirement: Environment binding remains a single collection-level property
The environment SHALL be bound at the collection level only; there is no per-request environment. All requests within a collection SHALL resolve their variables against the collection's single bound environment.

#### Scenario: Binding shared across requests in a collection
- **WHEN** the user binds an environment while editing one request and then runs a different request in the same collection
- **THEN** the second request resolves its variables against the same bound environment

#### Scenario: Run-time variable precedence favors the collection's current value
- **WHEN** a collection variable and an environment variable share the same key at run time
- **THEN** the collection variable's current value takes precedence, as it did before this change — where, per `collection-runtime-variables`, the collection's "current value" for a key a script has captured is scoped to the environment that was bound at capture time, not simply the most recently captured value

#### Scenario: Switching or unsetting the environment stops a stale script-captured value from taking precedence
- **WHEN** a script previously captured a collection variable's value while a different environment (or no environment) was bound, and the user then binds a different environment
- **THEN** that stale script-captured value no longer takes precedence over the environment variable of the same key; the collection variable resolves to its static default, or is treated as unset if it has none
