"""Settings for the how-to article generation runtime.

Deliberately tiny, for the same reason as `aeo-skill-builder-runtime`'s: this
runtime reads a model id, a region and a build stamp, and nothing else.

⚠️ **There is no `DATABASE_URL` here, and there must never be one.** This runtime
is **emit-only**: it returns a draft article and a similarity measurement, and the
gateway performs every write. It holds no database handle and no network write
authority, which is also the prompt-injection backstop — the org context it reads
is tenant-authored free text, and the strongest containment available is that the
process reading it cannot write anywhere. If a future change here wants a
connection string, that is the signal to stop and re-read
`okf/business/emit-only.md`, not to add a field.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Model -------------------------------------------------------------
    #: Claude Sonnet 5 on Bedrock, matching the sibling runtime's choice.
    #:
    #: 🔴 The bare `anthropic.` prefix is CORRECT — do not "normalise" it to
    #: `us.anthropic.…`. Prefix forms are per-endpoint: we call Claude through
    #: the Bedrock **Mantle** client, which wants the bare form and 404s on the
    #: other, while `bedrock-runtime` wants exactly the opposite. This cost the
    #: sibling runtime a debugging session; it is written down so it costs this
    #: one nothing.
    HOWTO_GENERATION_MODEL_ID: str = "anthropic.claude-sonnet-5"
    HOWTO_GENERATION_AWS_REGION: str = "us-east-1"

    #: Generation is one long-form article, not a chat turn. The ceiling is
    #: higher than the sibling's 16000 because adaptive thinking and a
    #: multi-section article share this budget, and a truncated article is
    #: indistinguishable from a short one once it reaches a reviewer.
    HOWTO_GENERATION_MAX_TOKENS: int = 32000

    #: The build serving a request, echoed in the audit record.
    #:
    #: Stamped at deploy time from the image tag (the git SHA), so it identifies
    #: code rather than an AgentCore version number. Empty means unstamped, and
    #: the field is omitted from the response — deliberately distinguishable
    #: from a stamp reading "unknown".
    HOWTO_GENERATION_BUILD_VERSION: str = ""

    #: Serve canned articles instead of calling Bedrock. **Local only.**
    #:
    #: This exists because the entire pipeline around the model — slot
    #: resolution, the refusals, the merge, the measurement, the audit record —
    #: is exactly the part worth exercising end to end, and none of it needs a
    #: real model. Without this flag, running the feature locally would require
    #: AWS credentials, which means it would simply not be run locally.
    #:
    #: 🔴 Defaults to False, and a test asserts that default. When it is on, the
    #: server logs a warning on every startup naming the flag — canned prose is
    #: plausible enough to be mistaken for real output, and an article that
    #: reads a little oddly is a far quieter failure than one that never
    #: arrives.
    HOWTO_GENERATION_USE_STUB_MODEL: bool = False

    # --- Similarity (HOW-4.4) ----------------------------------------------
    #: MinHash permutation count. 256 gives a standard error of about
    #: 1/sqrt(256) ≈ 6% on the Jaccard estimate.
    #:
    #: ⚠️ Worth knowing when reading a stored score: the column is
    #: `numeric(7,4)`, so a score prints to four decimal places while the
    #: estimator behind it is good to roughly the second. The precision is
    #: storage precision, not measurement precision. It is kept because V2
    #: threshold calibration wants the raw number, not a rounded one — but a
    #: threshold set on the fourth decimal place would be measuring noise.
    HOWTO_GENERATION_MINHASH_PERMUTATIONS: int = 256

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
