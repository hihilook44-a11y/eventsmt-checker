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

## Reviewed delivery (not configured)

The workflow can call `publish_reviewed` only for a pending, prepared candidate with a signed whole-audio review, exact file hash and configured YouTube destination. It requires `AUDIO_REVIEW_PUBLIC_KEY` (base64 raw Ed25519 public key), `WOOPSOCIAL_PROJECT_ID` and `WOOPSOCIAL_YOUTUBE_ACCOUNT_ID` as independently provisioned Actions secrets. No key, trusted reviewer, review capture or approval is provisioned by this code. Signatures only verify the origin and content of an attestation; they do not establish that the reviewer actually listened. Never sign or insert an attestation without a real full-audio review. Reviews would need to be stored under `audio_reviews` in the encrypted state using the schema in `audio_review.py`, via a secure authenticated review process that is not yet built. With any required setting absent or malformed, no audio candidate is promoted to public delivery. The recipient must be the intended verified account, and state is checkpointed before remote writes; uncertain outcomes must be investigated before retry. Local tests and synthetic draft uploads do not establish a live scheduled YouTube delivery.

### Original files without audio streams

The verifier can also inspect the exact downloaded source bytes with `ffprobe` and allow a valid video with no audio streams through the review gate. This does not mute or transcode a file. Any audio stream, unreadable file or failed probe still requires the separately authenticated full-audio human review. Metadata only selects candidates for a fresh exact-byte check, and a changed file is rejected by the saved hash. This does not classify speech or music, cannot certify any file with an audio stream as song-free, and does not activate the disabled delivery step. Tests use mock providers and do not establish live delivery.

The `review_intake.prepare_reviews` helper prepares signed proofs only from explicit, authenticated owner responses confirming full listening and per-clip `no_songs` verdicts. Callers must interpret the owner's actual message, not infer that unmentioned clips are clear. The helper checks the review manifest, exact local file hash, pending candidate and matching prepared/delivery record, and refuses existing or uncertain records. It returns proofs in memory; it does not write the queue, enable delivery, provision a signing key or verify that the reviewer listened. To use later: register eligible source bytes under their exact hash, call the helper only for explicitly reviewed clips, provision a persistent private signing key and corresponding trusted public key, and merge proofs into the latest encrypted snapshot with the existing conflict-safe checkpoint. A full owner review and an actual successful checkpoint remain prerequisites.


## Zernio scheduled delivery path (code ready, not activated)

`zernio_adapter.py` implements a scoped YouTube posting transport: it verifies the configured connected account under the configured Zernio profile, uploads reviewed media through Zernio's presigned media flow, and creates one public YouTube post scheduled 15 minutes ahead. The workflow still runs its encrypted candidate scan on its existing two-hour GitHub Actions schedule. Each API create carries a stable per-account/source/media idempotency key and source metadata.

The delivery path remains fail-closed: the existing signed whole-audio review and exact-byte hash checks run before upload; an unreviewed media item cannot be scheduled. Queue state is checkpointed before the remote create. Scheduled posts are reconciled from Zernio on later runs; confirmed publication adds the source to the duplicate ledger. Failed or uncertain states are not retried automatically. Zernio support requires `ZERNIO_API_KEY`, `ZERNIO_PROFILE_ID` and `ZERNIO_YOUTUBE_ACCOUNT_ID` GitHub Actions secrets. These secrets have not been provisioned in this code change; without them the workflow retains the prior provider path. Unit tests use mocked HTTP only and do not publish or schedule a real video.
