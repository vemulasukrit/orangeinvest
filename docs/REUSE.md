# Reference adaptation

Read-only reference files in the sibling `voiceosv2` checkout were inspected directly. No reference file was modified, no credentials were read, and no Electron or production infrastructure was copied.

* `main/subscription-integrations.cjs`, lines 190–208: owner-bound prepare/execute checks and consumed approval records informed session-bound proposals and durable approval rows. Here the state machine also binds exact price, slot, revision and hold using a recomputed fingerprint.
* `main/app-actions.cjs`, lines 575–613: locking a ticket before asynchronous work and replacing approval on edits informed serialized local actions, invalidation on fact changes and writing the durable operation before provider mutation.
* `renderer/browser/memory.js`, lines 101–136: provenance labels and explicit forget informed stated/inferred preference records, confirmation before reuse and removing inherited active context when forgetting.

The implementation is a small Python stdlib adaptation of these principles, with independent SQLite persistence and mock tool code. It does not reuse the gateway, renderer, networking, integrations, secrets or the full reference application's memory system.
