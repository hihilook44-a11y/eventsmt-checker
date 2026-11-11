# Conditional automatic compilations

`compilation-delivery.yml` runs every day at 03:31 UTC and supports manual dispatch.
It shares the encrypted queue concurrency group with Shorts/source scanning.
It uses the existing queue encryption, audio-review public key and Zernio secrets;
there is no new credential or service.

The workflow automatically:

1. Reconciles known compilation post IDs against the exact YouTube destination.
2. Downloads candidate files and checks full-audio, exact-byte signed proofs.
3. Selects full unique source clips until their total reaches at least 600 seconds.
   Exact source metadata is retained in the encrypted compilation archive before
   published Shorts leave the discovery queue. The archive grants no audio clearance.
   Previously posted Shorts can be compilation material, but previously compiled
   sources or identical media cannot be reused. Footage is never looped/padded.
4. Re-verifies bytes and proofs immediately before normalizing to 1280x720, 25fps,
   with original audio transcoded to AAC (no added music and no speech deletion).
5. Builds a source-description-derived title and source-linked description; makes
   a 1280x720 JPEG thumbnail from two source frames with Arabic text shaping.
6. Checkpoints the encrypted attempt before video upload, thumbnail upload, and
   scheduling a public YouTube video through Zernio. It schedules at least 15
   minutes after the initial delivery attempt, and independently reads back the
   post/destination/status. Only a provider-confirmed PUBLISHED status counts.

If fewer than ten cleared minutes exist, it exits without creating/uploading a
compilation. A pending or uncertain attempt blocks another attempt. There is no
blind retry of uploads or post creation; the uncertain record and any known post
ID are retained for reconciliation. A checkpoint failure stops before the next
provider write. Published compilations have a minimum 24-hour interval.

This workflow is NOT proof of reliable automatic song detection. YAMNet,
EfficientAT and PANNs tests missed real controlled music cases. Their scores never
create or impersonate signed reviews. See MUSIC_TRIAGE.md. As a result, the full
no-manual-review outcome is still blocked for new audio-bearing clips. This is
an actual conditional compilation delivery path, not a claim that a compilation
has already been published or that current material reaches ten minutes.

Tests include deterministic fake-provider lifecycle and uncertainty cases and an
isolated real-ffmpeg synthetic render. Unit tests lower the minimum to three
seconds only inside a patch; production keeps the 600-second minimum. Synthetic
media/proofs are never fed to the real encrypted queue or provider.

The older two-hour private-queue workflow still uses
`compilation_assessment.py` as a read-only readiness check (four-minute timeout).
It emits counts only, does not mutate the encrypted queue, and does not create a
render or submission. Scheduling is subject to GitHub availability; it is not a
precise timer, and neither workflow establishes complete source coverage.
