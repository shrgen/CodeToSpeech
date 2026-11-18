#!/usr/bin/env bash
# Package and deploy the recommendation API (Lambda + HTTP API) and the observability stack.
# Usage: deploy/deploy_api.sh <artifact-bucket> [mock|bedrock] [region] [alarm-email]
set -euo pipefail
BUCKET=${1:?usage: deploy/deploy_api.sh <artifact-bucket> [mock|bedrock] [region] [alarm-email]}
BRAIN=${2:-mock}
REGION=${3:-us-east-1}
EMAIL=${4:-}
cd "$(dirname "$0")/.."
BUILD=$(mktemp -d)
cp -r claimsense releases "$BUILD/"
find "$BUILD" -name __pycache__ -prune -exec rm -rf {} +
if [ "$BRAIN" = "bedrock" ]; then
  pip install --quiet --target "$BUILD" --platform manylinux2014_x86_64 --only-binary=:all: \
    --python-version 3.12 "openai-agents[litellm]>=0.3" "pydantic>=2.6"
fi
KEY="claimsense/lambda-$(date +%Y%m%d%H%M%S).zip"
(cd "$BUILD" && zip -qr lambda.zip .)
aws s3 cp "$BUILD/lambda.zip" "s3://$BUCKET/$KEY" --region "$REGION"
aws cloudformation deploy --region "$REGION" --stack-name claimsense-api --capabilities CAPABILITY_IAM \
  --template-file deploy/api.yaml --parameter-overrides CodeBucket="$BUCKET" CodeKey="$KEY" Brain="$BRAIN"
aws cloudformation deploy --region "$REGION" --stack-name claimsense-observability \
  --template-file ops/cloudwatch/observability.yaml --parameter-overrides AlarmEmail="$EMAIL"
aws cloudformation describe-stacks --region "$REGION" --stack-name claimsense-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
rm -rf "$BUILD"
