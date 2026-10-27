# Team notification preferences

## Goal
Let signed-in teammates choose which board updates they receive.

## Users
Existing members of the shared workspace. Use the current login system.

## First release
- Save notification preferences for the signed-in person.
- Show a settings form to change those preferences.
- Show confirmation after a successful save and a clear error after a failure.
- Keep selected choices when saving fails.
- Verify that a saved choice remains after refreshing the page.

## Constraints
Reuse the existing FastAPI backend and board frontend. Do not build another login.
Build the API before connecting the settings form. Cover the workflow with tests.

## Out of scope
Email delivery, mobile push, billing, and automatic stage changes.
