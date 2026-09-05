## Purpose

Lets a user reach a collection's configuration — its bound environment and variables, plus its auth, schema-check and negative-testing defaults — from any API view including the request editor, so the affordance to act lives where the need arises rather than only in the collection's settings. Environment binding remains a single collection-level property, and collection-scoped settings stay distinct from the editor's request-scoped tabs.

## ADDED Requirements

### Requirement: Environment selector is available in the request editor
The request editor SHALL present an environment selector in its own view that reflects the environment currently bound to the request's collection, so the user never has to leave the editor to see or change which environment is active.

#### Scenario: Editor opened with an environment bound
- **WHEN** the user opens a request whose collection is bound to an environment
- **THEN** the request editor shows a selector displaying that environment's name

#### Scenario: Editor opened with no environment bound
- **WHEN** the user opens a request whose collection has no environment bound
- **THEN** the request editor shows a selector displaying a "No environment" state

### Requirement: Selecting an environment binds it to the collection consistently across views
Choosing an environment from any API view (the request editor or the collection view) SHALL persist the selection as the collection's bound environment, and every view that shows the collection's environment SHALL reflect the same selection.

#### Scenario: Selecting an environment in the request editor
- **WHEN** the user picks an environment in the request editor's selector
- **THEN** that environment becomes the collection's bound environment and is used to resolve the request's variables

#### Scenario: Selection is saved immediately and confirmed
- **WHEN** the user picks or clears an environment in a selector
- **THEN** the binding is persisted at once (no separate save action) and the user is shown a brief confirmation of what was set

#### Scenario: Binding made in the editor is visible in the collection view
- **WHEN** the user binds an environment from the request editor and then opens that collection's view
- **THEN** the collection view's environment selector shows the same bound environment

#### Scenario: Binding changed elsewhere updates the open editor
- **WHEN** the collection's bound environment is changed from the collection view while a request editor for that collection is open
- **THEN** the open editor reflects the new environment without being closed and reopened

### Requirement: A new environment can be created and bound without leaving the current view
The user SHALL be able to create a new environment inline from the environment selector and have it bound to the current collection in one step, without navigating away.

#### Scenario: Creating a new environment from the request editor
- **WHEN** the user chooses the create-environment action and provides a name
- **THEN** a new environment with that name is created and becomes the collection's bound environment

#### Scenario: Creating an environment that already exists
- **WHEN** the user attempts to create an environment whose name already exists in the project
- **THEN** the user is informed and no duplicate environment is created

### Requirement: The variable picker empty state offers actions instead of a dead message
When no variables are available to insert, the variable picker SHALL present actions to select or create an environment and to add a variable, rather than only displaying informational text.

#### Scenario: No environment and no variables
- **WHEN** the variable picker opens and there is neither a bound environment nor any collection variable
- **THEN** the picker presents an action to select or create an environment and an action to add a variable

#### Scenario: The environment action opens the environment chooser
- **WHEN** the user chooses the select/create-environment action from the empty state
- **THEN** the environment selector's chooser opens so an environment can be picked or created (not merely focused)

#### Scenario: Acting on the empty state resolves it
- **WHEN** the user completes an add-variable or select/create-environment action from the empty state
- **THEN** the picker refreshes and shows the resulting variables without the editor being reopened

### Requirement: A variable can be added from the request editor
The user SHALL be able to add a collection variable from within the request editor without navigating away, by opening the collection's Variables editing surface in context, and the newly added variable SHALL become available to insert as `{{key}}`.

#### Scenario: Adding a variable opens the collection's Variables surface
- **WHEN** the user chooses to add a variable from the request editor's variable picker
- **THEN** the collection's Variables editing surface opens in context with a new, empty, editable variable row ready for input, focused on the variable name

#### Scenario: The added variable becomes insertable
- **WHEN** the user saves a new collection variable from that surface and returns to the request
- **THEN** the variable appears in the picker as an insertable `{{key}}` without the editor being reopened

### Requirement: Environment binding remains a single collection-level property
The environment SHALL be bound at the collection level only; there is no per-request environment. All requests within a collection SHALL resolve their variables against the collection's single bound environment.

#### Scenario: Binding shared across requests in a collection
- **WHEN** the user binds an environment while editing one request and then runs a different request in the same collection
- **THEN** the second request resolves its variables against the same bound environment

#### Scenario: Run-time variable precedence is unchanged
- **WHEN** a collection variable and an environment variable share the same key at run time
- **THEN** the collection variable's value takes precedence, as it did before this change

### Requirement: Collection settings are reachable from the request editor
The request editor SHALL provide a way to view and edit the collection's settings — its auth, variables, schema-check and negative-testing defaults — in context, without navigating away from the request being edited, and any change made there SHALL persist to the collection.

#### Scenario: Opening collection settings from the editor
- **WHEN** the user opens the collection-settings surface from the request editor
- **THEN** the collection's auth, variables, schema-check and negative-testing settings are shown, identified as belonging to that collection by name

#### Scenario: Editing a collection setting from the editor
- **WHEN** the user changes a collection-level setting from that surface and saves it
- **THEN** the change persists to the collection and applies to every request that inherits it, the same as editing it from the collection view

#### Scenario: Returning to the request
- **WHEN** the user closes the collection-settings surface
- **THEN** the request editor is exactly as it was left, with no loss of unsaved request edits

### Requirement: The request's Save is distinct from the collection controls
The editor's Save action SHALL apply only to the request being edited, and SHALL be presented so it is not mistaken for the environment and collection-settings controls beside it — which persist on their own without a Save.

#### Scenario: Save reflects only unsaved request edits
- **WHEN** the user changes the bound environment or opens the collection settings, but has made no edit to the request itself
- **THEN** the Save action does not present itself as having pending changes to save

#### Scenario: Editing the request enables Save
- **WHEN** the user edits a field of the request (URL, params, headers, body, scripts, etc.)
- **THEN** the Save action becomes available, and returns to its idle state once the request is saved

### Requirement: Request-scoped and collection-scoped settings remain distinct
Surfacing collection settings in the request editor SHALL NOT merge them into the editor's own request-scoped tabs; a setting that exists at both scopes (auth, schema-check, negative-testing) SHALL be presented so the user can tell which scope they are editing.

#### Scenario: No duplicate same-named tabs in the editor tab strip
- **WHEN** the collection-settings surface is available in the request editor
- **THEN** the editor's own request-scoped tab strip is unchanged and does not gain a second Auth, Schema Check or Negative tab

#### Scenario: Scope is labeled
- **WHEN** the user is editing an auth, schema-check or negative-testing setting that exists at both the request and collection scope
- **THEN** the surface makes clear whether the value being edited applies to this request or to the whole collection
