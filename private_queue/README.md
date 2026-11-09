# Encrypted candidate queue

A read-only scheduled scan retains a candidate queue encrypted with Fernet before committing it to the public repository. The encryption key is a GitHub Actions secret; plaintext queue, media, source text and the publication ledger never go into the repository. The workflow handles a failed source check without updating its state; scheduled runs and this encryption do not establish completeness of the source. Losing the key means losing the ability to decrypt the state. Rotating the key requires re-encrypting the existing state first.

This is NOT a publishing pipeline. All candidates await audio review, and no audio is cleared or published. The original local queue and this encrypted copy are separate; do not use either for publishing until their publication ledgers and pending items can be safely synchronized and uncertain uploads reconciled. The runner may be delayed or skipped by GitHub. Manual and scheduled results must be distinguished. The workflow uses standard Python cryptography and writes plaintext only to an ephemeral restricted runner directory, which is removed when the process completes; no queue contents are printed.

## Candidate-to-provider integration under preparation

`candidate_pipeline.py` links candidate identity and media hash to the existing
WoopSocial upload/draft adapter. The pipeline requires an independently authenticated
full-audio review bound to exact bytes, but no such verifier exists yet. The code has
no command-line entry point and no scheduler, and it never publishes. `git_checkpoint.py`
provides encrypted remote checkpoints that reject a divergent branch and never rebase.
Both modules are tested locally with fakes only; they are not wired into a GitHub job.
Unknown upload/draft outcomes remain blocked, and require provider reconciliation.
A confirmed draft is not a successful YouTube publication. Existing live synthetic
test receipts must not be retried or replaced.

The encrypted queue workflow now invokes `workflow_pipeline.py` after a scan and
preparation. It registers one exact-byte candidate in the delivery state using a
remote encrypted checkpoint. Production supplies no review verifier, so it stops
at `awaiting_audio_review` and performs no provider write. The same entry function
is exercised with a fake provider and a temporary encrypted Git remote for draft,
restart, and unknown-result protection; that synthetic test is not a live upload.
This does not publish or establish music-free audio. Full audio review bound to
the exact bytes, a production review verifier, live delivery and a confirmed
scheduled run remain necessary.
