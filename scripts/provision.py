#!/usr/bin/env python
"""Provision the how-to generation AgentCore runtime.

Idempotent: safe to re-run. Creating and updating both keep the SAME runtime ARN,
which matters because that ARN is what the gateway holds — a redeploy must not
invalidate it.

    python scripts/provision.py --check          # read-only inventory, creates nothing
    python scripts/provision.py                  # build, push, create/update
    python scripts/provision.py --skip-push      # re-point an existing image

Adapted from `aeo-skill-builder-runtime/scripts/provision.py`. The failure modes
it records were paid for on this account and are reproduced inline where they
bite, so nobody has to cross-reference to stay safe.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError

#: ⚠️ NOT the account default (`us-east-2`). The bedrock-agentcore grant carries
#: an `aws:RequestedRegion` condition, so a call from the default region is
#: denied with an access error that names no region at all.
REGION = "us-east-1"
ACCOUNT = "082585646836"

#: ⚠️ The namespace says "groundtruth" and this is NOT the ground-truth runtime.
#:
#: Deliberate, and a permissions artifact rather than a mistake. Our ECR grant is
#: resource-scoped: we may create and push under `aeo-groundtruth/*` and are
#: denied `ecr:CreateRepository` everywhere else. The sibling runtime carries the
#: same scar for the same reason.
ECR_REPO = "aeo-groundtruth/howto-generation"
REPO_URI = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO}"

#: Prefixed `AmazonBedrockAgentCore` DELIBERATELY, and it is not cosmetic.
#:
#: AWS's own AgentCore policy scopes `iam:PassRole` to
#: `arn:aws:iam::*:role/AmazonBedrockAgentCore*`. A role named anything else
#: needs a bespoke policy written and reviewed by an administrator — renaming
#: this makes the access request harder to grant, not tidier.
ROLE_NAME = "AmazonBedrockAgentCoreAEOHowtoGenerationRole"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
RUNTIME_NAME = "aeo_howto_generation"

#: The model the runtime calls. Kept here as well as in `config.py` because the
#: runtime reads its own default while the ROLE has to permit the exact model —
#: a mismatch is an access denial at the first generation, not at deploy.
MODEL_ID = "anthropic.claude-sonnet-5"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def image_tag() -> str:
    """The git description, so a deployed image traces to source.

    `--dirty` is not suppressed: a runtime built from uncommitted work should
    say so, and finding that out from the version string beats finding it out
    from behaviour.
    """
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--tags"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# --- ECR ---------------------------------------------------------------------


def ensure_repository(ecr, check_only: bool) -> None:
    try:
        ecr.describe_repositories(repositoryNames=[ECR_REPO])
        print(f"[ecr] exists: {ECR_REPO}")
        return
    except ClientError as error:
        if error.response["Error"]["Code"] != "RepositoryNotFoundException":
            raise
    if check_only:
        print(f"[ecr] MISSING: {ECR_REPO}")
        return
    ecr.create_repository(
        repositoryName=ECR_REPO,
        imageScanningConfiguration={"scanOnPush": True},
    )
    print(f"[ecr] created: {ECR_REPO}")


def build_and_push(ecr) -> str:
    """Build linux/arm64 and push. Returns the digest-pinned image URI.

    🔴 **`--platform linux/arm64` is required and cannot be inferred.** AgentCore
    runs arm64 only, and an amd64 image fails at DEPLOY rather than at build —
    so a machine that builds and pushes happily still produces a runtime that
    will not start. On an amd64 host this goes through QEMU and is slow; that is
    the correct trade against finding out later.
    """
    token = ecr.get_authorization_token()["authorizationData"][0]
    user, password = (
        base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
    )
    registry = token["proxyEndpoint"].replace("https://", "")

    _run(
        ["docker", "login", "--username", user, "--password-stdin", registry],
        input=password.encode(),
    )

    tag = image_tag()
    _run(
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/arm64",
            "-t",
            f"{REPO_URI}:{tag}",
            "-t",
            f"{REPO_URI}:latest",
            "--push",
            ".",
        ]
    )

    # 🔴 Pin by DIGEST, never by tag. `latest` is re-pointed by the next deploy,
    # and a runtime holding a tag would silently change what it runs the moment
    # somebody else pushed — including mid-incident, which is the worst time to
    # be uncertain about which code is live.
    described = ecr.describe_images(
        repositoryName=ECR_REPO, imageIds=[{"imageTag": tag}]
    )
    digest = described["imageDetails"][0]["imageDigest"]
    print(f"[ecr] pushed {tag} -> {digest}")
    return f"{REPO_URI}@{digest}"


# --- IAM ---------------------------------------------------------------------

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            # Confused-deputy guards. Without them any AgentCore runtime in any
            # account could ask to assume this role.
            "Condition": {
                "StringEquals": {"aws:SourceAccount": ACCOUNT},
                "ArnLike": {
                    "aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:*"
                },
            },
        }
    ],
}


def runtime_policy() -> dict:
    """What the runtime may do, and deliberately nothing more.

    ⚠️ **No database, no queue, no bucket, and that is the design.** This
    runtime is emit-only: it reads tenant-authored free text and feeds it to a
    model, and having nowhere to write is the containment. If a future change
    needs a write here, read `okf/business/emit-only.md` before adding it.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                # Cannot be resource-scoped — the API takes no resource.
                "Sid": "EcrTokenCannotBeScoped",
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*",
            },
            {
                "Sid": "PullTheRuntimeImage",
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                "Resource": f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{ECR_REPO}",
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/*",
            },
            {
                # Both the bare and the regional inference-profile forms. The
                # client resolves `anthropic.claude-sonnet-5` to a regional
                # profile at call time, so a policy naming only the bare id is
                # denied at the FIRST generation — after the deploy reported
                # success.
                "Sid": "InvokeTheModel",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
                    f"arn:aws:bedrock:*:{ACCOUNT}:inference-profile/us.anthropic.claude-*",
                ],
            },
            {
                # 🔴 **MANTLE IS A DIFFERENT SERVICE NAMESPACE**, and the
                # statement above does not cover it.
                #
                # `AnthropicBedrockMantle` does not call `bedrock:InvokeModel`
                # on a foundation model. It calls
                # `bedrock-mantle:CreateInference` on a PROJECT resource, and a
                # role holding only the `bedrock:*` grant is denied 403 at the
                # first generation — measured on the deployed runtime
                # 2026-09-04, after the deploy reported success and the image
                # started cleanly.
                #
                # ⚠️ The sibling runtime's role carries this statement under the
                # name `InvokeViaMantleWhichIsADifferentService`, i.e. this had
                # already been paid for once. Reading its provision script was
                # not enough — the answer was in its ROLE POLICY. When copying
                # a runtime, diff the live IAM too.
                "Sid": "InvokeViaMantleWhichIsADifferentService",
                "Effect": "Allow",
                "Action": [
                    "bedrock-mantle:CreateInference",
                    "bedrock-mantle:GetInference",
                    "bedrock-mantle:CancelInference",
                    "bedrock-mantle:GetProject",
                    "bedrock-mantle:ListProjects",
                    "bedrock-mantle:ListModels",
                    "bedrock-mantle:GetModel",
                    "bedrock-mantle:ListTagsForResource",
                ],
                "Resource": f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/*",
            },
        ],
    }


def ensure_role(iam, check_only: bool) -> str | None:
    try:
        iam.get_role(RoleName=ROLE_NAME)
        exists = True
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise
        exists = False

    if check_only:
        print(f"[iam] {'exists' if exists else 'MISSING'}: {ROLE_NAME}")
        return ROLE_ARN if exists else None

    if not exists:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
            Description="Execution role for the AEO how-to generation AgentCore runtime",
        )
        print(f"[iam] created role: {ROLE_NAME}")

    # Put on every run, not only on create: the policy is the thing most likely
    # to need correcting, and a redeploy that silently kept a stale one would
    # make "I fixed the permission" untrue in a way nothing reports.
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="AEOHowtoGenerationRuntimePolicy",
        PolicyDocument=json.dumps(runtime_policy()),
    )
    print("[iam] policy written")
    return ROLE_ARN


# --- Runtime -----------------------------------------------------------------


def find_runtime(control) -> dict | None:
    paginator = control.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for runtime in page.get("agentRuntimes", []):
            if runtime["agentRuntimeName"] == RUNTIME_NAME:
                return runtime
    return None


def ensure_runtime(control, container_uri: str | None, role_arn: str | None, check_only: bool):
    existing = find_runtime(control)

    if check_only:
        print(f"[runtime] {'exists' if existing else 'MISSING'}: {RUNTIME_NAME}")
        return existing["agentRuntimeArn"] if existing else None

    artifact = {"containerConfiguration": {"containerUri": container_uri}}

    #: HTTP, not AGUI — unlike the sibling. Generation is one request in and one
    #: article out; an event stream would be ceremony around a single result.
    protocol = {"serverProtocol": "HTTP"}

    #: A generation is a single long call, not a conversation. There is no user
    #: thinking between turns to keep a container warm for, so the idle timeout
    #: is short: a warm runtime waiting is a runtime nobody is using.
    lifecycle = {"idleRuntimeSessionTimeout": 300, "maxLifetime": 3600}

    #: ⚠️ Passed on BOTH paths, because `update_agent_runtime` is a full REPLACE
    #: and not a merge. Omitting it on update silently wipes what create set —
    #: invisible while the values match the defaults baked into `config.py`, and
    #: surfacing the first time a non-default matters, several deploys later.
    #:
    #: 🔴 `HOWTO_GENERATION_USE_STUB_MODEL` is deliberately NOT set here. Its
    #: default is off, and naming it in a deploy — even as "false" — puts the
    #: string one careless edit away from serving canned articles in production.
    build_version = f"{image_tag()}@{(container_uri or '').rsplit(':', 1)[-1][:12]}"
    environment = {
        "HOWTO_GENERATION_MODEL_ID": MODEL_ID,
        "HOWTO_GENERATION_AWS_REGION": REGION,
        "HOWTO_GENERATION_BUILD_VERSION": build_version,
    }

    if existing:
        response = control.update_agent_runtime(
            agentRuntimeId=existing["agentRuntimeId"],
            agentRuntimeArtifact=artifact,
            networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration=protocol,
            roleArn=role_arn,
            lifecycleConfiguration=lifecycle,
            environmentVariables=environment,
        )
        print(f"[runtime] updated to version {response.get('agentRuntimeVersion')}")
        return existing["agentRuntimeArn"]

    response = control.create_agent_runtime(
        agentRuntimeName=RUNTIME_NAME,
        description="AEO how-to article generation (HOW-4)",
        agentRuntimeArtifact=artifact,
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration=protocol,
        roleArn=role_arn,
        lifecycleConfiguration=lifecycle,
        environmentVariables=environment,
    )
    print(f"[runtime] created: {response['agentRuntimeArn']} ({response['status']})")
    return response["agentRuntimeArn"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Inventory only; create nothing")
    parser.add_argument("--skip-push", action="store_true", help="Reuse the image already in ECR")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    ecr = session.client("ecr")
    iam = session.client("iam")
    control = session.client("bedrock-agentcore-control")

    ensure_repository(ecr, args.check)
    role_arn = ensure_role(iam, args.check)

    container_uri = None
    if not args.check:
        if args.skip_push:
            described = ecr.describe_images(
                repositoryName=ECR_REPO, imageIds=[{"imageTag": "latest"}]
            )
            container_uri = f"{REPO_URI}@{described['imageDetails'][0]['imageDigest']}"
            print(f"[ecr] reusing {container_uri}")
        else:
            container_uri = build_and_push(ecr)

    arn = ensure_runtime(control, container_uri, role_arn, args.check)
    if arn and not args.check:
        print("")
        print("Set this in aeo-backend/.env — the ARN WINS over the URL:")
        print(f"  HOWTO_GENERATION_RUNTIME_ARN={arn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
